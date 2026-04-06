import re
from urllib.parse import urlparse, parse_qs

import streamlit as st
import streamlit.components.v1 as components
from googleapiclient.discovery import build

from config import MAX_RESULTS_PER_PAGE, SUPPORTED_LANGUAGES
from analysis import add_sentiment, cluster_into_themes
from translate import translate_keywords, add_back_translations
from report import build_html_report, build_pdf_report


def get_youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


def search_videos(youtube, query: str, max_results: int = 20) -> list[dict]:
    """Search for videos matching a query and return video metadata."""
    videos = []
    request = youtube.search().list(
        q=query,
        part="snippet",
        type="video",
        maxResults=min(max_results, MAX_RESULTS_PER_PAGE),
    )
    while request and len(videos) < max_results:
        response = request.execute()
        for item in response["items"]:
            videos.append(
                {
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                }
            )
        request = youtube.search().list_next(request, response)
    return videos[:max_results]


def extract_video_ids(text: str) -> list[str]:
    """Extract YouTube video IDs from URLs or raw IDs, one per line."""
    ids = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Try parsing as a URL first
        parsed = urlparse(line)
        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            vid = parse_qs(parsed.query).get("v", [None])[0]
            if vid:
                ids.append(vid)
                continue
        if parsed.hostname == "youtu.be":
            vid = parsed.path.lstrip("/").split("/")[0]
            if vid:
                ids.append(vid)
                continue
        # Try extracting an 11-char video ID from the string
        match = re.search(r"[A-Za-z0-9_-]{11}", line)
        if match:
            ids.append(match.group())
    return ids


def get_video_info(youtube, video_ids: list[str]) -> list[dict]:
    """Fetch video titles for a list of video IDs."""
    videos = []
    # API allows up to 50 IDs per call
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        response = youtube.videos().list(
            part="snippet", id=",".join(batch)
        ).execute()
        for item in response.get("items", []):
            videos.append(
                {"video_id": item["id"], "title": item["snippet"]["title"]}
            )
    return videos


def fetch_comments(youtube, video_id: str, max_comments: int = 100) -> list[dict]:
    """Fetch top-level comments for a video."""
    comments = []
    request = youtube.commentThreads().list(
        part="snippet",
        videoId=video_id,
        maxResults=min(max_comments, MAX_RESULTS_PER_PAGE),
        textFormat="plainText",
    )
    while request and len(comments) < max_comments:
        try:
            response = request.execute()
        except Exception:
            break
        for item in response["items"]:
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append(
                {
                    "author": snippet["authorDisplayName"],
                    "comment": snippet["textDisplay"],
                    "likes": snippet["likeCount"],
                    "replies": item["snippet"]["totalReplyCount"],
                    "date": snippet["publishedAt"],
                    "video_id": video_id,
                }
            )
        request = youtube.commentThreads().list_next(request, response)
    return comments[:max_comments]


def filter_comments(
    comments: list[dict],
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[dict]:
    """Keep comments where any keyword appears and no exclude keyword appears (case-insensitive)."""
    if not keywords:
        return comments
    exclude_keywords = exclude_keywords or []
    results = []
    for c in comments:
        text = c["comment"].lower()
        if not any(kw.lower() in text for kw in keywords):
            continue
        if exclude_keywords and any(ex.lower() in text for ex in exclude_keywords):
            continue
        results.append(c)
    return results


def main():
    st.set_page_config(page_title="YouTube Comment Scraper", layout="wide")
    st.title("💬 YouTube Comment Scraper")
    st.caption("Search · Analyze sentiment · Discover themes · Export PDF")

    api_key = st.secrets.get("YOUTUBE_API_KEY", "")
    if not api_key:
        st.error(
            "Missing `YOUTUBE_API_KEY`. Add it to **Streamlit secrets** "
            "(`.streamlit/secrets.toml` locally or the Secrets panel on Streamlit Cloud)."
        )
        return

    # --- Sidebar ---
    st.sidebar.header("Settings")
    max_videos = st.sidebar.slider("Max videos to search", 1, 50, 10)
    max_scan = st.sidebar.number_input(
        "Comments to scan per video", min_value=100, max_value=250_000,
        value=5000, step=1000,
        help="How deep to search into each video's comments for keyword matches. "
             "Set high for viral videos with 200k+ comments.",
    )
    max_matches = st.sidebar.number_input(
        "Max matched comments to return", min_value=10, max_value=10_000,
        value=200, step=50,
        help="Stop collecting once this many keyword-matched comments are found across all videos.",
    )
    max_themes = st.sidebar.slider("Max themes", 2, 12, 6)

    st.sidebar.header("Multi-Language Search")
    selected_langs = st.sidebar.multiselect(
        "Also search in these languages",
        options=list(SUPPORTED_LANGUAGES.keys()),
        help="Keywords will be translated and used to search for comments in each selected language. "
             "Matching comments will include a back-translation to English.",
    )

    # --- Main inputs ---
    input_mode = st.radio(
        "How do you want to find videos?",
        ["Paste video URLs", "Search YouTube"],
        horizontal=True,
    )

    if input_mode == "Paste video URLs":
        url_input = st.text_area(
            "YouTube video URLs (one per line)",
            placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://youtu.be/abc123XYZab",
            height=120,
        )
    else:
        search_query = st.text_input(
            "Search YouTube for videos",
            placeholder="e.g. python tutorial",
        )

    keyword_input = st.text_input(
        "Filter comments by keywords (comma-separated)",
        placeholder="e.g. great, awesome, helpful",
    )
    keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

    exclude_input = st.text_input(
        "Exclude comments containing (comma-separated)",
        placeholder="e.g. spam, subscribe, giveaway",
        help="Comments matching any of these words will be excluded, even if they match the keywords above.",
    )
    exclude_keywords = [k.strip() for k in exclude_input.split(",") if k.strip()]

    if st.button("Fetch & Analyze", type="primary"):
        if not keywords:
            st.warning("Enter at least one keyword to filter comments.")
            return

        youtube = get_youtube_client(api_key)

        # --- Resolve target videos ---
        if input_mode == "Paste video URLs":
            video_ids = extract_video_ids(url_input if "url_input" in dir() else "")
            if not video_ids:
                st.warning("Please paste at least one valid YouTube URL.")
                return
            with st.spinner("Looking up videos..."):
                direct_videos = get_video_info(youtube, video_ids)
            if not direct_videos:
                st.error("Could not find any of the provided video IDs.")
                return
            search_query = ", ".join(video_ids)
        else:
            if not search_query:
                st.warning("Please enter a search query.")
                return
            direct_videos = None

        # --- Build search queries per language ---
        search_plans = [{"keywords": keywords, "lang": None}]

        if selected_langs:
            with st.spinner("Translating keywords..."):
                for lang_name in selected_langs:
                    lang_code = SUPPORTED_LANGUAGES[lang_name]
                    translated_kw = translate_keywords(keywords, lang_code)
                    if translated_kw:
                        search_plans.append(
                            {
                                "keywords": translated_kw,
                                "lang": lang_code,
                            }
                        )

        # --- Fetch comments for all languages ---
        all_comments: list[dict] = []
        total_plans = len(search_plans)

        for plan in search_plans:
            lang_label = plan["lang"] or "English"

            # Get videos: use direct list or search
            if direct_videos is not None:
                videos = direct_videos
            else:
                translated_query = " ".join(plan["keywords"]) if plan["lang"] else search_query
                with st.spinner(f"Searching videos ({lang_label})..."):
                    videos = search_videos(youtube, translated_query, max_videos)

            if not videos:
                continue

            progress = st.progress(0, text=f"Fetching comments ({lang_label})...")
            for i, video in enumerate(videos):
                if len(all_comments) >= max_matches:
                    break
                comments = fetch_comments(youtube, video["video_id"], max_scan)
                for c in comments:
                    c["video_title"] = video["title"]
                filtered = filter_comments(comments, plan["keywords"], exclude_keywords)

                if plan["lang"]:
                    filtered = add_back_translations(filtered, plan["lang"])

                remaining = max_matches - len(all_comments)
                all_comments.extend(filtered[:remaining])
                progress.progress((i + 1) / len(videos))
            progress.empty()

        if not all_comments:
            st.warning("No comments matched your keywords in any language.")
            return

        # --- Analysis ---
        with st.spinner("Analyzing sentiment..."):
            all_comments = add_sentiment(all_comments)

        with st.spinner("Discovering themes..."):
            all_comments = cluster_into_themes(all_comments, max_themes=max_themes)

        st.success(
            f"Analyzed **{len(all_comments)}** matched comments "
            f"across **{total_plans}** language(s)."
        )

        # Assign each comment a stable id for hiding
        for idx, c in enumerate(all_comments):
            c["_id"] = idx

        # Store in session state
        st.session_state["all_comments"] = all_comments
        st.session_state["hidden_ids"] = set()
        st.session_state["search_query"] = search_query
        st.session_state["keywords"] = keywords

    # --- Nothing fetched yet ---
    if "all_comments" not in st.session_state:
        return

    all_comments = st.session_state["all_comments"]
    hidden_ids = st.session_state["hidden_ids"]

    # --- Hide comments UI ---
    st.divider()
    st.subheader("Review Comments")
    st.caption(
        "Un-check any comment to exclude it from the preview and PDF export."
    )

    visible_comments = []
    for c in all_comments:
        cid = c["_id"]
        # Build a short label: author + first 80 chars of comment
        preview = c["comment"][:80].replace("\n", " ")
        label = f"**{c['author']}**: {preview}..."
        kept = st.checkbox(label, value=(cid not in hidden_ids), key=f"cb_{cid}")
        if kept:
            hidden_ids.discard(cid)
            visible_comments.append(c)
        else:
            hidden_ids.add(cid)

    st.session_state["hidden_ids"] = hidden_ids

    if not visible_comments:
        st.warning("All comments are hidden. Check at least one to generate a report.")
        return

    hidden_count = len(all_comments) - len(visible_comments)
    if hidden_count:
        st.info(f"Hiding **{hidden_count}** comment(s). Report will include **{len(visible_comments)}**.")

    # --- Build report from visible comments only ---
    query = st.session_state["search_query"]
    kws = st.session_state["keywords"]
    html_report = build_html_report(visible_comments, query, kws)
    pdf_bytes = build_pdf_report(visible_comments, query, kws)

    st.divider()
    st.subheader("Report Preview")
    components.html(html_report, height=800, scrolling=True)

    # --- PDF download ---
    st.download_button(
        label="Download PDF Report",
        data=pdf_bytes,
        file_name="youtube_comment_report.pdf",
        mime="application/pdf",
        type="primary",
    )


if __name__ == "__main__":
    main()

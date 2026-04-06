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


def filter_comments(comments: list[dict], keywords: list[str]) -> list[dict]:
    """Keep comments where any keyword appears (case-insensitive)."""
    if not keywords:
        return comments
    return [
        c
        for c in comments
        if any(kw.lower() in c["comment"].lower() for kw in keywords)
    ]


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
    max_scan = st.sidebar.slider(
        "Comments to scan per video", 10, 1000, 200,
        help="How deep to search into each video's comments for keyword matches.",
    )
    max_matches = st.sidebar.slider(
        "Max matched comments to return", 10, 500, 100,
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
    search_query = st.text_input(
        "Search YouTube for videos",
        placeholder="e.g. python tutorial",
    )
    keyword_input = st.text_input(
        "Filter comments by keywords (comma-separated)",
        placeholder="e.g. great, awesome, helpful",
    )
    keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

    if st.button("Fetch & Analyze", type="primary"):
        if not search_query:
            st.warning("Please enter a search query.")
            return
        if not keywords:
            st.warning("Enter at least one keyword to filter comments.")
            return

        youtube = get_youtube_client(api_key)

        # --- Build search queries per language ---
        search_plans = [{"query": search_query, "keywords": keywords, "lang": None}]

        if selected_langs:
            with st.spinner("Translating keywords..."):
                for lang_name in selected_langs:
                    lang_code = SUPPORTED_LANGUAGES[lang_name]
                    translated_kw = translate_keywords(keywords, lang_code)
                    if translated_kw:
                        translated_query = " ".join(translated_kw)
                        search_plans.append(
                            {
                                "query": translated_query,
                                "keywords": translated_kw,
                                "lang": lang_code,
                            }
                        )

        # --- Fetch comments for all languages ---
        all_comments: list[dict] = []
        total_plans = len(search_plans)

        for plan_idx, plan in enumerate(search_plans):
            lang_label = plan["lang"] or "English"
            with st.spinner(f"Searching videos ({lang_label})..."):
                videos = search_videos(youtube, plan["query"], max_videos)

            if not videos:
                continue

            progress = st.progress(0, text=f"Fetching comments ({lang_label})...")
            for i, video in enumerate(videos):
                if len(all_comments) >= max_matches:
                    break
                comments = fetch_comments(youtube, video["video_id"], max_scan)
                for c in comments:
                    c["video_title"] = video["title"]
                filtered = filter_comments(comments, plan["keywords"])

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

        # --- Build report ---
        html_report = build_html_report(all_comments, search_query, keywords)

        # Build PDF while we have the data
        pdf_bytes = build_pdf_report(all_comments, search_query, keywords)

        # Store in session state so it persists across reruns
        st.session_state["report_html"] = html_report
        st.session_state["report_pdf"] = pdf_bytes

    # --- Display report if available ---
    if "report_html" not in st.session_state:
        return

    st.divider()
    st.subheader("Report Preview")
    components.html(st.session_state["report_html"], height=800, scrolling=True)

    # --- PDF download ---
    st.download_button(
        label="Download PDF Report",
        data=st.session_state["report_pdf"],
        file_name="youtube_comment_report.pdf",
        mime="application/pdf",
        type="primary",
    )


if __name__ == "__main__":
    main()

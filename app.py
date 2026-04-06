import re
import json
import html as html_mod
from urllib.parse import urlparse, parse_qs

import anthropic
import streamlit as st
from googleapiclient.discovery import build

from config import MAX_RESULTS_PER_PAGE, SUPPORTED_LANGUAGES, SENTIMENT_COLORS
from analysis import add_sentiment, cluster_into_themes, get_theme_summary, get_sentiment_counts
from translate import translate_keywords, add_back_translations
from report import (
    build_html_report, build_pdf_report,
    _sentiment_badge, _avatar_color, _initials, _format_date,
)


def generate_ai_summary(comments: list[dict], search_query: str) -> str:
    """Generate an AI summary of themes using Claude."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""

    themes = get_theme_summary(comments)
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)

    # Build a concise prompt with theme data and sample comments
    theme_blocks = []
    for theme_name, theme_comments in themes.items():
        t_counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
        for c in theme_comments:
            t_counts[c["sentiment_label"]] += 1
        samples = [c["comment"][:200] for c in theme_comments[:5]]
        theme_blocks.append(
            f"Theme: {theme_name} ({len(theme_comments)} comments)\n"
            f"Sentiment: +{t_counts['Positive']} ~{t_counts['Neutral']} -{t_counts['Negative']}\n"
            f"Sample comments:\n" + "\n".join(f"- {s}" for s in samples)
        )

    prompt = (
        f"Analyze these YouTube comment themes from a search for \"{search_query}\".\n"
        f"Total: {total} comments | "
        f"+{sentiment_counts['Positive']} positive, "
        f"~{sentiment_counts['Neutral']} neutral, "
        f"-{sentiment_counts['Negative']} negative.\n\n"
        + "\n\n".join(theme_blocks)
        + "\n\nWrite a concise summary (3-5 paragraphs) of the key themes and sentiment "
        "patterns in these comments. What are people talking about? What's the overall "
        "tone? Are there notable points of agreement or disagreement? "
        "Be specific and reference the actual topics, not generic observations."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"*Could not generate AI summary: {e}*"


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
        match = re.search(r"[A-Za-z0-9_-]{11}", line)
        if match:
            ids.append(match.group())
    return ids


def get_video_info(youtube, video_ids: list[str]) -> list[dict]:
    """Fetch video titles for a list of video IDs."""
    videos = []
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


def fetch_replies(youtube, parent_id: str) -> list[dict]:
    """Fetch all replies for a top-level comment."""
    replies = []
    request = youtube.comments().list(
        part="snippet",
        parentId=parent_id,
        maxResults=100,
        textFormat="plainText",
    )
    while request:
        try:
            response = request.execute()
        except Exception:
            break
        for item in response["items"]:
            s = item["snippet"]
            replies.append(
                {
                    "author": s["authorDisplayName"],
                    "comment": s["textDisplay"],
                    "likes": s["likeCount"],
                    "replies": 0,
                    "date": s["publishedAt"],
                    "video_id": s["videoId"],
                    "is_reply": True,
                    "parent_id": parent_id,
                }
            )
        request = youtube.comments().list_next(request, response)
    return replies


def fetch_comments(
    youtube, video_id: str, max_comments: int = 100, include_replies: bool = False
) -> list[dict]:
    """Fetch top-level comments (and optionally replies) for a video."""
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
            thread_id = item["snippet"]["topLevelComment"]["id"]
            reply_count = item["snippet"]["totalReplyCount"]
            comments.append(
                {
                    "author": snippet["authorDisplayName"],
                    "comment": snippet["textDisplay"],
                    "likes": snippet["likeCount"],
                    "replies": reply_count,
                    "date": snippet["publishedAt"],
                    "video_id": video_id,
                    "is_reply": False,
                    "comment_id": thread_id,
                }
            )
            if include_replies and reply_count > 0:
                replies = fetch_replies(youtube, thread_id)
                comments.extend(replies)
        request = youtube.commentThreads().list_next(request, response)
    return comments[:max_comments]


def filter_comments(
    comments: list[dict],
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[dict]:
    """Keep comments where any keyword appears and no exclude keyword appears (case-insensitive)."""
    if not keywords:
        return list(comments)
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


# ---------------------------------------------------------------------------
# Apply filters + analysis to the cached raw comments (no API calls)
# ---------------------------------------------------------------------------
def apply_filters_and_analysis(
    raw_comments: list[dict],
    keywords: list[str],
    exclude_keywords: list[str],
    search_all: bool,
    selected_lang_codes: list[str],
    no_match_limit: bool,
    max_matches: float,
) -> list[dict]:
    """Filter, translate, sentiment-score, and cluster cached comments."""
    if search_all:
        matched = [dict(c) for c in raw_comments]  # shallow copies
    else:
        # Build all keyword sets (English + translated)
        all_kw_sets: list[tuple[list[str], str | None]] = [(keywords, None)]
        for lang_code in selected_lang_codes:
            translated_kw = translate_keywords(keywords, lang_code)
            if translated_kw:
                all_kw_sets.append((translated_kw, lang_code))

        # Match against each keyword set, deduplicate, track language
        seen: set[int] = set()
        matched: list[dict] = []
        for idx, c in enumerate(raw_comments):
            for plan_kws, plan_lang in all_kw_sets:
                text = c["comment"].lower()
                if not any(kw.lower() in text for kw in plan_kws):
                    continue
                if exclude_keywords and any(ex.lower() in text for ex in exclude_keywords):
                    continue
                if idx in seen:
                    continue
                seen.add(idx)
                copy = dict(c)
                if plan_lang:
                    copy["_needs_bt"] = plan_lang
                matched.append(copy)
                break  # first matching keyword set wins

        # Back-translate comments that matched via non-English keywords
        needs_bt = [m for m in matched if m.get("_needs_bt")]
        if needs_bt:
            by_lang: dict[str, list[dict]] = {}
            for m in needs_bt:
                by_lang.setdefault(m.pop("_needs_bt"), []).append(m)
            for lang_code, group in by_lang.items():
                add_back_translations(group, lang_code)

    # Apply match limit
    if not no_match_limit and len(matched) > max_matches:
        matched = matched[: int(max_matches)]

    if not matched:
        return []

    # Sentiment + themes
    add_sentiment(matched)
    cluster_into_themes(matched)

    # Assign stable IDs
    for idx, c in enumerate(matched):
        c["_id"] = idx

    return matched


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

    # --- Sidebar: Fetch settings ---
    st.sidebar.header("Fetch Settings")
    max_scan = st.sidebar.number_input(
        "Comments to scan per video", min_value=100, max_value=250_000,
        value=5000, step=1000,
        help="How deep to search into each video's comments for keyword matches. "
             "Set high for viral videos with 200k+ comments.",
    )
    include_replies = st.sidebar.checkbox(
        "Include replies",
        help="Fetch replies under each top-level comment. Uses 1 additional API call "
             "per top-level comment that has replies.",
    )

    # --- Load previous export ---
    st.sidebar.header("Load Previous Export")
    uploaded = st.sidebar.file_uploader(
        "Upload a comments JSON export",
        type=["json"],
        help="Load a previously exported comments file to re-analyze without fetching from YouTube.",
    )
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read())
            st.session_state["raw_comments"] = data["comments"]
            st.session_state["search_query"] = data.get("search_query", "Imported")
            st.session_state.pop("analyzed_comments", None)
            st.session_state.pop("hidden_ids", None)
            st.sidebar.success(f"Loaded **{len(data['comments']):,}** comments.")
        except Exception as e:
            st.sidebar.error(f"Failed to load file: {e}")

    # --- Main inputs: video source ---
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
        max_videos = st.slider("Max videos to search", 1, 50, 10)

    # --- Quota estimate ---
    if input_mode == "Paste video URLs":
        _est_videos = len(extract_video_ids(url_input)) if url_input.strip() else 1
        _search_cost = 0
    else:
        _est_videos = max_videos
        _search_cost = ((_est_videos + 49) // 50) * 100

    _pages_per_video = (max_scan + 99) // 100
    _comment_cost = _est_videos * _pages_per_video
    _total_est = _search_cost + _comment_cost

    _pct = min(_total_est / 10_000 * 100, 100)
    _color = "🟢" if _pct < 25 else "🟡" if _pct < 60 else "🔴"
    st.sidebar.divider()
    st.sidebar.markdown(
        f"### API Quota Estimate\n"
        f"{_color} **~{_total_est:,} units** of 10,000 daily quota ({_pct:.0f}%)\n\n"
        f"<small>{_est_videos} video(s) &times; {_pages_per_video:,} pages/video"
        f"{f' + {_search_cost} search' if _search_cost else ''}</small>",
        unsafe_allow_html=True,
    )

    # ===================================================================
    # PHASE 1: FETCH — hits the API, stores raw comments in session state
    # ===================================================================
    if st.button("Fetch Comments", type="primary"):
        youtube = get_youtube_client(api_key)

        if input_mode == "Paste video URLs":
            video_ids = extract_video_ids(url_input)
            if not video_ids:
                st.warning("Please paste at least one valid YouTube URL.")
                return
            with st.spinner("Looking up videos..."):
                videos = get_video_info(youtube, video_ids)
            if not videos:
                st.error("Could not find any of the provided video IDs.")
                return
            sq = ", ".join(v["title"] for v in videos)
        else:
            if not search_query:
                st.warning("Please enter a search query.")
                return
            with st.spinner("Searching videos..."):
                videos = search_videos(youtube, search_query, max_videos)
            if not videos:
                st.warning("No videos found.")
                return
            sq = search_query

        raw_comments: list[dict] = []
        progress = st.progress(0, text="Fetching comments...")
        for i, video in enumerate(videos):
            batch = fetch_comments(youtube, video["video_id"], max_scan, include_replies)
            for c in batch:
                c["video_title"] = video["title"]
            raw_comments.extend(batch)
            progress.progress((i + 1) / len(videos))
        progress.empty()

        # Store raw (unfiltered) comments
        st.session_state["raw_comments"] = raw_comments
        st.session_state["search_query"] = sq
        st.session_state.pop("analyzed_comments", None)
        st.session_state.pop("hidden_ids", None)

        st.success(f"Fetched **{len(raw_comments):,}** comments from **{len(videos)}** video(s).")

    # --- Nothing fetched yet ---
    if "raw_comments" not in st.session_state:
        return

    raw_comments = st.session_state["raw_comments"]
    sq = st.session_state["search_query"]

    # --- Download raw export ---
    st.divider()
    export_data = json.dumps(
        {"search_query": sq, "comments": raw_comments},
        ensure_ascii=False,
    ).encode("utf-8")

    col_info, col_dl = st.columns([0.7, 0.3])
    with col_info:
        st.subheader("Filter & Analyze")
        st.caption(
            f"**{len(raw_comments):,}** cached comments available. "
            "Change filters and re-analyze without re-fetching."
        )
    with col_dl:
        st.download_button(
            label="Export Raw Comments (JSON)",
            data=export_data,
            file_name="youtube_comments_raw.json",
            mime="application/json",
        )

    search_all = st.checkbox(
        "Return all comments (skip keyword filter)",
        help="Include every comment without keyword filtering. "
             "Useful when you want to analyze all discussion on specific videos.",
    )

    if not search_all:
        keyword_input = st.text_input(
            "Filter comments by keywords (comma-separated)",
            placeholder="e.g. great, awesome, helpful",
        )
        keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

        exclude_input = st.text_input(
            "Exclude comments containing (comma-separated)",
            placeholder="e.g. spam, subscribe, giveaway",
            help="Comments matching any of these words will be excluded.",
        )
        exclude_keywords = [k.strip() for k in exclude_input.split(",") if k.strip()]
    else:
        keywords = []
        exclude_keywords = []

    # --- Sidebar: analysis settings (only shown after fetch) ---
    st.sidebar.header("Analysis Settings")
    no_match_limit = st.sidebar.checkbox(
        "Return all matched comments (no limit)",
        help="When checked, every keyword match is kept.",
    )
    if no_match_limit:
        max_matches = float("inf")
    else:
        max_matches = st.sidebar.number_input(
            "Max matched comments to return", min_value=10, max_value=10_000,
            value=200, step=50,
            help="Cap the number of matched comments to analyze.",
        )

    st.sidebar.header("Multi-Language Search")
    selected_langs = st.sidebar.multiselect(
        "Also search in these languages",
        options=list(SUPPORTED_LANGUAGES.keys()),
        help="Keywords will be translated and matched against cached comments. "
             "Matching comments will include a back-translation to English.",
    )
    selected_lang_codes = [SUPPORTED_LANGUAGES[n] for n in selected_langs]

    if st.button("Apply Filters & Analyze", type="primary"):
        if not search_all and not keywords:
            st.warning("Enter at least one keyword or check 'Return all comments'.")
            return

        with st.spinner("Filtering and analyzing..."):
            analyzed = apply_filters_and_analysis(
                raw_comments,
                keywords,
                exclude_keywords,
                search_all,
                selected_lang_codes,
                no_match_limit,
                max_matches,
            )

        if not analyzed:
            st.warning("No comments matched your filters.")
            return

        with st.spinner("Generating AI theme summary..."):
            ai_summary = generate_ai_summary(analyzed, sq)

        st.session_state["analyzed_comments"] = analyzed
        st.session_state["hidden_ids"] = set()
        st.session_state["keywords"] = keywords
        st.session_state["ai_summary"] = ai_summary
        st.success(f"**{len(analyzed):,}** comments match your filters.")

    # --- Nothing analyzed yet ---
    if "analyzed_comments" not in st.session_state:
        return

    all_comments = st.session_state["analyzed_comments"]
    hidden_ids = st.session_state.get("hidden_ids", set())
    kws = st.session_state.get("keywords", [])
    ai_summary = st.session_state.get("ai_summary", "")

    # --- Preview ---
    st.divider()
    st.subheader("Report Preview")

    # --- AI Theme Summary ---
    if ai_summary:
        with st.expander("**AI Theme Summary**", expanded=True):
            st.markdown(ai_summary)

    st.caption("Un-check any comment to exclude it from the report and PDF.")

    # --- Video filter ---
    all_video_titles = sorted(set(c.get("video_title", "") for c in all_comments))
    if len(all_video_titles) > 1:
        selected_videos = st.multiselect(
            "Filter by video",
            options=all_video_titles,
            default=all_video_titles,
            help="Show only comments from the selected videos.",
        )
        display_comments = [c for c in all_comments if c.get("video_title") in selected_videos]
    else:
        display_comments = all_comments

    sentiment_counts = get_sentiment_counts(display_comments)
    total = len(display_comments)

    # Overall sentiment bar
    if total > 0:
        _bar_html = ""
        for label in ["Positive", "Neutral", "Negative"]:
            count = sentiment_counts.get(label, 0)
            pct = count / total * 100
            color = SENTIMENT_COLORS[label]
            emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}[label]
            if pct > 0:
                _bar_html += (
                    f'<div style="flex:{pct};background:{color};height:32px;'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'color:#fff;font-size:12px;font-weight:600;'
                    f'min-width:{40 if pct > 3 else 0}px;">'
                    f'{emoji} {count} ({pct:.0f}%)</div>'
                )
        st.html(
            f'<div style="display:flex;border-radius:12px;overflow:hidden;'
            f'margin:8px 0 16px 0;">{_bar_html}</div>'
        )

    # Group comments by sentiment
    sentiment_groups = {}
    for label in ["Positive", "Neutral", "Negative"]:
        group = [c for c in display_comments if c["sentiment_label"] == label]
        if group:
            sentiment_groups[label] = group

    # Render sentiment-grouped comment cards with checkboxes
    visible_comments = []
    for label, group_comments in sentiment_groups.items():
        emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}[label]
        color = SENTIMENT_COLORS[label]
        with st.expander(f"**{emoji} {label}** — {len(group_comments)} comments", expanded=True):
            for c in group_comments:
                cid = c["_id"]

                col_cb, col_card, col_sent = st.columns([0.03, 0.82, 0.15], vertical_alignment="top")
                with col_cb:
                    kept = st.checkbox(
                        "include",
                        value=(cid not in hidden_ids),
                        key=f"cb_{cid}",
                        label_visibility="collapsed",
                    )
                if kept:
                    hidden_ids.discard(cid)
                    visible_comments.append(c)
                else:
                    hidden_ids.add(cid)

                with col_sent:
                    sentiment_options = ["Positive", "Neutral", "Negative"]
                    current = c["sentiment_label"]
                    new_sentiment = st.selectbox(
                        "Sentiment",
                        options=sentiment_options,
                        index=sentiment_options.index(current),
                        key=f"sent_{cid}",
                        label_visibility="collapsed",
                    )
                    if new_sentiment != current:
                        c["sentiment_label"] = new_sentiment
                        c["sentiment_override"] = True

                with col_card:
                    avatar_bg = _avatar_color(c["author"])
                    initials = _initials(c["author"])
                    date_str = _format_date(c["date"])
                    sentiment = _sentiment_badge(c["sentiment_label"])
                    opacity = "1" if kept else "0.35"

                    reply_marker = ""
                    if c.get("is_reply"):
                        reply_marker = (
                            '<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
                            'font-size:10px;font-weight:500;color:#6366f1;background:#eef2ff;'
                            'margin-right:6px;">↩ reply</span>'
                        )

                    likes_html = ""
                    if c.get("likes", 0) > 0:
                        likes_html = f'<span style="color:#606060;font-size:12px;margin-right:10px;">👍 {c["likes"]}</span>'
                    replies_html = ""
                    if c.get("replies", 0) > 0:
                        replies_html = f'<span style="color:#606060;font-size:12px;">💬 {c["replies"]}</span>'

                    translation_html = ""
                    if c.get("back_translation") and c.get("original_language"):
                        bt = html_mod.escape(c["back_translation"])
                        translation_html = (
                            f'<div style="margin-top:8px;padding:8px 12px;background:#f0f4ff;'
                            f'border-left:3px solid #6366f1;border-radius:4px;font-size:13px;'
                            f'color:#4a5568;font-style:italic;">🌐 English: {bt}</div>'
                        )

                    comment_text = html_mod.escape(c["comment"])
                    author_text = html_mod.escape(c["author"])

                    video_tag_html = ""
                    if len(all_video_titles) > 1 and c.get("video_title"):
                        vt = html_mod.escape(c["video_title"])
                        video_tag_html = (
                            f'<div style="margin-bottom:6px;">'
                            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                            f'font-size:11px;font-weight:500;color:#4a5568;background:#f3f4f6;">'
                            f'🎬 {vt}</span></div>'
                        )

                    st.html(f"""
                    <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f0f0f0;opacity:{opacity};">
                      <div style="flex-shrink:0;width:40px;height:40px;border-radius:50%;
                                  background:{avatar_bg};display:flex;align-items:center;
                                  justify-content:center;color:#fff;font-weight:700;font-size:14px;">
                        {initials}
                      </div>
                      <div style="flex:1;min-width:0;">
                        {video_tag_html}
                        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                          {reply_marker}
                          <span style="font-weight:600;font-size:13px;color:#030303;">{author_text}</span>
                          <span style="font-size:12px;color:#909090;">{date_str}</span>
                          {sentiment}
                        </div>
                        <div style="margin-top:6px;font-size:14px;color:#030303;line-height:1.5;
                                    word-wrap:break-word;">{comment_text}</div>
                        {translation_html}
                        <div style="margin-top:6px;">{likes_html}{replies_html}</div>
                      </div>
                    </div>
                    """)

    st.session_state["hidden_ids"] = hidden_ids

    hidden_count = len(all_comments) - len(visible_comments)
    if hidden_count:
        st.info(f"Hiding **{hidden_count}** comment(s). Report will include **{len(visible_comments)}**.")

    if not visible_comments:
        st.warning("All comments are hidden. Check at least one to generate a report.")
        return

    # --- PDF export ---
    pdf_bytes = build_pdf_report(visible_comments, sq, kws, ai_summary=ai_summary)

    st.download_button(
        label="Download PDF Report",
        data=pdf_bytes,
        file_name="youtube_comment_report.pdf",
        mime="application/pdf",
        type="primary",
    )


if __name__ == "__main__":
    main()

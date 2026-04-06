import re
import json
import html as html_mod
from urllib.parse import urlparse, parse_qs

import anthropic
import streamlit as st
from googleapiclient.discovery import build

from config import MAX_RESULTS_PER_PAGE, SUPPORTED_LANGUAGES, SENTIMENT_COLORS, KEYWORD_PRESETS
from analysis import add_sentiment, cluster_into_themes, get_theme_summary, get_sentiment_counts
from translate import translate_keywords, add_back_translations, back_translate, batch_back_translate, detect_language
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
        + "\n\nWrite a brief summary: one short paragraph (2-3 sentences) capturing "
        "the overall tone and what people are talking about, followed by 3-5 bullet "
        "points highlighting the most notable specific themes or patterns. "
        "Be specific — reference actual topics from the comments, not generic observations. "
        "Use markdown formatting (- for bullets)."
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


import time


def _api_call_with_retry(request, max_retries: int = 3):
    """Execute an API request with exponential backoff retries."""
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except Exception as e:
            if attempt == max_retries:
                raise
            err_str = str(e)
            # Retry on transient errors only
            if any(x in err_str for x in ["500", "503", "429", "timed out", "Connection"]):
                time.sleep(2 ** attempt)
                continue
            raise


def fetch_replies(youtube, parent_id: str, video_id: str) -> list[dict]:
    """Fetch all replies for a top-level comment with retries."""
    replies = []
    request = youtube.comments().list(
        part="snippet",
        parentId=parent_id,
        maxResults=100,
        textFormat="plainText",
    )
    while request:
        try:
            response = _api_call_with_retry(request)
        except Exception:
            break
        for item in response.get("items", []):
            s = item["snippet"]
            replies.append(
                {
                    "author": s["authorDisplayName"],
                    "comment": s["textDisplay"],
                    "likes": s["likeCount"],
                    "replies": 0,
                    "date": s["publishedAt"],
                    "video_id": s.get("videoId", video_id),
                    "is_reply": True,
                    "parent_id": parent_id,
                }
            )
        request = youtube.comments().list_next(request, response)
    return replies


def fetch_comments(
    youtube, video_id: str, max_comments: int | None = None,
    on_progress=None,
) -> list[dict]:
    """Fetch top-level comments for a video with retries.

    Fetches using both 'time' and 'relevance' ordering and deduplicates
    to maximize coverage on large videos where a single pass may miss
    comments due to YouTube API pagination limits.

    Checks st.session_state["_stop_fetch"] between pages to allow
    the user to stop early and keep what was fetched.
    """
    seen_ids: set[str] = set()
    comments: list[dict] = []
    page_size = MAX_RESULTS_PER_PAGE if max_comments is None else min(max_comments, MAX_RESULTS_PER_PAGE)

    for sort_order in ["time", "relevance"]:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=page_size,
            textFormat="plainText",
            order=sort_order,
        )
        consecutive_failures = 0
        stale_pages = 0
        while request:
            # Check stop flag
            if st.session_state.get("_stop_fetch"):
                return comments

            if max_comments is not None and len(comments) >= max_comments:
                break
            try:
                response = _api_call_with_retry(request)
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    break
                continue

            new_on_page = 0
            for item in response.get("items", []):
                thread_id = item["snippet"]["topLevelComment"]["id"]
                if thread_id in seen_ids:
                    continue
                seen_ids.add(thread_id)
                new_on_page += 1

                snippet = item["snippet"]["topLevelComment"]["snippet"]
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

            # Stop this sort order if pages return no new comments
            if new_on_page == 0:
                stale_pages += 1
                if stale_pages >= 3:
                    break
            else:
                stale_pages = 0

            if on_progress:
                on_progress(len(comments))
            request = youtube.commentThreads().list_next(request, response)

    if max_comments is not None:
        return comments[:max_comments]
    return comments


def _build_keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    """Build a compiled regex that matches any keyword as a whole word (case-insensitive)."""
    if not keywords:
        return None
    escaped = [re.escape(kw.strip()) for kw in keywords if kw.strip()]
    if not escaped:
        return None
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


def filter_comments(
    comments: list[dict],
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[dict]:
    """Keep comments where any keyword appears as a whole word (case-insensitive)."""
    if not keywords:
        return list(comments)
    include_pat = _build_keyword_pattern(keywords)
    exclude_pat = _build_keyword_pattern(exclude_keywords or [])
    if not include_pat:
        return list(comments)
    results = []
    for c in comments:
        text = c["comment"]
        if not include_pat.search(text):
            continue
        if exclude_pat and exclude_pat.search(text):
            continue
        results.append(c)
    return results


def main():
    st.set_page_config(page_title="BEAST | YouTube Comment Analysis", layout="wide")
    st.title("YouTube Comment Analysis")
    st.caption("Search · Analyze sentiment · Discover themes · Export PDF")

    api_key = st.secrets.get("YOUTUBE_API_KEY", "")
    if not api_key:
        st.error(
            "Missing `YOUTUBE_API_KEY`. Add it to **Streamlit secrets** "
            "(`.streamlit/secrets.toml` locally or the Secrets panel on Streamlit Cloud)."
        )
        return

    # --- Main inputs: video source ---
    input_mode = st.radio(
        "How do you want to find videos?",
        ["Paste video URLs", "Search YouTube", "Upload previous export"],
        horizontal=True,
    )

    if input_mode == "Upload previous export":
        uploaded = st.file_uploader(
            "Upload a comments JSON export",
            type=["json"],
            help="Load a previously exported comments file to re-analyze without fetching from YouTube.",
        )
        if uploaded is not None:
            upload_id = f"{uploaded.name}_{uploaded.size}"
            if st.session_state.get("_last_upload_id") != upload_id:
                try:
                    data = json.loads(uploaded.read())
                    st.session_state["raw_comments"] = data["comments"]
                    st.session_state["search_query"] = data.get("search_query", "Imported")
                    st.session_state.pop("analyzed_comments", None)
                    st.session_state.pop("hidden_ids", None)
                    st.session_state["_last_upload_id"] = upload_id
                    st.success(f"Loaded **{len(data['comments']):,}** comments.")
                except Exception as e:
                    st.error(f"Failed to load file: {e}")

    elif input_mode == "Paste video URLs":
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

    # (quota estimate moved inline with fetch settings below)

    # --- Recover partial fetch ---
    if "_fetch_in_progress" in st.session_state and st.session_state["_fetch_in_progress"]:
        partial = st.session_state["_fetch_in_progress"]
        st.warning(f"A previous fetch was interrupted with **{len(partial):,}** comments saved.")
        if st.button("Use these comments", key="_use_partial"):
            st.session_state["raw_comments"] = partial
            st.session_state["search_query"] = st.session_state.get("search_query", "Interrupted fetch")
            st.session_state.pop("_fetch_in_progress", None)
            st.session_state.pop("analyzed_comments", None)
            st.session_state.pop("hidden_ids", None)
            st.rerun()
        if st.button("Discard and start over", key="_discard_partial"):
            st.session_state.pop("_fetch_in_progress", None)
            st.rerun()

    # ===================================================================
    # PHASE 1: FETCH — hits the API, stores raw comments in session state
    # ===================================================================
    if input_mode != "Upload previous export":
        # Fetch settings
        fetch_col1, fetch_col2 = st.columns(2)
        with fetch_col1:
            fetch_all = st.checkbox(
                "Fetch all comments",
                value=True,
                help="Fetch every comment on each video. Uncheck to set a limit.",
            )
            if not fetch_all:
                max_scan = st.number_input(
                    "Comments to scan per video", min_value=100, max_value=250_000,
                    value=5000, step=1000,
                )
            else:
                max_scan = None
        with fetch_col2:
            include_replies = st.checkbox(
                "Include replies",
                help="Fetch replies under each top-level comment. Uses 1 additional API call "
                     "per top-level comment that has replies.",
            )

    # Quota estimate (inline, only for fetch modes)
    if input_mode != "Upload previous export":
        if input_mode == "Paste video URLs":
            _est_videos = len(extract_video_ids(url_input)) if url_input.strip() else 1
            _search_cost = 0
        else:
            _est_videos = max_videos
            _search_cost = ((_est_videos + 49) // 50) * 100

        if fetch_all:
            st.caption(
                "Quota: Unknown (fetching all comments). Each page of 50 comments = 1 unit."
            )
        else:
            _pages_per_video = (max_scan + 99) // 100
            _total_est = _search_cost + _est_videos * _pages_per_video
            _pct = min(_total_est / 10_000 * 100, 100)
            st.caption(
                f"Estimated quota: ~{_total_est:,} of 10,000 daily units ({_pct:.0f}%)"
            )

    if input_mode == "Upload previous export":
        pass  # Upload handled above, no fetch needed
    elif st.button("Fetch Comments", type="primary"):
        from googleapiclient.errors import HttpError

        youtube = get_youtube_client(api_key)

        try:
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
        except HttpError as e:
            reason = e.error_details[0]["reason"] if e.error_details else str(e)
            if e.resp.status == 403:
                st.error(
                    f"**YouTube API error (403):** {reason}\n\n"
                    "This usually means your daily quota (10,000 units) is exhausted. "
                    "Quota resets at midnight Pacific Time. You can check usage at "
                    "[Google Cloud Console](https://console.cloud.google.com/apis/dashboard)."
                )
            else:
                st.error(f"**YouTube API error ({e.resp.status}):** {reason}")
            return

        raw_comments: list[dict] = []
        st.session_state["_stop_fetch"] = False
        st.session_state["_fetch_in_progress"] = []
        status = st.status("Fetching comments...", expanded=True)

        try:
            # Pass 1: Fetch top-level comments
            for i, video in enumerate(videos):
                if st.session_state.get("_stop_fetch"):
                    break
                counter = status.empty()
                video_label = video["title"][:50]

                def update_counter(count, _label=video_label, _el=counter, _prev=raw_comments):
                    total = len(_prev) + count
                    _el.markdown(f"**{_label}** — {count:,} top-level comments ({total:,} total)")

                batch = fetch_comments(
                    youtube, video["video_id"], max_scan,
                    on_progress=update_counter,
                )
                for c in batch:
                    c["video_title"] = video["title"]
                raw_comments.extend(batch)
                # Save progress so partial results survive interruption
                st.session_state["_fetch_in_progress"] = list(raw_comments)
                counter.markdown(
                    f"**{video_label}** — {len(batch):,} top-level ✓ "
                    f"({len(raw_comments):,} total)"
                )

            # Pass 2: Fetch replies (separate pass so failures don't break main fetch)
            if include_replies and not st.session_state.get("_stop_fetch"):
                comments_with_replies = [c for c in raw_comments if c.get("replies", 0) > 0]
                if comments_with_replies:
                    reply_counter = status.empty()
                    total_replies = 0
                    failed_replies = 0
                    for j, c in enumerate(comments_with_replies):
                        if st.session_state.get("_stop_fetch"):
                            break
                        try:
                            replies = fetch_replies(youtube, c["comment_id"], c["video_id"])
                            for r in replies:
                                r["video_title"] = c.get("video_title", "")
                            raw_comments.extend(replies)
                            total_replies += len(replies)
                        except Exception:
                            failed_replies += 1
                        if (j + 1) % 10 == 0 or j == len(comments_with_replies) - 1:
                            reply_counter.markdown(
                                f"Replies: {total_replies:,} fetched from "
                                f"{j + 1:,}/{len(comments_with_replies):,} threads"
                                f"{f' ({failed_replies} failed)' if failed_replies else ''}"
                            )

        except HttpError as e:
            reason = e.error_details[0]["reason"] if e.error_details else str(e)
            if raw_comments:
                status.update(
                    label=f"API error after {len(raw_comments):,} comments — saving what was fetched.",
                    state="error", expanded=True,
                )
                status.write(f"**Error:** {reason}")
                if e.resp.status == 403:
                    status.write("Daily quota likely exhausted. Resets at midnight PT.")
            else:
                status.update(label="API error", state="error")
                st.error(f"**YouTube API error ({e.resp.status}):** {reason}")
                return

        was_stopped = st.session_state.get("_stop_fetch", False)
        if was_stopped:
            status.update(
                label=f"Stopped — saved {len(raw_comments):,} comments fetched so far.",
                state="complete", expanded=False,
            )
        else:
            status.update(
                label=f"Fetched {len(raw_comments):,} comments from {len(videos)} video(s).",
                state="complete", expanded=False,
            )
        st.session_state.pop("_fetch_in_progress", None)

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
    _rainbow_bar = (
        '<div style="display:flex;width:100%;height:3px;overflow:hidden;">'
        '<div style="flex:1;background:#00BCE7;"></div>'
        '<div style="flex:1;background:#E64783;"></div>'
        '<div style="flex:1;background:#1CE8B5;"></div>'
        '<div style="flex:1;background:#C94EFF;"></div>'
        '<div style="flex:1;background:#FFD93D;"></div>'
        '<div style="flex:1;background:#FF5E5B;"></div>'
        '<div style="flex:1;background:#CCF913;"></div>'
        '<div style="flex:1;background:#FF9500;"></div>'
        '</div>'
    )
    st.html(_rainbow_bar)
    from datetime import datetime
    _export_ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _video_titles = sorted(set(c.get("video_title", "") for c in raw_comments if c.get("video_title")))
    _title_slug = re.sub(r"[^\w\s-]", "", _video_titles[0] if len(_video_titles) == 1 else "multiple_videos")
    _title_slug = re.sub(r"\s+", "_", _title_slug.strip())[:50]
    _export_filename = f"{_title_slug}_{_export_ts}.json"

    export_data = json.dumps(
        {"search_query": sq, "comments": raw_comments},
        ensure_ascii=False,
    ).encode("utf-8")

    # --- Fetch stats breakdown ---
    total_raw = len(raw_comments)
    top_level = [c for c in raw_comments if not c.get("is_reply")]
    replies_list = [c for c in raw_comments if c.get("is_reply")]

    st.subheader("Fetch Stats")
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("Total Comments", f"{total_raw:,}")
    stat_col2.metric("Top-Level", f"{len(top_level):,}")
    stat_col3.metric("Replies", f"{len(replies_list):,}")

    # Per-video breakdown
    video_titles = sorted(set(c.get("video_title", "") for c in raw_comments))
    if len(video_titles) > 1 or video_titles:
        for vt in video_titles:
            v_comments = [c for c in raw_comments if c.get("video_title") == vt]
            v_top = sum(1 for c in v_comments if not c.get("is_reply"))
            v_replies = sum(1 for c in v_comments if c.get("is_reply"))
            st.caption(
                f"**{vt}** — {len(v_comments):,} total "
                f"({v_top:,} top-level, {v_replies:,} replies)"
            )

    _analysis_done = "analyzed_comments" in st.session_state
    _analyze_expander = st.expander(
        f"**Filter & Analyze** — {total_raw:,} cached comments",
        expanded=not _analysis_done,
    )
    with _analyze_expander:
        col_info, col_dl = st.columns([0.7, 0.3])
        with col_info:
            st.caption(
                f"**{total_raw:,}** cached comments available. "
                "Change filters and re-analyze without re-fetching."
            )
        with col_dl:
            st.download_button(
                label="Export Raw Comments (JSON)",
                data=export_data,
                file_name=_export_filename,
                mime="application/json",
            )

    with _analyze_expander:
        search_all = st.checkbox(
        "Return all comments (skip keyword filter)",
        help="Include every comment without keyword filtering. "
             "Useful when you want to analyze all discussion on specific videos.",
        key="search_all",
    )

    with _analyze_expander:
        if not search_all:
            # Preset selector
            preset_names = ["Custom"] + list(KEYWORD_PRESETS.keys())
            selected_preset = st.selectbox(
                "Keyword preset",
                options=preset_names,
                help="Load a pre-built keyword set or use your own custom keywords.",
                key="keyword_preset",
            )

            if selected_preset != "Custom":
                preset = KEYWORD_PRESETS[selected_preset]
                default_kw = ", ".join(preset["keywords"])
                preset_translations = preset.get("translations", {})
            else:
                default_kw = ""
                preset_translations = {}

            # Update keyword input and clear translation cache when preset changes
            if st.session_state.get("_last_preset") != selected_preset:
                st.session_state["keyword_input"] = default_kw
                st.session_state["_last_preset"] = selected_preset
                st.session_state.pop("_translation_cache_key", None)
                st.session_state.pop("_translated_kw_map", None)

            keyword_input = st.text_input(
                "Filter comments by keywords (comma-separated)",
                placeholder="e.g. great, awesome, helpful",
                key="keyword_input",
            )
            keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

            exclude_input = st.text_input(
                "Exclude comments containing (comma-separated)",
                placeholder="e.g. spam, subscribe, giveaway",
                help="Comments matching any of these words will be excluded.",
                key="exclude_input",
            )
            exclude_keywords = [k.strip() for k in exclude_input.split(",") if k.strip()]
        else:
            keywords = []
            exclude_keywords = []
            preset_translations = {}
            selected_preset = "Custom"

        # --- Multi-Language Search ---
        selected_langs = st.multiselect(
            "Also search in these languages",
            options=list(SUPPORTED_LANGUAGES.keys()),
            help="Keywords will be translated and matched against cached comments. "
                 "Matching comments will include a back-translation to English.",
            key="selected_langs",
        )
        selected_lang_codes = [SUPPORTED_LANGUAGES[n] for n in selected_langs]

    # --- Translated keywords preview + edit ---
    translated_kw_map: dict[str, list[str]] = {}
    if selected_langs and keywords and not search_all:
        # Cache key includes preset name so changing preset resets translations
        cache_key = f"{selected_preset}|{','.join(keywords)}|{','.join(selected_langs)}"
        if st.session_state.get("_translation_cache_key") != cache_key:
            # Clear old per-language text input keys so they pick up new values
            for lang_name in SUPPORTED_LANGUAGES:
                lc = SUPPORTED_LANGUAGES[lang_name]
                st.session_state.pop(f"trans_{lc}", None)

            new_map = {}
            needs_translation = []
            for lang_name in selected_langs:
                lang_code = SUPPORTED_LANGUAGES[lang_name]
                if lang_code in preset_translations and preset_translations[lang_code]:
                    new_map[lang_code] = preset_translations[lang_code]
                else:
                    needs_translation.append((lang_name, lang_code))

            if needs_translation:
                with st.spinner("Translating keywords..."):
                    for lang_name, lang_code in needs_translation:
                        translated = translate_keywords(keywords, lang_code)
                        new_map[lang_code] = translated

            st.session_state["_translated_kw_map"] = new_map
            st.session_state["_translation_cache_key"] = cache_key

        stored_map = st.session_state.get("_translated_kw_map", {})

        with _analyze_expander:
            st.markdown("**Translated keywords** — edit any translation before analyzing:")
            for lang_name in selected_langs:
                lang_code = SUPPORTED_LANGUAGES[lang_name]
                current = stored_map.get(lang_code, [])
                if f"trans_{lang_code}" not in st.session_state:
                    st.session_state[f"trans_{lang_code}"] = ", ".join(current)
                edited = st.text_input(
                    f"{lang_name} ({lang_code})",
                    key=f"trans_{lang_code}",
                )
                translated_kw_map[lang_code] = [k.strip() for k in edited.split(",") if k.strip()]

    with _analyze_expander:
        _do_analyze = st.button("Apply Filters & Analyze", type="primary")

    if _do_analyze:
        if not search_all and not keywords:
            st.warning("Enter at least one keyword or check 'Return all comments'.")
            return

        status = st.status("Analyzing...", expanded=True)

        # Step 1: Filter
        status.update(label="Step 1/3 — Filtering comments...")
        if search_all:
            matched = [dict(c, matched_language="all") for c in raw_comments]
        else:
            # Build compiled regex patterns for each keyword set
            all_kw_sets: list[tuple[re.Pattern, str | None]] = []
            include_en = _build_keyword_pattern(keywords)
            if include_en:
                all_kw_sets.append((include_en, None))
            for lang_code, kws in translated_kw_map.items():
                pat = _build_keyword_pattern(kws)
                if pat:
                    all_kw_sets.append((pat, lang_code))

            exclude_pat = _build_keyword_pattern(exclude_keywords)

            seen: set[int] = set()
            matched: list[dict] = []
            for idx, c in enumerate(raw_comments):
                for include_pat, plan_lang in all_kw_sets:
                    text = c["comment"]
                    if not include_pat.search(text):
                        continue
                    if exclude_pat and exclude_pat.search(text):
                        continue
                    if idx in seen:
                        continue
                    seen.add(idx)
                    copy = dict(c)
                    # Detect actual language instead of using keyword set
                    detected = detect_language(c["comment"])
                    copy["matched_language"] = detected
                    if detected != "en":
                        copy["_needs_bt"] = detected
                    matched.append(copy)
                    break

        if not matched:
            status.update(label="No comments matched.", state="error")
            st.warning("No comments matched your filters.")
            return

        status.write(f"Found **{len(matched):,}** matches.")

        # Clean up internal flags, preserve language info for later translation
        for m in matched:
            bt_lang = m.pop("_needs_bt", None)
            if bt_lang and not m.get("original_language"):
                m["original_language"] = bt_lang

        # Step 2: Sentiment
        status.update(label=f"Step 2/3 — Sentiment analysis on {len(matched):,} comments...")
        add_sentiment(matched)
        sentiment_counts = get_sentiment_counts(matched)
        status.write(
            f"+{sentiment_counts['Positive']} positive, "
            f"~{sentiment_counts['Neutral']} neutral, "
            f"-{sentiment_counts['Negative']} negative"
        )

        # Step 3: Theme clustering (for AI summary)
        status.update(label="Step 3/3 — Discovering themes...")
        cluster_into_themes(matched)

        for idx, c in enumerate(matched):
            c["_id"] = idx

        status.update(label="Analysis complete.", state="complete", expanded=False)

        analyzed = matched

        if not analyzed:
            st.warning("No comments matched your filters.")
            return

        st.session_state["analyzed_comments"] = analyzed
        st.session_state["hidden_ids"] = set()
        st.session_state["keywords"] = keywords
        st.session_state.pop("ai_summary", None)
        # Reset filter/sort state for fresh results
        for k in ["fs_videos", "fs_sentiment", "fs_language", "fs_text_search",
                   "fs_text_exclude", "fs_min_likes", "fs_sort", "fs_reply_type"]:
            st.session_state.pop(k, None)
        st.success(f"**{len(analyzed):,}** comments match your filters.")

    # --- Nothing analyzed yet ---
    if "analyzed_comments" not in st.session_state:
        return

    all_comments = st.session_state["analyzed_comments"]
    hidden_ids = st.session_state.get("hidden_ids", set())
    kws = st.session_state.get("keywords", [])

    # --- Bulk back-translate ---
    non_english = [
        c for c in all_comments
        if c.get("matched_language", "en") != "en"
        and c.get("matched_language") != "all"
        and (not c.get("back_translation") or c["back_translation"] == c["comment"])
    ]
    if non_english:
        st.divider()
        col_bt_info, col_bt_btn = st.columns([0.7, 0.3])
        with col_bt_info:
            st.markdown(
                f"**{len(non_english):,}** non-English comments without translations."
            )
        with col_bt_btn:
            if st.button("Translate All", key="bulk_translate"):
                texts = [c["comment"] for c in non_english]
                with st.spinner(f"Translating {len(texts):,} comments in batch..."):
                    translations = batch_back_translate(texts)
                for c, translation in zip(non_english, translations):
                    c["back_translation"] = translation
                    c["original_language"] = c.get("matched_language", detect_language(c["comment"]))
                st.success(f"Translated **{len(non_english):,}** comments.")
                st.rerun()

    # --- Preview ---
    st.divider()
    st.subheader("Report Preview")
    st.caption("Un-check any comment to exclude it from the report and PDF.")

    # --- Filters & Sort ---
    # Initialize filter defaults in session state on first analysis
    all_video_titles = sorted(set(c.get("video_title", "") for c in all_comments))
    # Build language label lookup: code -> display name
    _lang_code_to_name = {v: k for k, v in SUPPORTED_LANGUAGES.items()}
    _lang_code_to_name["en"] = "English"
    _lang_code_to_name["all"] = "All (unfiltered)"
    all_languages = sorted(set(c.get("matched_language", "en") for c in all_comments))
    all_language_labels = [_lang_code_to_name.get(lc, lc) for lc in all_languages]

    if "fs_videos" not in st.session_state:
        st.session_state["fs_videos"] = all_video_titles
    if "fs_sentiment" not in st.session_state:
        st.session_state["fs_sentiment"] = ["Positive", "Neutral", "Negative"]
    if "fs_language" not in st.session_state:
        st.session_state["fs_language"] = all_language_labels

    with st.expander("**Filter & Sort**", expanded=False):
        filter_col1, filter_col2 = st.columns(2)

        # Video filter
        if len(all_video_titles) > 1:
            with filter_col1:
                selected_videos = st.multiselect(
                    "Filter by video",
                    options=all_video_titles,
                    key="fs_videos",
                )
        else:
            selected_videos = all_video_titles

        # Sentiment filter
        with filter_col2:
            selected_sentiments = st.multiselect(
                "Filter by sentiment",
                options=["Positive", "Neutral", "Negative"],
                key="fs_sentiment",
            )

        # Row 2: Language filter (if multiple) + empty or language takes full row
        if len(all_languages) > 1:
            filter_row2_l, filter_row2_r = st.columns(2)
            with filter_row2_l:
                selected_language_labels = st.multiselect(
                    "Filter by matched language",
                    options=all_language_labels,
                    key="fs_language",
                )
        else:
            selected_language_labels = all_language_labels

        # Row 3: Text search + Does not contain
        filter_row3_l, filter_row3_r = st.columns(2)
        with filter_row3_l:
            text_search = st.text_input(
                "Search within comments",
                placeholder="e.g. auto-generated",
                key="fs_text_search",
            )
        with filter_row3_r:
            text_exclude = st.text_input(
                "Does not contain",
                placeholder="e.g. spam, bot, fake",
                key="fs_text_exclude",
                help="Exclude comments containing any of these words (comma-separated).",
            )

        # Row 4: Min likes + Sort
        filter_row4_l, filter_row4_r = st.columns(2)
        with filter_row4_l:
            min_likes = st.number_input("Min likes", min_value=0, value=0, step=1, key="fs_min_likes")
        with filter_row4_r:
            sort_options = {
                "Date (newest)": ("date", True),
                "Date (oldest)": ("date", False),
                "Likes (most)": ("likes", True),
                "Likes (fewest)": ("likes", False),
                "Author (A-Z)": ("author", False),
            }
            sort_choice = st.selectbox("Sort by", options=list(sort_options.keys()), key="fs_sort")

        # Row 5: Comment type
        show_replies = st.radio(
            "Comment type",
            ["All", "Top-level only", "Replies only"],
            horizontal=True,
            key="fs_reply_type",
        )

    # Apply filters
    display_comments = all_comments

    if len(all_video_titles) > 1:
        display_comments = [c for c in display_comments if c.get("video_title") in selected_videos]

    display_comments = [c for c in display_comments if c["sentiment_label"] in selected_sentiments]

    # Language filter
    if len(all_languages) > 1:
        _name_to_code = {v: k for k, v in _lang_code_to_name.items()}
        selected_lang_filter_codes = {_name_to_code.get(lbl, lbl) for lbl in selected_language_labels}
        display_comments = [c for c in display_comments if c.get("matched_language", "en") in selected_lang_filter_codes]

    if text_search:
        text_search_lower = text_search.lower()
        display_comments = [c for c in display_comments if text_search_lower in c["comment"].lower()]

    if text_exclude:
        exclude_words = [w.strip().lower() for w in text_exclude.split(",") if w.strip()]
        display_comments = [
            c for c in display_comments
            if not any(w in c["comment"].lower() for w in exclude_words)
        ]

    if min_likes > 0:
        display_comments = [c for c in display_comments if c.get("likes", 0) >= min_likes]

    if show_replies == "Top-level only":
        display_comments = [c for c in display_comments if not c.get("is_reply")]
    elif show_replies == "Replies only":
        display_comments = [c for c in display_comments if c.get("is_reply")]

    # Apply sort
    sort_key, sort_reverse = sort_options[sort_choice]
    display_comments = sorted(display_comments, key=lambda c: c.get(sort_key, ""), reverse=sort_reverse)

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
                text_color = "#1a1a1a" if label == "Positive" else "#fff"
                _bar_html += (
                    f'<div style="flex:{pct};background:{color};height:32px;'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'color:{text_color};font-size:12px;font-weight:600;'
                    f'min-width:{40 if pct > 3 else 0}px;">'
                    f'{emoji} {count} ({pct:.0f}%)</div>'
                )
        st.html(
            f'<div style="display:flex;border-radius:12px;overflow:hidden;'
            f'margin:8px 0 16px 0;">{_bar_html}</div>'
        )

    # Language breakdown
    _lang_code_to_name = {v: k for k, v in SUPPORTED_LANGUAGES.items()}
    _lang_code_to_name["en"] = "English"
    _lang_code_to_name["all"] = "All (unfiltered)"

    lang_counts: dict[str, int] = {}
    for c in display_comments:
        lc = c.get("matched_language", "en")
        name = _lang_code_to_name.get(lc, lc)
        lang_counts[name] = lang_counts.get(name, 0) + 1

    if len(lang_counts) > 1 or (len(lang_counts) == 1 and "English" not in lang_counts):
        lang_parts = [f"{name}: {count:,}" for name, count in
                      sorted(lang_counts.items(), key=lambda x: -x[1])]
        st.caption(f"**Languages detected:** {' · '.join(lang_parts)}")

    # Compute visible comments (excluding hidden) for AI summary + export
    visible_comments = [c for c in display_comments if c["_id"] not in hidden_ids]

    # --- AI Summary + Export (right under sentiment bar) ---
    if visible_comments:
        ai_summary = st.session_state.get("ai_summary", "")

        if st.button("Generate AI Summary", type="secondary", key="gen_ai_summary"):
            with st.spinner("Generating AI theme summary from selected comments..."):
                ai_summary = generate_ai_summary(visible_comments, sq)
                st.session_state["ai_summary"] = ai_summary
                st.session_state["_ai_summary_ids"] = {c["_id"] for c in visible_comments}

        # Check if summary is stale (comments changed since generation)
        summary_stale = False
        if ai_summary:
            saved_ids = st.session_state.get("_ai_summary_ids", set())
            current_ids = {c["_id"] for c in visible_comments}
            if saved_ids != current_ids:
                summary_stale = True

            with st.expander("**AI Theme Summary**", expanded=True):
                st.markdown(ai_summary)
                if summary_stale:
                    st.warning("Comments have changed since this summary was generated. "
                               "Click **Generate AI Summary** above to refresh.")

        _preset = st.session_state.get("keyword_preset", "Custom")
        pdf_bytes = build_pdf_report(
            visible_comments, sq, kws,
            ai_summary=ai_summary,
            preset_name=_preset,
        )
        if summary_stale:
            st.caption("AI summary may be outdated. Regenerate before exporting for accurate results.")
        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=f"{_title_slug}_{_export_ts}_report.pdf",
            mime="application/pdf",
            type="primary",
        )

    hidden_count = len(display_comments) - len(visible_comments)
    if hidden_count:
        st.info(f"Hiding **{hidden_count}** comment(s). Report will include **{len(visible_comments)}**.")

    # Group comments by sentiment (preserving sort within each group)
    sentiment_groups = {}
    for label in ["Positive", "Neutral", "Negative"]:
        group = [c for c in display_comments if c["sentiment_label"] == label]
        if group:
            sentiment_groups[label] = group

    st.caption(f"Showing **{total:,}** comments")

    # Render sentiment-grouped comment cards with checkboxes
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

                    # On-demand translate button for non-English comments
                    lang_code = c.get("matched_language", "en")
                    has_translation = c.get("back_translation") and c["back_translation"] != c["comment"]
                    if lang_code != "en" and not has_translation:
                        if st.button("🌐 Translate", key=f"bt_{cid}"):
                            c["back_translation"] = back_translate(c["comment"])
                            st.rerun()

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
                            'font-size:10px;font-weight:500;color:#00BCE7;background:#e0f7fc;'
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
                            f'border-left:3px solid #00BCE7;border-radius:4px;font-size:13px;'
                            f'color:#4a5568;font-style:italic;">🌐 English: {bt}</div>'
                        )

                    comment_text = html_mod.escape(c["comment"])
                    author_text = html_mod.escape(c["author"])

                    tags_html = ""
                    if len(all_video_titles) > 1 and c.get("video_title"):
                        vt = html_mod.escape(c["video_title"])
                        tags_html += (
                            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                            f'font-size:11px;font-weight:500;color:#4a5568;background:#f3f4f6;'
                            f'margin-right:6px;">🎬 {vt}</span>'
                        )

                    lang_code = c.get("matched_language", "en")
                    if lang_code not in ("en", "all"):
                        lang_label = _lang_code_to_name.get(lang_code, lang_code)
                        tags_html += (
                            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                            f'font-size:11px;font-weight:500;color:#00BCE7;background:#e0f7fc;">'
                            f'🌐 {lang_label}</span>'
                        )

                    if tags_html:
                        tags_html = f'<div style="margin-bottom:6px;">{tags_html}</div>'

                    st.html(f"""
                    <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f0f0f0;opacity:{opacity};">
                      <div style="flex-shrink:0;width:40px;height:40px;border-radius:50%;
                                  background:{avatar_bg};display:flex;align-items:center;
                                  justify-content:center;color:#fff;font-weight:700;font-size:14px;">
                        {initials}
                      </div>
                      <div style="flex:1;min-width:0;">
                        {tags_html}
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


if __name__ == "__main__":
    main()

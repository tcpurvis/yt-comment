import re
import json
import html as html_mod
from urllib.parse import urlparse, parse_qs

import anthropic
import streamlit as st
from googleapiclient.discovery import build

from config import MAX_RESULTS_PER_PAGE, SUPPORTED_LANGUAGES, SENTIMENT_COLORS, KEYWORD_PRESETS, LANGUAGE_NAMES
from analysis import add_sentiment, cluster_into_themes, get_theme_summary, get_sentiment_counts
from translate import translate_keywords, add_back_translations, back_translate, batch_back_translate, detect_language
from report import (
    build_html_report, build_pdf_report, build_interactive_html_report,
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
        "Use markdown formatting (- for bullets). "
        "Every bullet MUST start with a sentiment tag in square brackets indicating "
        "the dominant sentiment of that theme: [POS] if viewers are mostly positive, "
        "[NEG] if mostly negative, [NEU] if mixed or neutral. Example:\n"
        "- [POS] Viewers love the professional dubbing quality.\n"
        "- [NEG] Many complain about missing subtitles for their language.\n"
        "- [NEU] Opinions are split on whether the new voice actor fits the character."
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


_SENTIMENT_TAG_STYLE = {
    "POS": ("Positive", "#1CE8B5", "#033d33"),
    "NEG": ("Negative", "#FF5E5B", "#5a1111"),
    "NEU": ("Neutral",  "#C94EFF", "#2e0b3d"),
}


def _decorate_ai_summary(text: str) -> str:
    """Replace [POS]/[NEG]/[NEU] sentiment tags in an AI summary with
    colored HTML badges so the user can see each bullet's polarity."""
    if not text:
        return text

    def _repl(match: re.Match) -> str:
        tag = match.group(1).upper()
        label, bg, fg = _SENTIMENT_TAG_STYLE[tag]
        return (
            f'<span style="display:inline-block;padding:1px 8px;'
            f'border-radius:10px;background:{bg};color:{fg};'
            f'font-size:10px;font-weight:700;letter-spacing:0.4px;'
            f'margin-right:6px;vertical-align:middle;">{label.upper()}</span>'
        )

    return re.sub(r"\[(POS|NEG|NEU)\]", _repl, text)


def _rename_themes_with_claude(comments: list[dict]) -> None:
    """Replace TF-IDF theme names (like 'Subtitle / Captions / English') with
    2-4 word semantic titles (like 'Missing language subtitles'). Modifies
    comments in place. Silent no-op if the API key is absent or the call fails."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key or not comments:
        return

    # Group by current theme label; skip if there's only one cluster.
    buckets: dict[str, list[dict]] = {}
    for c in comments:
        buckets.setdefault(c.get("theme", "General"), []).append(c)
    if len(buckets) < 2:
        return

    # Build a numbered list of clusters with up to 5 representative samples each.
    names = list(buckets.keys())
    blocks = []
    for i, name in enumerate(names, start=1):
        samples = buckets[name][:5]
        sample_lines = "\n".join(
            f"  - {(c.get('back_translation') or c['comment'])[:180]}"
            for c in samples
        )
        blocks.append(f"Cluster {i} (currently \"{name}\", {len(buckets[name])} comments):\n{sample_lines}")
    prompt = (
        "For each cluster of YouTube comments below, write a concise 2-4 word "
        "title capturing what the comments are ABOUT (the theme), not the sentiment. "
        "Be specific — refer to the subject matter, not generic words like 'Comments' "
        "or 'Discussion'. Return ONLY the titles, one per line, in the format:\n"
        "1. <title>\n2. <title>\n...\n\n"
        + "\n\n".join(blocks)
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = response.content[0].text.strip()
    except Exception:
        return

    new_names: dict[str, str] = {}
    for line in reply.split("\n"):
        m = re.match(r"\s*(\d+)[\.\)]\s*(.+)", line.strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1
        title = m.group(2).strip().strip("\"").strip()
        if 0 <= idx < len(names) and title:
            new_names[names[idx]] = title

    for c in comments:
        old = c.get("theme", "General")
        if old in new_names:
            c["theme"] = new_names[old]


def generate_one_line_summary(comments: list[dict], section_name: str) -> str:
    """Generate a one-sentence sentiment summary for a section using Claude Haiku."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key or not comments:
        return ""

    counts = get_sentiment_counts(comments)
    total = len(comments)
    samples = [c.get("back_translation") or c["comment"] for c in comments[:30]]
    sample_block = "\n".join(f"- {s[:180]}" for s in samples)

    prompt = (
        f"Summarize overall sentiment across {total} YouTube comments about "
        f"\"{section_name}\" in ONE sentence (max 25 words). "
        f"Counts: +{counts['Positive']} positive, ~{counts['Neutral']} neutral, "
        f"-{counts['Negative']} negative.\n\n"
        f"Sample comments:\n{sample_block}\n\n"
        "Start your reply with a sentiment tag in square brackets: "
        "[POS] if viewers are mostly positive, [NEG] if mostly negative, "
        "[NEU] if mixed or neutral. Example: "
        "\"[POS] Viewers overwhelmingly praise the dubbing quality.\" "
        "Reply with just the one tagged sentence — no quotes, no preamble."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


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


# English names of languages → ISO code. Used to tag English comments that
# mention a language by name (e.g. "the Japanese dub") so the language pill
# still surfaces them even though no translation is needed.
_ENGLISH_LANGUAGE_MENTIONS = {
    "japanese": "ja", "spanish": "es", "french": "fr", "german": "de",
    "portuguese": "pt", "italian": "it", "korean": "ko",
    "chinese": "zh-CN", "mandarin": "zh-CN", "cantonese": "zh-CN",
    "hindi": "hi", "arabic": "ar", "russian": "ru", "turkish": "tr",
    "thai": "th", "vietnamese": "vi", "indonesian": "id",
    "polish": "pl", "dutch": "nl", "swedish": "sv", "danish": "da",
    "norwegian": "no", "finnish": "fi", "czech": "cs", "slovak": "sk",
    "hungarian": "hu", "romanian": "ro", "bulgarian": "bg", "croatian": "hr",
    "serbian": "sr", "ukrainian": "uk", "greek": "el", "hebrew": "he",
    "persian": "fa", "farsi": "fa", "malay": "ms", "filipino": "tl",
    "tagalog": "tl", "bengali": "bn", "tamil": "ta", "telugu": "te",
    "malayalam": "ml", "kannada": "kn", "marathi": "mr", "gujarati": "gu",
    "urdu": "ur", "swahili": "sw", "afrikaans": "af", "catalan": "ca",
    "nepali": "ne", "sinhala": "si", "khmer": "km", "lao": "lo",
    "burmese": "my", "mongolian": "mn", "kazakh": "kk", "uzbek": "uz",
    "azerbaijani": "az", "armenian": "hy", "georgian": "ka", "albanian": "sq",
    "macedonian": "mk", "slovenian": "sl", "estonian": "et", "latvian": "lv",
    "lithuanian": "lt", "icelandic": "is", "basque": "eu", "galician": "gl",
}

_ENGLISH_LANGUAGE_MENTION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _ENGLISH_LANGUAGE_MENTIONS) + r")\b",
    re.IGNORECASE,
)


def _find_english_language_mention(text: str) -> str | None:
    """Return the ISO code of the first language mentioned by name in an
    English comment, or None. Uses whole-word, case-insensitive matching."""
    m = _ENGLISH_LANGUAGE_MENTION_PATTERN.search(text or "")
    if m:
        return _ENGLISH_LANGUAGE_MENTIONS[m.group(0).lower()]
    return None


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

    # Sticky header with title + save button
    st.html("""
    <style>
    div[data-testid="stMainBlockContainer"] > div:first-child {
        position: sticky;
        top: 0;
        z-index: 999;
        background: white;
        padding: 0.5rem 0;
    }
    /* Right-align save button column */
    div[data-testid="stMainBlockContainer"] > div:first-child
    div[data-testid="stHorizontalBlock"] > div:last-child {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
    }
    /* Compact buttons */
    .stButton > button {
        padding: 0.2rem 0.5rem !important;
        font-size: 13px !important;
        min-height: 0 !important;
    }
    /* Pink Reanalyze button */
    .st-key-sidebar_reanalyze_top button,
    .st-key-sidebar_reanalyze_bulk button {
        background-color: #E64783 !important;
        border-color: #E64783 !important;
        color: white !important;
    }
    .st-key-sidebar_reanalyze_top button:hover,
    .st-key-sidebar_reanalyze_bulk button:hover {
        background-color: #d13a73 !important;
        border-color: #d13a73 !important;
    }
    </style>
    """)
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

    _has_data = "raw_comments" in st.session_state

    if not _has_data:
        # PAGE 1 — Setup
        st.title("YouTube Comment Analysis")
        st.caption("Search · Analyze sentiment · Discover themes · Export PDF")
        st.html(_rainbow_bar)
    else:
        # PAGE 2 — Analysis (page title = video title)
        _raw_top = st.session_state["raw_comments"]
        _top_titles = sorted(set(c.get("video_title", "") for c in _raw_top if c.get("video_title")))
        if len(_top_titles) == 1:
            _page_title = _top_titles[0]
        elif _top_titles:
            _page_title = ", ".join(_top_titles[:3]) + (f" (+{len(_top_titles)-3} more)" if len(_top_titles) > 3 else "")
        else:
            _page_title = st.session_state.get("search_query", "YouTube Comments")

        # Pick a thumbnail — first stored video_id, otherwise the first comment's video_id
        _thumb_vid = None
        _vids_top = st.session_state.get("video_ids") or []
        if _vids_top:
            _thumb_vid = _vids_top[0]
        else:
            for _c in _raw_top:
                if _c.get("video_id"):
                    _thumb_vid = _c["video_id"]
                    break

        if _thumb_vid:
            _thumb_url = f"https://img.youtube.com/vi/{_thumb_vid}/mqdefault.jpg"
            st.html(
                f'<div style="display:flex;align-items:center;gap:20px;margin:0 0 8px 0;">'
                f'<img src="{_thumb_url}" alt="" '
                f'style="height:90px;width:auto;border-radius:6px;object-fit:cover;flex-shrink:0;" />'
                f'<h1 style="margin:0;font-size:2.25rem;font-weight:700;line-height:1.2;">'
                f'{html_mod.escape(_page_title)}</h1>'
                f'</div>'
            )
        else:
            st.title(_page_title)
        st.html(_rainbow_bar)

    # Save project button in sidebar (only when data exists)
    if "raw_comments" in st.session_state:
        # Reserve slots at the top of the sidebar for Download PDF, Share link,
        # and Reanalyze. They're filled later in the run once the reports have
        # been built — otherwise on the first page-2 render those buttons would
        # be missing until the user clicks anything to trigger a rerun.
        _pdf_btn_slot = st.sidebar.empty()
        _html_btn_slot = st.sidebar.empty()
        _reanalyze_btn_slot = st.sidebar.empty()
        st.sidebar.divider()

        st.sidebar.header("Save Project")
        st.sidebar.caption("Save full session to resume later")
        _raw_h = st.session_state["raw_comments"]
        _sq_h = st.session_state.get("search_query", "export")
        _vtitles_h = sorted(set(c.get("video_title", "") for c in _raw_h if c.get("video_title")))
        _tslug_h = re.sub(r"[^\w\s-]", "", _vtitles_h[0] if len(_vtitles_h) == 1 else "multiple_videos")
        _tslug_h = re.sub(r"\s+", "_", _tslug_h.strip())[:50]
        from datetime import datetime as _dt_h
        _exp_ts_h = _dt_h.now().strftime("%Y-%m-%d_%H%M%S")

        # Collect video IDs (from current session or derived from comments) so the
        # loaded project can trigger an Update fetch without re-pasting URLs.
        _vids_h = st.session_state.get("video_ids") or sorted(
            {c["video_id"] for c in _raw_h if c.get("video_id")}
        )
        _payload_h: dict = {
            "search_query": _sq_h,
            "comments": _raw_h,
            "video_ids": list(_vids_h),
        }
        if "analyzed_comments" in st.session_state:
            _payload_h["analyzed_comments"] = st.session_state["analyzed_comments"]
            _payload_h["hidden_ids"] = list(st.session_state.get("hidden_ids", set()))
            _payload_h["keywords"] = st.session_state.get("keywords", [])
            _payload_h["preset"] = st.session_state.get("keyword_preset", "Custom")
            _payload_h["ai_summary"] = st.session_state.get("ai_summary", "")
        if st.session_state.get("multi_analyses"):
            _payload_h["multi_analyses"] = st.session_state["multi_analyses"]
        # Custom search state
        if st.session_state.get("custom_search_results"):
            _payload_h["custom_search_results"] = st.session_state["custom_search_results"]
            _payload_h["custom_search_keywords"] = st.session_state.get("custom_search_keywords", [])
            _payload_h["custom_search_exclude"] = st.session_state.get("custom_search_exclude", [])
        # Per-tab AI summaries
        _tab_summaries = {}
        for _k in list(st.session_state.keys()):
            if _k.startswith("ai_summary_") and _k not in ("ai_summary_edit",):
                _tab_summaries[_k] = st.session_state[_k]
        if _tab_summaries:
            _payload_h["tab_summaries"] = _tab_summaries
        # Per-tab one-line summaries
        _one_liners = {}
        for _k in list(st.session_state.keys()):
            if _k.startswith("one_liner_") and not _k.endswith(("_input", "_regen")):
                _one_liners[_k] = st.session_state[_k]
        if _one_liners:
            _payload_h["one_liners"] = _one_liners

        _data_h = json.dumps(_payload_h, ensure_ascii=False).encode("utf-8")
        st.sidebar.download_button(
            label="Save Project",
            data=_data_h,
            file_name=f"{_tslug_h}_{_exp_ts_h}.json",
            mime="application/json",
            key="save_project_sidebar",
        )

        # Update — re-fetch newer comments for the videos in this session
        if st.session_state.get("video_ids"):
            if st.sidebar.button("Update", key="sidebar_update", help="Fetch comments posted since the last pull for this session's videos"):
                st.session_state["_needs_session_update"] = True
                st.rerun()

        # Start Over (confirmation before clearing)
        if st.sidebar.button("Start Over", key="sidebar_start_over"):
            st.session_state["_confirm_start_over"] = True

        if st.session_state.get("_confirm_start_over"):
            st.sidebar.warning("Starting over will clear all data. Save your project first if you want to keep it.")
            _so1, _so2 = st.sidebar.columns(2)
            with _so1:
                if st.button("Yes, clear", key="confirm_start_over_yes", type="primary"):
                    _keys_to_keep = {"_last_upload_id"}
                    for _k in list(st.session_state.keys()):
                        if _k not in _keys_to_keep:
                            del st.session_state[_k]
                    st.rerun()
            with _so2:
                if st.button("Cancel", key="confirm_start_over_no"):
                    st.session_state.pop("_confirm_start_over", None)
                    st.rerun()

        st.sidebar.divider()

    api_key = st.secrets.get("YOUTUBE_API_KEY", "")
    if not api_key:
        st.error(
            "Missing `YOUTUBE_API_KEY`. Add it to **Streamlit secrets** "
            "(`.streamlit/secrets.toml` locally or the Secrets panel on Streamlit Cloud)."
        )
        return

    if not _has_data:
        # --- Main inputs: video source ---
        input_mode = st.radio(
            "How do you want to find videos?",
            ["Paste video URLs", "Upload previous export"],
            horizontal=True,
            help="Tip: after uploading, use the sidebar Update button to fetch newer comments.",
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
                        st.session_state["_last_upload_id"] = upload_id
                        # Preserve video IDs so the Update button can re-fetch without re-pasting URLs
                        _loaded_vids = data.get("video_ids") or sorted(
                            {c["video_id"] for c in data["comments"] if c.get("video_id")}
                        )
                        st.session_state["video_ids"] = list(_loaded_vids)

                        # Restore analysis state if saved in the export
                        st.session_state["hidden_ids"] = set(data.get("hidden_ids", []))
                        if "analyzed_comments" in data:
                            st.session_state["analyzed_comments"] = data["analyzed_comments"]
                            st.session_state["keywords"] = data.get("keywords", [])
                            if data.get("preset"):
                                st.session_state["keyword_preset"] = data["preset"]
                            if data.get("ai_summary"):
                                st.session_state["ai_summary"] = data["ai_summary"]
                        else:
                            st.session_state.pop("analyzed_comments", None)

                        # Restore multi-analysis tabs (Subtitles & Dubs)
                        if "multi_analyses" in data and data["multi_analyses"]:
                            st.session_state["multi_analyses"] = data["multi_analyses"]
                        else:
                            # Old-format export — auto-run analysis so tabs render
                            st.session_state["multi_analyses"] = None
                            st.session_state["_needs_auto_analysis"] = True

                        # Restore custom search results
                        if "custom_search_results" in data:
                            st.session_state["custom_search_results"] = data["custom_search_results"]
                            st.session_state["custom_search_keywords"] = data.get("custom_search_keywords", [])
                            st.session_state["custom_search_exclude"] = data.get("custom_search_exclude", [])

                        # Restore per-tab AI summaries
                        for _k, _v in data.get("tab_summaries", {}).items():
                            st.session_state[_k] = _v
                        # Restore per-tab one-line summaries
                        for _k, _v in data.get("one_liners", {}).items():
                            st.session_state[_k] = _v

                        _has_multi = data.get("multi_analyses") is not None and len(data.get("multi_analyses", [])) > 0
                        _has_custom = bool(data.get("custom_search_results"))
                        _parts = []
                        if _has_multi:
                            _match_count = sum(len(m['comments']) for m in data['multi_analyses'])
                            _parts.append(f"{_match_count:,} keyword matches")
                        if _has_custom:
                            _parts.append(f"{len(data['custom_search_results']):,} custom search results")
                        _detail = f" · {', '.join(_parts)}" if _parts else ""
                        st.success(f"Loaded **{len(data['comments']):,}** raw comments{_detail}.")
                        # Trigger auto-translation and backfill of any summaries /
                        # one-liners that older exports didn't save.
                        st.session_state["_needs_auto_translate"] = True
                        st.session_state["_needs_summary_backfill"] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to load file: {e}")

            # (Reprocess button moved after function definitions below)

        elif input_mode == "Paste video URLs":
            url_input = st.text_area(
                "YouTube video URLs (one per line)",
                placeholder="https://www.youtube.com/watch?v=dQw4w9WgXcQ\nhttps://youtu.be/abc123XYZab",
                height=120,
            )

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
        if input_mode == "Paste video URLs":
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
                pass  # fetch settings column

            _est_videos = len(extract_video_ids(url_input)) if url_input.strip() else 1
            if fetch_all:
                st.caption(
                    "Quota: Unknown (fetching all comments). Each page of 50 comments = 1 unit."
                )
            else:
                _pages_per_video = (max_scan + 99) // 100
                _total_est = _est_videos * _pages_per_video
                _pct = min(_total_est / 10_000 * 100, 100)
                st.caption(
                    f"Estimated quota: ~{_total_est:,} of 10,000 daily units ({_pct:.0f}%)"
                )

        if input_mode == "Paste video URLs" and st.button("Fetch Comments", type="primary"):
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
            except Exception as e:
                if raw_comments:
                    status.update(
                        label=f"Error after {len(raw_comments):,} comments — saving what was fetched.",
                        state="error", expanded=True,
                    )
                    status.write(f"**Error:** {e}")
                else:
                    status.update(label="Error", state="error")
                    st.error(f"**Error:** {e}")
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
            st.session_state["video_ids"] = [v["video_id"] for v in videos]
            st.session_state.pop("analyzed_comments", None)
            st.session_state.pop("hidden_ids", None)

            st.success(f"Fetched **{len(raw_comments):,}** comments from **{len(videos)}** video(s).")
            st.session_state["_needs_auto_analysis"] = True
            # Rerun so the page 1 setup UI (rendered earlier this run) is replaced
            # by the page 2 analysis view on the next pass.
            st.rerun()

    # --- Nothing fetched yet ---
    if "raw_comments" not in st.session_state:
        return

    raw_comments = st.session_state["raw_comments"]
    sq = st.session_state["search_query"]

    from datetime import datetime
    _export_ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _video_titles = sorted(set(c.get("video_title", "") for c in raw_comments if c.get("video_title")))
    _title_slug = re.sub(r"[^\w\s-]", "", _video_titles[0] if len(_video_titles) == 1 else "multiple_videos")
    _title_slug = re.sub(r"\s+", "_", _title_slug.strip())[:50]

    # --- Fetch stats in sidebar ---
    total_raw = len(raw_comments)
    st.sidebar.header("Fetch Stats")
    _multi_a = st.session_state.get("multi_analyses")
    _match_total = sum(len(m["comments"]) for m in _multi_a) if _multi_a else 0
    _fs1, _fs2 = st.sidebar.columns(2)
    _fs1.metric("Total Comments", f"{total_raw:,}")
    _fs2.metric("Keyword Matches", f"{_match_total:,}")
    st.sidebar.divider()

    # Video titles shown above tabs — store for later
    _video_titles_display = sorted(set(c.get("video_title", "") for c in raw_comments if c.get("video_title")))

    def _run_single_analysis(raw, kw_list, excl_list, trans_map, status_obj, label=""):
        """Run filter + sentiment + clustering on raw comments. Returns list or empty."""
        prefix = f"[{label}] " if label else ""

        # Filter
        status_obj.write(f"{prefix}Filtering...")
        all_kw_sets_a: list[tuple[re.Pattern, str | None]] = []
        include_en_a = _build_keyword_pattern(kw_list)
        if include_en_a:
            all_kw_sets_a.append((include_en_a, None))
        for lc, kws in trans_map.items():
            pat = _build_keyword_pattern(kws)
            if pat:
                all_kw_sets_a.append((pat, lc))
        exclude_pat_a = _build_keyword_pattern(excl_list)

        seen_a: set[int] = set()
        matched_a: list[dict] = []
        for idx, c in enumerate(raw):
            for inc_pat, plan_lang in all_kw_sets_a:
                text = c["comment"]
                if not inc_pat.search(text):
                    continue
                if exclude_pat_a and exclude_pat_a.search(text):
                    continue
                if idx in seen_a:
                    continue
                seen_a.add(idx)
                copy = dict(c)
                detected = detect_language(c["comment"])
                copy["matched_language"] = detected
                if detected != "en":
                    copy["original_language"] = detected
                else:
                    # English comment — tag the mentioned language (e.g. "the Japanese dub")
                    _mentioned = _find_english_language_mention(c["comment"])
                    if _mentioned:
                        copy["matched_language"] = _mentioned
                matched_a.append(copy)
                break

        if not matched_a:
            status_obj.write(f"{prefix}No matches found.")
            return []

        status_obj.write(f"{prefix}Found **{len(matched_a):,}** matches.")

        # Sentiment
        add_sentiment(matched_a)
        sc = get_sentiment_counts(matched_a)
        status_obj.write(f"{prefix}+{sc['Positive']} ~{sc['Neutral']} -{sc['Negative']}")

        # Themes
        cluster_into_themes(matched_a)
        # Replace TF-IDF cluster names with semantic 2-4 word titles.
        _rename_themes_with_claude(matched_a)

        for idx, c in enumerate(matched_a):
            c["_id"] = idx

        return matched_a

    def _auto_translate_multi(multi_results):
        """Batch-translate non-English comments in each tab that don't already
        have a back_translation. Modifies comments in place."""
        to_translate = []
        for ma in multi_results:
            for c in ma.get("comments", []):
                if c.get("matched_language", "en") in ("en", "all"):
                    continue
                if c.get("back_translation") and c["back_translation"] != c["comment"]:
                    continue
                to_translate.append(c)
        if not to_translate:
            return
        texts = [c["comment"] for c in to_translate]
        with st.spinner(f"Translating {len(texts):,} non-English comments..."):
            translations = batch_back_translate(texts)
        for c, translation in zip(to_translate, translations):
            c["back_translation"] = translation
            if not c.get("original_language"):
                c["original_language"] = c.get("matched_language", detect_language(c["comment"]))

    def _backfill_summaries(multi_results, search_query=""):
        """Generate any missing per-tab AI summaries and one-liners. Safe to
        call after upload so older exports pick up the newer UI features."""
        for mi, mr in enumerate(multi_results):
            if not mr.get("comments"):
                continue
            _ai_key = f"ai_summary_{mi}"
            if not st.session_state.get(_ai_key):
                with st.spinner(f"Generating AI summary for {mr['name']}..."):
                    st.session_state[_ai_key] = generate_ai_summary(
                        mr["comments"], search_query
                    )
            _ol_key = f"one_liner_{mi}"
            if not st.session_state.get(_ol_key):
                with st.spinner(f"Generating one-line summary for {mr['name']}..."):
                    st.session_state[_ol_key] = generate_one_line_summary(
                        mr["comments"], mr["name"]
                    )

    def _auto_run_subtitles_dubs(raw_comments, search_query=""):
        """Auto-run Subtitles & Dubs analysis in all languages."""
        preset_data = KEYWORD_PRESETS["Subtitles & Dubs"]
        multi_names = preset_data["analyses"]
        all_lang_names = list(SUPPORTED_LANGUAGES.keys())

        status = st.status("Running Subtitles & Dubs analysis...", expanded=True)
        multi_results = []
        for mi, analysis_name in enumerate(multi_names):
            status.update(label=f"Analyzing {analysis_name} ({mi+1}/{len(multi_names)})...")
            sub_preset = KEYWORD_PRESETS[analysis_name]
            sub_kw = sub_preset["keywords"]
            sub_trans: dict[str, list[str]] = {}
            for lang_name in all_lang_names:
                lc = SUPPORTED_LANGUAGES[lang_name]
                if lc in sub_preset.get("translations", {}):
                    sub_trans[lc] = sub_preset["translations"][lc]
                else:
                    sub_trans[lc] = translate_keywords(sub_kw, lc)

            result = _run_single_analysis(
                raw_comments, sub_kw, [], sub_trans, status, label=analysis_name
            )
            multi_results.append({"name": analysis_name, "comments": result})

        status.update(label="Analysis complete.", state="complete", expanded=False)

        # Auto-translate any non-English comments before storing so the cards
        # render with translations on first page 2 load.
        _auto_translate_multi(multi_results)

        st.session_state["multi_analyses"] = multi_results
        st.session_state["analyzed_comments"] = multi_results[0]["comments"] if multi_results else []
        st.session_state["hidden_ids"] = set()
        st.session_state["keywords"] = []
        st.session_state["keyword_preset"] = "Subtitles & Dubs"
        st.session_state["selected_langs"] = all_lang_names
        st.session_state.pop("ai_summary", None)
        st.session_state.pop("ai_summary_0", None)
        st.session_state.pop("ai_summary_1", None)
        st.session_state.pop("one_liner_0", None)
        st.session_state.pop("one_liner_1", None)
        st.session_state.pop("custom_search_results", None)
        for k in ["fs_videos", "fs_sentiment", "fs_language", "fs_text_search",
                   "fs_text_exclude", "fs_min_likes", "fs_sort"]:
            st.session_state.pop(k, None)

        total_matches = sum(len(r["comments"]) for r in multi_results)
        st.success(f"**{total_matches:,}** total matches across {len(multi_names)} analyses.")

        # Auto-generate AI summaries for each tab
        for mi, mr in enumerate(multi_results):
            if mr["comments"]:
                _ai_key = f"ai_summary_{mi}"
                if _ai_key not in st.session_state:
                    with st.spinner(f"Generating AI summary for {mr['name']}..."):
                        _sum = generate_ai_summary(mr["comments"], search_query)
                        st.session_state[_ai_key] = _sum
                _ol_key = f"one_liner_{mi}"
                if _ol_key not in st.session_state:
                    with st.spinner(f"Generating one-line summary for {mr['name']}..."):
                        st.session_state[_ol_key] = generate_one_line_summary(
                            mr["comments"], mr["name"]
                        )

    # Session Update — re-fetch newer comments for the videos already loaded in this session.
    # Fetches comments posted since the latest stored comment date for the session's videos.
    if st.session_state.pop("_needs_session_update", False):
        from googleapiclient.errors import HttpError

        existing_comments = st.session_state.get("raw_comments", [])
        existing_ids = {c["comment_id"] for c in existing_comments if c.get("comment_id")}
        latest_date = max((c.get("date", "") for c in existing_comments), default="")
        video_ids_update = st.session_state.get("video_ids", [])

        if not video_ids_update:
            st.warning("No video IDs stored in this session — can't run update.")
        elif not latest_date:
            st.warning("Existing comments have no timestamps — can't determine cutoff.")
        else:
            youtube = get_youtube_client(api_key)
            try:
                videos = get_video_info(youtube, video_ids_update)
            except HttpError as e:
                reason = e.error_details[0]["reason"] if e.error_details else str(e)
                st.error(f"YouTube API error: {reason}")
                videos = []

            if videos:
                st.info(
                    f"Fetching comments newer than **{latest_date[:10]}** "
                    f"for **{len(videos)}** video(s)..."
                )
                new_comments: list[dict] = []
                status = st.status("Fetching new comments...", expanded=True)
                try:
                    for video in videos:
                        counter = status.empty()
                        vid_label = video["title"][:50]
                        request = youtube.commentThreads().list(
                            part="snippet",
                            videoId=video["video_id"],
                            maxResults=MAX_RESULTS_PER_PAGE,
                            textFormat="plainText",
                            order="time",
                        )
                        hit_cutoff = False
                        while request and not hit_cutoff:
                            try:
                                response = _api_call_with_retry(request)
                            except Exception:
                                break
                            for item in response.get("items", []):
                                thread_id = item["snippet"]["topLevelComment"]["id"]
                                if thread_id in existing_ids:
                                    continue
                                snippet = item["snippet"]["topLevelComment"]["snippet"]
                                comment_date = snippet["publishedAt"]
                                if comment_date <= latest_date:
                                    hit_cutoff = True
                                    break
                                new_comments.append({
                                    "author": snippet["authorDisplayName"],
                                    "comment": snippet["textDisplay"],
                                    "likes": snippet["likeCount"],
                                    "replies": item["snippet"]["totalReplyCount"],
                                    "date": comment_date,
                                    "video_id": video["video_id"],
                                    "video_title": video["title"],
                                    "is_reply": False,
                                    "comment_id": thread_id,
                                })
                            counter.markdown(
                                f"**{vid_label}** — {len(new_comments):,} new comments found"
                            )
                            request = youtube.commentThreads().list_next(request, response)
                except HttpError as e:
                    reason = e.error_details[0]["reason"] if e.error_details else str(e)
                    status.write(f"API error: {reason}")

                merged = new_comments + existing_comments
                status.update(
                    label=f"Found {len(new_comments):,} new comments. Total: {len(merged):,}.",
                    state="complete", expanded=False,
                )
                st.session_state["raw_comments"] = merged
                # Refresh local variable so downstream handlers see merged set
                raw_comments = merged

                if new_comments:
                    _existing_multi = st.session_state.get("multi_analyses") or []
                    if _existing_multi:
                        st.session_state["_update_new_comments"] = new_comments
                        st.session_state["_needs_delta_analysis"] = True
                    else:
                        st.session_state["_needs_auto_analysis"] = True
                    st.success(
                        f"Merged **{len(new_comments):,}** new comments into the current session."
                    )
                else:
                    st.info("No new comments since the last pull.")

    # Auto-run analysis after fetch
    if st.session_state.pop("_needs_auto_analysis", False):
        _auto_run_subtitles_dubs(raw_comments, sq)
        st.session_state["_charts_stale"] = False

    # Auto-translate after upload (only untranslated non-English comments)
    if st.session_state.pop("_needs_auto_translate", False):
        _ma_auto = st.session_state.get("multi_analyses") or []
        if _ma_auto:
            _auto_translate_multi(_ma_auto)
            st.session_state["multi_analyses"] = _ma_auto

    # Backfill missing summaries / one-liners on upload so old exports pick up
    # new UI features without requiring the user to manually regenerate.
    if st.session_state.pop("_needs_summary_backfill", False):
        _ma_bf = st.session_state.get("multi_analyses") or []
        if _ma_bf:
            _backfill_summaries(_ma_bf, st.session_state.get("search_query", ""))

    # Delta analysis — run only on NEW comments from Session Update, append to existing tabs
    if st.session_state.pop("_needs_delta_analysis", False):
        _new_comments = st.session_state.pop("_update_new_comments", [])
        _existing_multi = st.session_state.get("multi_analyses") or []

        if _new_comments and _existing_multi:
            status = st.status(f"Analyzing {len(_new_comments):,} new comments...", expanded=True)
            preset_data = KEYWORD_PRESETS["Subtitles & Dubs"]
            multi_names = preset_data["analyses"]
            all_lang_names = list(SUPPORTED_LANGUAGES.keys())

            # Build index of existing tabs by name
            _by_name = {ma["name"]: ma for ma in _existing_multi}

            for mi, analysis_name in enumerate(multi_names):
                status.update(label=f"Analyzing new comments for {analysis_name}...")
                sub_preset = KEYWORD_PRESETS[analysis_name]
                sub_kw = sub_preset["keywords"]
                sub_trans: dict[str, list[str]] = {}
                for lang_name in all_lang_names:
                    lc = SUPPORTED_LANGUAGES[lang_name]
                    if lc in sub_preset.get("translations", {}):
                        sub_trans[lc] = sub_preset["translations"][lc]
                    else:
                        sub_trans[lc] = translate_keywords(sub_kw, lc)

                new_matches = _run_single_analysis(
                    _new_comments, sub_kw, [], sub_trans, status, label=analysis_name
                )

                if new_matches and analysis_name in _by_name:
                    existing_tab = _by_name[analysis_name]
                    existing_comments_list = existing_tab.get("comments", [])
                    # Re-assign IDs to avoid collisions with existing
                    _max_id = max((c.get("_id", 0) for c in existing_comments_list if isinstance(c.get("_id"), int)), default=-1)
                    for idx, c in enumerate(new_matches):
                        c["_id"] = _max_id + 1 + idx
                    existing_tab["comments"] = existing_comments_list + new_matches

            # Auto-translate any new non-English comments (existing translations
            # are preserved; only untranslated comments are sent to the API).
            _auto_translate_multi(_existing_multi)
            # Regenerate missing summaries / one-liners so the UI is complete.
            _backfill_summaries(_existing_multi, st.session_state.get("search_query", ""))

            status.update(label="Delta analysis complete.", state="complete", expanded=False)
            st.session_state["multi_analyses"] = _existing_multi
            # Ensure analyzed_comments exists so page 2 renders
            _all_ac = []
            for _ma in _existing_multi:
                _all_ac.extend(_ma.get("comments", []))
            st.session_state["analyzed_comments"] = _all_ac
            st.success(f"Added new comments to analysis tabs. Your existing overrides and translations are preserved.")
            st.rerun()

    # Reanalyze trigger (button lives in sidebar, flag is set there)
    if st.session_state.pop("_needs_reanalyze", False) and "raw_comments" in st.session_state and "multi_analyses" in st.session_state:
        _raw = st.session_state["raw_comments"]
        if True:  # preserve indentation of existing block
            _overrides: dict[str, dict] = {}
            for _src in [st.session_state.get("multi_analyses")]:
                if not _src:
                    continue
                for _ma in _src:
                    if not isinstance(_ma, dict):
                        continue
                    for c in _ma.get("comments", []):
                        cid = c.get("comment_id", "")
                        if not cid:
                            continue
                        override = {}
                        if c.get("sentiment_override"):
                            override["sentiment_label"] = c["sentiment_label"]
                        if c.get("back_translation") and c["back_translation"] != c["comment"]:
                            override["back_translation"] = c["back_translation"]
                            override["original_language"] = c.get("original_language", "")
                        if override:
                            _overrides[cid] = override

            with st.spinner("Reprocessing..."):
                _auto_run_subtitles_dubs(_raw, st.session_state.get("search_query", ""))

            _multi = st.session_state.get("multi_analyses", [])
            _applied = 0
            for _ma in (_multi or []):
                for c in _ma.get("comments", []):
                    cid = c.get("comment_id", "")
                    if cid in _overrides:
                        ov = _overrides[cid]
                        if "sentiment_label" in ov:
                            c["sentiment_label"] = ov["sentiment_label"]
                            c["sentiment_override"] = True
                        if "back_translation" in ov:
                            c["back_translation"] = ov["back_translation"]
                            c["original_language"] = ov["original_language"]
                        _applied += 1
            st.session_state["_charts_stale"] = False
            st.rerun()

    # --- Nothing analyzed yet ---
    if "analyzed_comments" not in st.session_state:
        return

    multi_analyses = st.session_state.get("multi_analyses")
    hidden_ids = st.session_state.get("hidden_ids", set())
    kws = st.session_state.get("keywords", [])
    if "_bulk_selected" not in st.session_state:
        st.session_state["_bulk_selected"] = set()
    bulk_selected = st.session_state["_bulk_selected"]

    # Fill the Reanalyze slot now that analysis handlers have run
    if multi_analyses:
        if _reanalyze_btn_slot.button("Reanalyze Data", key="sidebar_reanalyze_top", type="primary"):
            st.session_state["_needs_reanalyze"] = True
            st.rerun()

    # Tab selector for multi-analysis
    _active_tab = 0
    if multi_analyses and len(multi_analyses) > 1:
        _all_multi_comments = []
        for _ma in multi_analyses:
            _all_multi_comments.extend(_ma["comments"])
        _vis_multi = [c for c in _all_multi_comments if c["_id"] not in hidden_ids]

        # Sidebar Filter & Sort (applies to all tabs)
        st.sidebar.header("Filter & Sort")
        _sb_text_search = st.sidebar.text_input("Search within comments",
                                                placeholder="e.g. auto-generated",
                                                key="sb_text_search")
        _sb_text_exclude = st.sidebar.text_input("Does not contain",
                                                 placeholder="e.g. spam, bot",
                                                 key="sb_text_exclude")
        _sb_min_likes = st.sidebar.number_input("Min likes", min_value=0, value=0,
                                                step=1, key="sb_min_likes")
        _sb_sort_opts = {
            "Likes (most)": ("likes", True),
            "Likes (fewest)": ("likes", False),
            "Date (newest)": ("date", True),
            "Date (oldest)": ("date", False),
        }
        _sb_sort = st.sidebar.selectbox("Sort by", options=list(_sb_sort_opts.keys()), key="sb_sort")
        st.sidebar.divider()

        st.sidebar.header("Bulk Actions")
        st.sidebar.caption(f"**{len(bulk_selected)}** selected")

        _bs1, _bs2 = st.sidebar.columns([0.6, 0.4])
        with _bs1:
            _m_bulk_sent = st.selectbox("Sentiment", options=["Positive", "Neutral", "Negative"],
                                        key="m_bulk_sent", label_visibility="collapsed")
        with _bs2:
            if st.button("Apply", key="m_bulk_apply_sent", type="primary"):
                changed = 0
                for c in _all_multi_comments:
                    if c["_id"] in bulk_selected and c["sentiment_label"] != _m_bulk_sent:
                        c["sentiment_label"] = _m_bulk_sent
                        c["sentiment_override"] = True
                        changed += 1
                if changed:
                    st.session_state["_bulk_selected"] = set()
                    for k in list(st.session_state.keys()):
                        if k.startswith("sel_"):
                            st.session_state.pop(k, None)
                    st.rerun()

        _m_lang_opts = ["en"] + sorted(set(SUPPORTED_LANGUAGES.values()))
        _m_lang_disp = [LANGUAGE_NAMES.get(lc, lc) for lc in _m_lang_opts]
        _bl1, _bl2 = st.sidebar.columns([0.6, 0.4])
        with _bl1:
            _m_bulk_lang = st.selectbox("Language", options=_m_lang_disp,
                                        key="m_bulk_lang", label_visibility="collapsed")
        with _bl2:
            if st.button("Apply", key="m_bulk_apply_lang", type="primary"):
                _n2c = {LANGUAGE_NAMES.get(lc, lc): lc for lc in _m_lang_opts}
                _new_code = _n2c.get(_m_bulk_lang, "en")
                changed = 0
                for c in _all_multi_comments:
                    if c["_id"] in bulk_selected and c.get("matched_language", "en") != _new_code:
                        c["matched_language"] = _new_code
                        changed += 1
                if changed:
                    st.session_state["_bulk_selected"] = set()
                    for k in list(st.session_state.keys()):
                        if k.startswith("sel_"):
                            st.session_state.pop(k, None)
                    st.rerun()

        _bk1, _bk2 = st.sidebar.columns(2)
        with _bk1:
            if st.button("Skip selected", key="m_bulk_skip"):
                for cid in bulk_selected:
                    hidden_ids.add(cid)
                st.session_state["hidden_ids"] = hidden_ids
                st.session_state["_bulk_selected"] = set()
                st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
                st.rerun()
        with _bk2:
            if st.button("Unselect all", key="m_bulk_unselect"):
                st.session_state["_bulk_selected"] = set()
                # Clear ALL selection checkbox keys
                st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
                st.rerun()
        # Define custom search renderer (runs on raw comments)
        # Comment cards in fragment to prevent full rerun on checkbox
        @st.fragment
        def _render_tab_cards(_comments, _tidx):
            _hidden_f = st.session_state.get("hidden_ids", set())
            _bsel_f = st.session_state.get("_bulk_selected", set())
            _alo = ["en"] + sorted(set(SUPPORTED_LANGUAGES.values()))
            _ald = [LANGUAGE_NAMES.get(lc, lc) for lc in _alo]
            _n2c_t = {LANGUAGE_NAMES.get(lc, lc): lc for lc in _alo}

            _groups = {}
            _sent_rank = {"Positive": 2, "Neutral": 1, "Negative": 0}
            for _lbl in ["Positive", "Neutral", "Negative"]:
                _grp = [c for c in _comments if c["sentiment_label"] == _lbl]
                if _grp:
                    # Primary sort: likes desc. Secondary: sentiment rank desc
                    # (positive > neutral > negative).
                    _grp.sort(
                        key=lambda c: (
                            c.get("likes", 0),
                            _sent_rank.get(c.get("sentiment_label"), 0),
                        ),
                        reverse=True,
                    )
                    _groups[_lbl] = _grp

            for _lbl, _grp_c in _groups.items():
                _emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}[_lbl]
                # Cluster by theme within the sentiment group so related comments
                # sit together. Themes are emitted largest-first; pagination still
                # applies to the flat, theme-ordered list.
                _theme_buckets: dict[str, list[dict]] = {}
                for _c_t in _grp_c:
                    _theme_buckets.setdefault(_c_t.get("theme", "General"), []).append(_c_t)
                _ordered_themes = sorted(_theme_buckets.keys(),
                                         key=lambda t: (-len(_theme_buckets[t]), t))
                _grp_c = [c for t in _ordered_themes for c in _theme_buckets[t]]

                with st.expander(f"**{_emoji} {_lbl}** — {len(_grp_c)} comments", expanded=False):
                    # Paginate to reduce widget count
                    _page_size = 50
                    _page_key = f"page_{_tidx}_{_lbl}"
                    _current_page = st.session_state.get(_page_key, 0)
                    _end = min((_current_page + 1) * _page_size, len(_grp_c))
                    _displayed = _grp_c[:_end]
                    _last_theme = None
                    for c in _displayed:
                        _this_theme = c.get("theme", "General")
                        if _this_theme != _last_theme:
                            _theme_count = len(_theme_buckets.get(_this_theme, []))
                            st.html(
                                f'<div style="margin:14px 0 6px 0;padding:4px 0;'
                                f'border-top:1px solid #e5e7eb;font-size:12px;'
                                f'font-weight:700;color:#6b7280;letter-spacing:0.5px;'
                                f'text-transform:uppercase;">'
                                f'{html_mod.escape(_this_theme)} '
                                f'<span style="color:#9ca3af;font-weight:500;">'
                                f'({_theme_count})</span></div>'
                            )
                            _last_theme = _this_theme
                        cid = c["_id"]
                        _is_skipped = cid in _hidden_f

                        _av_bg = _avatar_color(c["author"])
                        _ini = _initials(c["author"])
                        _ds = _format_date(c["date"])
                        _sb = _sentiment_badge(c["sentiment_label"])
                        _op = "0.35" if _is_skipped else "1"
                        _ct = html_mod.escape(c["comment"])
                        _at = html_mod.escape(c["author"])

                        _lc = c.get("matched_language", "en")
                        _lt = ""
                        if _lc not in ("en", "all"):
                            _ll = LANGUAGE_NAMES.get(_lc, _lc)
                            _lt = (f'<span style="padding:1px 6px;border-radius:4px;font-size:10px;'
                                   f'font-weight:500;color:#00BCE7;background:#e0f7fc;margin-left:6px;">{_ll}</span>')

                        _rt = ""

                        _tr = ""
                        if c.get("back_translation") and c.get("original_language"):
                            _bt = html_mod.escape(c["back_translation"])
                            _tr = (f'<div style="margin-top:4px;padding:4px 8px;background:#f0f4ff;'
                                   f'border-left:2px solid #00BCE7;border-radius:3px;font-size:12px;'
                                   f'color:#4a5568;font-style:italic;">🌐 {_bt}</div>')

                        # Single row: checkbox | card | skip | lang
                        _tc1, _tc2, _tcP, _tcN, _tcNg, _tc3, _tc4 = st.columns(
                            [0.03, 0.62, 0.04, 0.04, 0.04, 0.08, 0.15], vertical_alignment="top"
                        )
                        _sver_t = st.session_state.get("_sel_version", 0)
                        with _tc1:
                            _sel = st.checkbox("s", value=(cid in _bsel_f),
                                               key=f"sel_{_tidx}_{cid}_v{_sver_t}", label_visibility="collapsed")
                            if _sel:
                                _bsel_f.add(cid)
                            else:
                                _bsel_f.discard(cid)
                        _cur_sent = c["sentiment_label"]
                        with _tcP:
                            if st.button("😊", key=f"pos_{_tidx}_{cid}",
                                         type="primary" if _cur_sent == "Positive" else "secondary",
                                         help="Mark as Positive"):
                                c["sentiment_label"] = "Positive"
                                c["sentiment_override"] = True
                                st.session_state["_charts_stale"] = True
                                st.rerun(scope="fragment")
                        with _tcN:
                            if st.button("😐", key=f"neu_{_tidx}_{cid}",
                                         type="primary" if _cur_sent == "Neutral" else "secondary",
                                         help="Mark as Neutral"):
                                c["sentiment_label"] = "Neutral"
                                c["sentiment_override"] = True
                                st.session_state["_charts_stale"] = True
                                st.rerun(scope="fragment")
                        with _tcNg:
                            if st.button("😞", key=f"neg_{_tidx}_{cid}",
                                         type="primary" if _cur_sent == "Negative" else "secondary",
                                         help="Mark as Negative"):
                                c["sentiment_label"] = "Negative"
                                c["sentiment_override"] = True
                                st.session_state["_charts_stale"] = True
                                st.rerun(scope="fragment")
                        with _tc2:
                            st.html(f"""
                            <div style="display:flex;gap:8px;opacity:{_op};align-items:flex-start;">
                              <div style="flex-shrink:0;width:28px;height:28px;border-radius:50%;
                                          background:{_av_bg};display:flex;align-items:center;
                                          justify-content:center;color:#fff;font-weight:700;font-size:11px;">
                                {_ini}
                              </div>
                              <div style="flex:1;min-width:0;">
                                <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">
                                  {_rt}
                                  <span style="font-weight:600;font-size:12px;color:#030303;">{_at}</span>
                                  <span style="font-size:10px;color:#909090;">{_ds}</span>
                                  {_sb}{_lt}
                                  {f'<span style="color:#909090;font-size:10px;">👍{c["likes"]}</span>' if c.get("likes", 0) > 0 else ''}
                                </div>
                                <div style="margin-top:2px;font-size:13px;color:#030303;line-height:1.3;">{_ct}</div>
                                {_tr}
                              </div>
                            </div>
                            """)
                        with _tc3:
                            if not _is_skipped:
                                if st.button("Skip", key=f"skip_{_tidx}_{cid}"):
                                    _hidden_f.add(cid)
                                    st.session_state["hidden_ids"] = _hidden_f
                                    st.session_state["_charts_stale"] = True
                                    st.rerun(scope="fragment")
                            else:
                                if st.button("Incl", key=f"inc_{_tidx}_{cid}"):
                                    _hidden_f.discard(cid)
                                    st.session_state["hidden_ids"] = _hidden_f
                                    st.session_state["_charts_stale"] = True
                                    st.rerun(scope="fragment")
                        with _tc4:
                            _clc = c.get("matched_language", "en")
                            _cld = LANGUAGE_NAMES.get(_clc, _clc)
                            _mlk = f"lang_{_tidx}_{cid}"
                            if _mlk not in st.session_state:
                                st.session_state[_mlk] = _cld
                            _nld = st.selectbox("L", options=_ald, key=_mlk, label_visibility="collapsed")
                            _nlc = _n2c_t.get(_nld, _clc)
                            if _nlc != c.get("matched_language", "en"):
                                c["matched_language"] = _nlc
                                # Auto-translate on language change. If the new
                                # language is English, clear any stale translation.
                                if _nlc in ("en", "all"):
                                    c.pop("back_translation", None)
                                    c.pop("original_language", None)
                                else:
                                    with st.spinner("Translating..."):
                                        _translated = back_translate(c["comment"], _nlc)
                                    c["back_translation"] = _translated
                                    c["original_language"] = _nlc
                                st.session_state["_charts_stale"] = True
                                st.rerun(scope="fragment")

                    # Show more button
                    if _end < len(_grp_c):
                        _remaining = len(_grp_c) - _end
                        if st.button(f"Show more ({_remaining:,} remaining)", key=f"more_{_tidx}_{_lbl}"):
                            st.session_state[_page_key] = _current_page + 1

            st.session_state["hidden_ids"] = _hidden_f
            st.session_state["_bulk_selected"] = _bsel_f

        def _render_custom_search_tab(raw_comments, sq, _title_slug, _export_ts, hidden_ids, bulk_selected):
            st.caption("Search any keywords across ALL raw comments (not limited to Subtitles or Dubbing matches).")

            _cs_c1, _cs_c2 = st.columns(2)
            with _cs_c1:
                _cs_kw_input = st.text_input(
                    "Keywords (comma-separated)",
                    placeholder="e.g. lighting, audio, editing",
                    key="custom_kw_input",
                )
            with _cs_c2:
                _cs_excl_input = st.text_input(
                    "Exclude (comma-separated)",
                    placeholder="e.g. spam, bot",
                    key="custom_excl_input",
                )

            _cs_kw = [k.strip() for k in _cs_kw_input.split(",") if k.strip()]
            _cs_excl = [k.strip() for k in _cs_excl_input.split(",") if k.strip()]

            if st.button("Search", type="primary", key="custom_search_run"):
                if not _cs_kw:
                    st.warning("Enter at least one keyword.")
                else:
                    with st.spinner(f"Searching {len(raw_comments):,} comments..."):
                        pat = _build_keyword_pattern(_cs_kw)
                        excl_pat = _build_keyword_pattern(_cs_excl)
                        matched = []
                        if pat:
                            for c in raw_comments:
                                text = c["comment"]
                                if not pat.search(text):
                                    continue
                                if excl_pat and excl_pat.search(text):
                                    continue
                                copy = dict(c)
                                detected = detect_language(c["comment"])
                                copy["matched_language"] = detected
                                if detected != "en":
                                    copy["original_language"] = detected
                                else:
                                    _mentioned = _find_english_language_mention(c["comment"])
                                    if _mentioned:
                                        copy["matched_language"] = _mentioned
                                matched.append(copy)

                        if matched:
                            add_sentiment(matched)
                            cluster_into_themes(matched)
                            _rename_themes_with_claude(matched)
                            for idx, c in enumerate(matched):
                                c["_id"] = f"cs_{idx}"

                            st.session_state["custom_search_results"] = matched
                            st.session_state["custom_search_keywords"] = _cs_kw
                            st.session_state["custom_search_exclude"] = _cs_excl
                            st.session_state.pop("ai_summary_custom", None)
                            st.rerun()
                        else:
                            st.warning("No matches found.")

            # Show existing results
            _results = st.session_state.get("custom_search_results", [])
            if not _results:
                st.info("Enter keywords and click Search to filter raw comments.")
                return

            st.subheader(f"Custom Search — {len(_results):,} comments")

            # Sentiment bar + Language pie chart
            _cs_sc = get_sentiment_counts(_results)
            _cs_total = len(_results)
            _cs_bar_col, _cs_pie_col = st.columns([0.65, 0.35])
            with _cs_bar_col:
                st.markdown("**Sentiment Analysis**")
                _cs_bar = ""
                for _lbl in ["Positive", "Neutral", "Negative"]:
                    _cnt = _cs_sc.get(_lbl, 0)
                    _pct_v = _cnt / _cs_total * 100 if _cs_total else 0
                    _clr = SENTIMENT_COLORS[_lbl]
                    _tc = "#1a1a1a" if _lbl == "Positive" else "#fff"
                    if _pct_v > 0:
                        _cs_bar += (
                            f'<div style="flex:{_pct_v};background:{_clr};height:32px;'
                            f'display:flex;align-items:center;justify-content:center;'
                            f'color:{_tc};font-size:12px;font-weight:600;'
                            f'min-width:{40 if _pct_v > 3 else 0}px;">'
                            f'{_cnt} ({_pct_v:.0f}%)</div>'
                        )
                st.html(f'<div style="display:flex;border-radius:12px;overflow:hidden;margin:8px 0 16px 0;">{_cs_bar}</div>')

            with _cs_pie_col:
                st.markdown("**Language Coverage**")
                _cs_lang_counts: dict[str, int] = {}
                for c in _results:
                    lc = c.get("matched_language", "en")
                    name = LANGUAGE_NAMES.get(lc, lc)
                    _cs_lang_counts[name] = _cs_lang_counts.get(name, 0) + 1

                if _cs_lang_counts:
                    _palette = ["#00BCE7", "#E64783", "#1CE8B5", "#C94EFF",
                                "#FFD93D", "#FF5E5B", "#CCF913", "#FF9500"]
                    _sorted_langs = sorted(_cs_lang_counts.items(), key=lambda x: -x[1])
                    _lang_total = sum(_cs_lang_counts.values())
                    _gradient_parts = []
                    _legend_parts = []
                    _running = 0
                    for _i, (_name, _ct) in enumerate(_sorted_langs):
                        _color = _palette[_i % len(_palette)]
                        _pct = _ct / _lang_total * 100
                        _gradient_parts.append(f"{_color} {_running:.2f}% {_running + _pct:.2f}%")
                        _running += _pct
                        _legend_parts.append(
                            f'<div style="display:flex;align-items:center;gap:4px;font-size:10px;margin-bottom:2px;">'
                            f'<div style="width:10px;height:10px;border-radius:2px;background:{_color};"></div>'
                            f'<span>{html_mod.escape(_name)}: {_ct:,}</span></div>'
                        )
                    _gradient = ", ".join(_gradient_parts)
                    st.html(f"""
                    <div style="display:flex;align-items:center;gap:12px;">
                      <div style="width:80px;height:80px;border-radius:50%;
                                  background:conic-gradient({_gradient});flex-shrink:0;"></div>
                      <div style="flex:1;min-width:0;max-height:100px;overflow-y:auto;
                                  display:grid;grid-template-columns:1fr 1fr;gap:0 10px;">
                        {"".join(_legend_parts)}
                      </div>
                    </div>
                    """)

            # AI Summary
            _ai_cs = st.session_state.get("ai_summary_custom", "")
            _cs_vis = [c for c in _results if c["_id"] not in hidden_ids]
            if _cs_vis:
                _btn_label_cs = "Regenerate AI Summary" if _ai_cs else "Generate AI Summary"
                if st.button(_btn_label_cs, key="gen_ai_custom", type="secondary"):
                    with st.spinner("Generating summary..."):
                        _ai_cs = generate_ai_summary(_cs_vis, sq)
                        st.session_state["ai_summary_custom"] = _ai_cs
                        st.session_state["ai_edit_custom"] = _ai_cs
                        st.rerun()
                if _ai_cs:
                    with st.expander("**Summary**", expanded=True):
                        _pv_cs, _ed_cs = st.tabs(["Preview", "Edit"])
                        if "ai_edit_custom" not in st.session_state:
                            st.session_state["ai_edit_custom"] = _ai_cs
                        with _ed_cs:
                            _edited_cs = st.text_area(
                                "Edit (supports **bold**, *italic*, <u>underline</u>)",
                                height=200,
                                key="ai_edit_custom",
                                label_visibility="collapsed",
                            )
                            if _edited_cs != _ai_cs:
                                st.session_state["ai_summary_custom"] = _edited_cs
                                _ai_cs = _edited_cs
                        with _pv_cs:
                            st.markdown(_decorate_ai_summary(_ai_cs), unsafe_allow_html=True)

            # Clear button
            if st.button("Clear search results", key="clear_custom_search"):
                st.session_state.pop("custom_search_results", None)
                st.session_state.pop("custom_search_keywords", None)
                st.session_state.pop("custom_search_exclude", None)
                st.session_state.pop("ai_summary_custom", None)
                st.rerun()

            # Render comment cards (reuse tab renderer)
            _render_tab_cards(_results, "custom")

            # PDF export for this search
            if _cs_vis:
                _cs_thumb_vid = (st.session_state.get("video_ids") or [None])[0]
                _cs_pdf = build_pdf_report(
                    _cs_vis, sq, _cs_kw,
                    ai_summary=_ai_cs,
                    preset_name=f"Custom: {', '.join(_cs_kw[:3])}",
                    thumbnail_video_id=_cs_thumb_vid,
                )
                st.download_button(
                    label="Download Custom Search PDF",
                    data=_cs_pdf,
                    file_name=f"{_title_slug}_{_export_ts}_custom.pdf",
                    mime="application/pdf",
                )

        # Make tab labels prominent
        st.html("""
        <style>
        button[data-baseweb="tab"] {
            font-size: 18px !important;
            font-weight: 700 !important;
            padding: 12px 24px !important;
        }
        </style>
        """)

        # Stale-charts banner — shown when in-line edits (sentiment, skip,
        # language) have changed data but the charts haven't been refreshed.
        if st.session_state.get("_charts_stale"):
            _sc1, _sc2 = st.columns([0.75, 0.25], vertical_alignment="center")
            with _sc1:
                st.warning(
                    "Charts and AI summaries are out of date after recent edits. "
                    "Click **Refresh Graphs** to update them."
                )
            with _sc2:
                if st.button("Refresh Graphs", key="refresh_graphs_btn", type="primary"):
                    st.session_state["_charts_stale"] = False
                    st.rerun()

        # One-line summaries per section (editable) — shown above the tabs
        for _oi, _ma_ol in enumerate(multi_analyses):
            _ol_key = f"one_liner_{_oi}"
            if _ol_key not in st.session_state:
                continue  # generated lazily; skip if not available yet
            _ol_val = st.session_state.get(_ol_key, "")
            # Parse optional [POS]/[NEG]/[NEU] tag so we can render it as a
            # colored pill next to the section name.
            _ol_tag_match = re.match(r"^\s*\[(POS|NEG|NEU)\]\s*", _ol_val)
            _ol_pill_html = ""
            if _ol_tag_match:
                _tag = _ol_tag_match.group(1)
                _label, _bg, _fg = _SENTIMENT_TAG_STYLE[_tag]
                _ol_pill_html = (
                    f'<span style="display:inline-block;padding:1px 8px;'
                    f'border-radius:10px;background:{_bg};color:{_fg};'
                    f'font-size:10px;font-weight:700;letter-spacing:0.4px;'
                    f'margin-left:6px;vertical-align:middle;">{_label.upper()}</span>'
                )
            _col_lbl, _col_val, _col_btn = st.columns([0.14, 0.74, 0.12], vertical_alignment="center")
            with _col_lbl:
                st.html(
                    f'<div style="font-weight:700;font-size:14px;">'
                    f'{html_mod.escape(_ma_ol["name"])}{_ol_pill_html}</div>'
                )
            with _col_val:
                _new_ol = st.text_input(
                    _ma_ol["name"],
                    value=_ol_val,
                    key=f"{_ol_key}_input",
                    label_visibility="collapsed",
                )
                if _new_ol != _ol_val:
                    st.session_state[_ol_key] = _new_ol
            with _col_btn:
                if st.button("Regenerate", key=f"{_ol_key}_regen"):
                    with st.spinner(f"Regenerating {_ma_ol['name']}..."):
                        _new_line = generate_one_line_summary(
                            [c for c in _ma_ol["comments"] if c["_id"] not in hidden_ids],
                            _ma_ol["name"],
                        )
                    if _new_line:
                        st.session_state[_ol_key] = _new_line
                    st.rerun()

        tab_names = [r["name"] for r in multi_analyses] + ["Custom Search"]
        tabs = st.tabs(tab_names)
        _custom_tab_idx = len(tab_names) - 1
        # We render the full view inside each tab
        for tab_idx, tab_obj in enumerate(tabs):
            with tab_obj:
                # Custom Search tab (last one)
                if tab_idx == _custom_tab_idx:
                    _render_custom_search_tab(
                        raw_comments=raw_comments,
                        sq=sq,
                        _title_slug=_title_slug,
                        _export_ts=_export_ts,
                        hidden_ids=hidden_ids,
                        bulk_selected=bulk_selected,
                    )
                    continue

                _tab_comments = multi_analyses[tab_idx]["comments"]
                _tab_name = tab_names[tab_idx]
                if not _tab_comments:
                    st.info(f"No comments matched for **{_tab_name}**.")
                    continue

                st.subheader(f"{_tab_name} — {len(_tab_comments):,} comments")

                # Sentiment bar + Language pie chart side by side
                _t_sc = get_sentiment_counts(_tab_comments)
                _t_total = len(_tab_comments)
                _bar_col, _pie_col = st.columns([0.65, 0.35])
                with _bar_col:
                    st.markdown("**Sentiment Analysis**")
                    _t_bar = ""
                    for _lbl in ["Positive", "Neutral", "Negative"]:
                        _cnt = _t_sc.get(_lbl, 0)
                        _pct_v = _cnt / _t_total * 100 if _t_total else 0
                        _clr = SENTIMENT_COLORS[_lbl]
                        _tc = "#1a1a1a" if _lbl == "Positive" else "#fff"
                        if _pct_v > 0:
                            _t_bar += (
                                f'<div style="flex:{_pct_v};background:{_clr};height:32px;'
                                f'display:flex;align-items:center;justify-content:center;'
                                f'color:{_tc};font-size:12px;font-weight:600;'
                                f'min-width:{40 if _pct_v > 3 else 0}px;">'
                                f'{_cnt} ({_pct_v:.0f}%)</div>'
                            )
                    st.html(f'<div style="display:flex;border-radius:12px;overflow:hidden;margin:8px 0 16px 0;">{_t_bar}</div>')

                with _pie_col:
                    st.markdown("**Language Coverage**")
                    # Language pie chart (this tab only)
                    _tab_lang_counts: dict[str, int] = {}
                    for c in _tab_comments:
                        lc = c.get("matched_language", "en")
                        name = LANGUAGE_NAMES.get(lc, lc)
                        _tab_lang_counts[name] = _tab_lang_counts.get(name, 0) + 1

                    if _tab_lang_counts:
                        _palette = ["#00BCE7", "#E64783", "#1CE8B5", "#C94EFF",
                                    "#FFD93D", "#FF5E5B", "#CCF913", "#FF9500"]
                        _sorted_langs = sorted(_tab_lang_counts.items(), key=lambda x: -x[1])
                        _lang_total = sum(_tab_lang_counts.values())
                        _gradient_parts = []
                        _legend_parts = []
                        _running = 0
                        for _i, (_name, _ct) in enumerate(_sorted_langs):
                            _color = _palette[_i % len(_palette)]
                            _pct = _ct / _lang_total * 100
                            _gradient_parts.append(f"{_color} {_running:.2f}% {_running + _pct:.2f}%")
                            _running += _pct
                            _legend_parts.append(
                                f'<div style="display:flex;align-items:center;gap:4px;font-size:10px;margin-bottom:2px;">'
                                f'<div style="width:10px;height:10px;border-radius:2px;background:{_color};"></div>'
                                f'<span>{html_mod.escape(_name)}: {_ct:,}</span></div>'
                            )
                        _gradient = ", ".join(_gradient_parts)
                        st.html(f"""
                        <div style="display:flex;align-items:center;gap:12px;">
                          <div style="width:80px;height:80px;border-radius:50%;
                                      background:conic-gradient({_gradient});flex-shrink:0;"></div>
                          <div style="flex:1;min-width:0;max-height:100px;overflow-y:auto;
                                      display:grid;grid-template-columns:1fr 1fr;gap:0 10px;">
                            {"".join(_legend_parts)}
                          </div>
                        </div>
                        """)

                # AI summary for this tab
                _ai_key = f"ai_summary_{tab_idx}"
                _ai_sum = st.session_state.get(_ai_key, "")
                _vis = [c for c in _tab_comments if c["_id"] not in hidden_ids]
                if _vis:
                    _btn_label = "Regenerate AI Summary" if _ai_sum else "Generate AI Summary"
                    if st.button(_btn_label, key=f"gen_ai_{tab_idx}", type="secondary"):
                        with st.spinner(f"Generating summary for {_tab_name}..."):
                            _ai_sum = generate_ai_summary(_vis, sq)
                            st.session_state[_ai_key] = _ai_sum
                            st.session_state[f"ai_edit_{tab_idx}"] = _ai_sum
                            st.rerun()
                    if _ai_sum:
                        with st.expander("**Summary**", expanded=True):
                            _pv_tab, _ed_tab = st.tabs(["Preview", "Edit"])
                            _ed_key = f"ai_edit_{tab_idx}"
                            if _ed_key not in st.session_state:
                                st.session_state[_ed_key] = _ai_sum
                            with _ed_tab:
                                _edited = st.text_area(
                                    "Edit (supports **bold**, *italic*, <u>underline</u>)",
                                    height=200,
                                    key=_ed_key,
                                    label_visibility="collapsed",
                                )
                                if _edited != _ai_sum:
                                    st.session_state[_ai_key] = _edited
                                    _ai_sum = _edited
                            with _pv_tab:
                                st.markdown(_decorate_ai_summary(_ai_sum), unsafe_allow_html=True)

                # Apply sidebar filters to this tab's comments
                _filtered_tab = _tab_comments
                if _sb_text_search:
                    _ts_low = _sb_text_search.lower()
                    _filtered_tab = [c for c in _filtered_tab if _ts_low in c["comment"].lower()]
                if _sb_text_exclude:
                    _excl_words = [w.strip().lower() for w in _sb_text_exclude.split(",") if w.strip()]
                    _filtered_tab = [c for c in _filtered_tab
                                     if not any(w in c["comment"].lower() for w in _excl_words)]
                if _sb_min_likes > 0:
                    _filtered_tab = [c for c in _filtered_tab if c.get("likes", 0) >= _sb_min_likes]
                _sk, _sr = _sb_sort_opts[_sb_sort]
                _filtered_tab = sorted(_filtered_tab, key=lambda c: c.get(_sk, ""), reverse=_sr)

                st.caption(f"Showing **{len(_filtered_tab):,}** comments")


                _render_tab_cards(_filtered_tab, tab_idx)

        # PDF export for multi-analysis
        st.divider()
        _all_vis = []
        _all_summaries = []
        for ti, ma in enumerate(multi_analyses):
            _vis_t = [c for c in ma["comments"] if c["_id"] not in hidden_ids]
            _all_vis.extend(_vis_t)
            _all_summaries.append({
                "name": ma["name"],
                "comments": _vis_t,
                "ai_summary": st.session_state.get(f"ai_summary_{ti}", ""),
                "one_liner": st.session_state.get(f"one_liner_{ti}", ""),
            })

        if _all_vis:
            _preset_name = st.session_state.get("keyword_preset", "Custom")
            # First stored video ID for the header thumbnail
            _thumb_vid_pdf = None
            _vids_pdf = st.session_state.get("video_ids") or []
            if _vids_pdf:
                _thumb_vid_pdf = _vids_pdf[0]
            else:
                for _c in st.session_state.get("raw_comments", []):
                    if _c.get("video_id"):
                        _thumb_vid_pdf = _c["video_id"]
                        break
            pdf_bytes = build_pdf_report(_all_vis, sq, kws, preset_name=_preset_name,
                                          multi_sections=_all_summaries,
                                          thumbnail_video_id=_thumb_vid_pdf)
            # Stash for sidebar download button
            st.session_state["_pdf_report_bytes"] = pdf_bytes
            st.session_state["_pdf_report_filename"] = f"{_title_slug}_{_export_ts}_report.pdf"
            # Fill the sidebar placeholder reserved earlier in the run
            _pdf_btn_slot.download_button(
                label="Download PDF Report",
                data=pdf_bytes,
                file_name=st.session_state["_pdf_report_filename"],
                mime="application/pdf",
                type="primary",
                key="sidebar_pdf_download",
            )

            # Interactive HTML (point-in-time, self-contained, shareable)
            _html_bytes = build_interactive_html_report(
                search_query=sq,
                sections=_all_summaries,
                keywords=kws,
                thumbnail_video_id=_thumb_vid_pdf,
                main_title=st.session_state.get("search_query", sq),
            ).encode("utf-8")
            _html_btn_slot.download_button(
                label="Download Shareable HTML",
                data=_html_bytes,
                file_name=f"{_title_slug}_{_export_ts}_report.html",
                mime="text/html",
                help="Self-contained interactive page — share via email, Slack, or host it yourself.",
                key="sidebar_html_download",
            )

        st.session_state["hidden_ids"] = hidden_ids
        return

    all_comments = st.session_state["analyzed_comments"]

    # --- Preview ---
    st.divider()
    st.subheader("Report Preview")
    st.caption("Un-check any comment to exclude it from the report and PDF.")

    # --- Filters & Sort ---
    # Initialize filter defaults in session state on first analysis
    all_video_titles = sorted(set(c.get("video_title", "") for c in all_comments))
    # Build language label lookup: code -> display name
    _lang_code_to_name = LANGUAGE_NAMES
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
                "Likes (most)": ("likes", True),
                "Likes (fewest)": ("likes", False),
                "Date (newest)": ("date", True),
                "Date (oldest)": ("date", False),
                "Author (A-Z)": ("author", False),
            }
            sort_choice = st.selectbox("Sort by", options=list(sort_options.keys()), key="fs_sort")

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

    # Compute visible comments (excluding hidden) for AI summary + export
    visible_comments = [c for c in display_comments if c["_id"] not in hidden_ids]

    # --- AI Summary + Export (right under sentiment bar) ---
    if visible_comments:
        ai_summary = st.session_state.get("ai_summary", "")

        if st.button("Generate AI Summary", type="secondary", key="gen_ai_summary"):
            with st.spinner("Generating AI theme summary from selected comments..."):
                ai_summary = generate_ai_summary(visible_comments, sq)
                st.session_state["ai_summary"] = ai_summary
                st.session_state["ai_summary_edit"] = ai_summary
                st.session_state["_ai_summary_source"] = "generate"
                st.session_state["_ai_summary_ids"] = {c["_id"] for c in visible_comments}

        # Check if summary is stale (comments changed since generation)
        summary_stale = False
        if ai_summary:
            saved_ids = st.session_state.get("_ai_summary_ids", set())
            current_ids = {c["_id"] for c in visible_comments}
            if saved_ids != current_ids:
                summary_stale = True

            with st.expander("**AI Theme Summary**", expanded=True):
                # Sync edit key with ai_summary
                if "ai_summary_edit" not in st.session_state:
                    st.session_state["ai_summary_edit"] = ai_summary
                elif st.session_state["ai_summary_edit"] != ai_summary and \
                     st.session_state.get("_ai_summary_source") == "generate":
                    # AI summary was just regenerated, update edit field
                    st.session_state["ai_summary_edit"] = ai_summary

                preview_tab, edit_tab = st.tabs(["Preview", "Edit"])
                with edit_tab:
                    edited_summary = st.text_area(
                        "Edit summary (supports **bold**, *italic*, <u>underline</u>)",
                        height=200,
                        key="ai_summary_edit",
                        label_visibility="collapsed",
                    )
                    if edited_summary != ai_summary:
                        st.session_state["ai_summary"] = edited_summary
                        ai_summary = edited_summary
                with preview_tab:
                    st.markdown(_decorate_ai_summary(ai_summary), unsafe_allow_html=True)

                if summary_stale:
                    st.warning("Comments have changed since this summary was generated. "
                               "Click **Generate AI Summary** above to refresh.")

        _preset = st.session_state.get("keyword_preset", "Custom")
        _sa_thumb_vid = (st.session_state.get("video_ids") or [None])[0]
        pdf_bytes = build_pdf_report(
            visible_comments, sq, kws,
            ai_summary=ai_summary,
            preset_name=_preset,
            thumbnail_video_id=_sa_thumb_vid,
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

    # Group comments by sentiment, most liked first (ties broken by positivity)
    sentiment_groups = {}
    _sent_rank_sa = {"Positive": 2, "Neutral": 1, "Negative": 0}
    for label in ["Positive", "Neutral", "Negative"]:
        group = [c for c in display_comments if c["sentiment_label"] == label]
        if group:
            group.sort(
                key=lambda c: (
                    c.get("likes", 0),
                    _sent_rank_sa.get(c.get("sentiment_label"), 0),
                ),
                reverse=True,
            )
            sentiment_groups[label] = group

    st.caption(f"Showing **{total:,}** comments")

    # --- Language Detection (sidebar, uses visible comments) ---
    visible_for_lang = [c for c in all_comments if c["_id"] not in hidden_ids]
    lang_counts: dict[str, int] = {}
    for c in visible_for_lang:
        lc = c.get("matched_language", "en")
        name = LANGUAGE_NAMES.get(lc, lc)
        lang_counts[name] = lang_counts.get(name, 0) + 1

    non_english = [
        c for c in visible_for_lang
        if c.get("matched_language", "en") != "en"
        and c.get("matched_language") != "all"
        and (not c.get("back_translation") or c["back_translation"] == c["comment"])
    ]

    st.sidebar.header("Language Detection")
    lang_parts = [f"{name}: {count:,}" for name, count in
                  sorted(lang_counts.items(), key=lambda x: -x[1])]
    st.sidebar.caption(" · ".join(lang_parts))

    if non_english:
        st.sidebar.caption(f"**{len(non_english):,}** untranslated")
        if st.sidebar.button("Translate All", key="bulk_translate", type="primary"):
            texts = [c["comment"] for c in non_english]
            with st.spinner(f"Translating {len(texts):,} comments in batch..."):
                translations = batch_back_translate(texts)
            for c, translation in zip(non_english, translations):
                c["back_translation"] = translation
                c["original_language"] = c.get("matched_language", detect_language(c["comment"]))
            st.rerun()

    st.sidebar.divider()

    # Bulk actions in sidebar
    st.sidebar.header("Bulk Actions")
    st.sidebar.caption(f"**{len(bulk_selected)}** selected")

    # Sentiment
    _bs_col1, _bs_col2 = st.sidebar.columns([0.6, 0.4])
    with _bs_col1:
        bulk_target = st.selectbox(
            "Sentiment",
            options=["Positive", "Neutral", "Negative"],
            key="bulk_sentiment_target",
            label_visibility="collapsed",
        )
    with _bs_col2:
        if st.button("Apply", key="bulk_apply_sent", type="primary"):
            changed = 0
            for c in all_comments:
                if c["_id"] in bulk_selected and c["sentiment_label"] != bulk_target:
                    c["sentiment_label"] = bulk_target
                    c["sentiment_override"] = True
                    changed += 1
            if changed:
                st.session_state["_bulk_selected"] = set()
                st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
                st.rerun()

    # Language
    _bulk_lang_opts = ["en"] + sorted(set(SUPPORTED_LANGUAGES.values()))
    _bulk_lang_display = [LANGUAGE_NAMES.get(lc, lc) for lc in _bulk_lang_opts]
    _bl_col1, _bl_col2 = st.sidebar.columns([0.6, 0.4])
    with _bl_col1:
        bulk_lang = st.selectbox(
            "Language",
            options=_bulk_lang_display,
            key="bulk_lang_target",
            label_visibility="collapsed",
        )
    with _bl_col2:
        if st.button("Apply", key="bulk_apply_lang", type="primary"):
            _n2c = {LANGUAGE_NAMES.get(lc, lc): lc for lc in _bulk_lang_opts}
            _new_code = _n2c.get(bulk_lang, "en")
            changed = 0
            for c in all_comments:
                if c["_id"] in bulk_selected and c.get("matched_language", "en") != _new_code:
                    c["matched_language"] = _new_code
                    st.session_state.pop(f"lang_{c['_id']}", None)
                    changed += 1
            if changed:
                st.session_state["_bulk_selected"] = set()
                st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
                st.rerun()

    # Skip + Unselect
    _bk_col1, _bk_col2 = st.sidebar.columns(2)
    with _bk_col1:
        if st.button("Skip selected", key="bulk_skip"):
            for cid in bulk_selected:
                hidden_ids.add(cid)
            st.session_state["hidden_ids"] = hidden_ids
            st.session_state["_bulk_selected"] = set()
            st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
            st.rerun()
    with _bk_col2:
        if st.button("Unselect all", key="bulk_unselect"):
            st.session_state["_bulk_selected"] = set()
            st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1
            st.rerun()


    # Render sentiment-grouped comment cards (fragment prevents full page rerun on checkbox)
    @st.fragment
    def _render_cards():
        _hidden = st.session_state.get("hidden_ids", set())
        _bsel = st.session_state.get("_bulk_selected", set())

        def _clear_selections():
            st.session_state["_bulk_selected"] = set()
            st.session_state["_sel_version"] = st.session_state.get("_sel_version", 0) + 1

        _all_lang_opts = ["en"] + sorted(set(SUPPORTED_LANGUAGES.values()))
        _lang_display = [LANGUAGE_NAMES.get(lc, lc) for lc in _all_lang_opts]
        _n2c_r = {LANGUAGE_NAMES.get(lc, lc): lc for lc in _all_lang_opts}

        for label, group_comments in sentiment_groups.items():
            emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}[label]
            with st.expander(f"**{emoji} {label}** — {len(group_comments)} comments", expanded=True):
                for c in group_comments:
                    cid = c["_id"]
                    is_skipped = cid in _hidden

                    # Build HTML card
                    avatar_bg = _avatar_color(c["author"])
                    initials = _initials(c["author"])
                    date_str = _format_date(c["date"])
                    sentiment_html = _sentiment_badge(c["sentiment_label"])
                    opacity = "0.35" if is_skipped else "1"
                    comment_text = html_mod.escape(c["comment"])
                    author_text = html_mod.escape(c["author"])

                    lang_code = c.get("matched_language", "en")
                    lang_tag = ""
                    if lang_code not in ("en", "all"):
                        ll = LANGUAGE_NAMES.get(lang_code, lang_code)
                        lang_tag = (f'<span style="padding:1px 6px;border-radius:4px;font-size:10px;'
                                    f'font-weight:500;color:#00BCE7;background:#e0f7fc;margin-left:6px;">{ll}</span>')

                    reply_tag = ""

                    meta = ""
                    if c.get("likes", 0) > 0:
                        meta += f'<span style="color:#909090;font-size:11px;margin-right:8px;">👍 {c["likes"]}</span>'
                    if c.get("replies", 0) > 0:
                        meta += f'<span style="color:#909090;font-size:11px;">💬 {c["replies"]}</span>'

                    tr_html = ""
                    if c.get("back_translation") and c.get("original_language"):
                        bt = html_mod.escape(c["back_translation"])
                        tr_html = (f'<div style="margin-top:4px;padding:4px 8px;background:#f0f4ff;'
                                   f'border-left:2px solid #00BCE7;border-radius:3px;font-size:12px;'
                                   f'color:#4a5568;font-style:italic;">🌐 {bt}</div>')

                    # Single row: checkbox | comment card | skip | lang
                    _c1, _c2, _c3, _c4 = st.columns([0.03, 0.77, 0.07, 0.13], vertical_alignment="top")
                    _sver = st.session_state.get("_sel_version", 0)
                    with _c1:
                        sel = st.checkbox("s", value=(cid in _bsel), key=f"sel_{cid}_v{_sver}", label_visibility="collapsed")
                        if sel:
                            _bsel.add(cid)
                        else:
                            _bsel.discard(cid)
                    with _c2:
                        st.html(f"""
                        <div style="display:flex;gap:8px;opacity:{opacity};align-items:flex-start;">
                          <div style="flex-shrink:0;width:28px;height:28px;border-radius:50%;
                                      background:{avatar_bg};display:flex;align-items:center;
                                      justify-content:center;color:#fff;font-weight:700;font-size:11px;">
                            {initials}
                          </div>
                          <div style="flex:1;min-width:0;">
                            <div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">
                              {reply_tag}
                              <span style="font-weight:600;font-size:12px;color:#030303;">{author_text}</span>
                              <span style="font-size:10px;color:#909090;">{date_str}</span>
                              {sentiment_html}{lang_tag}
                              {f'<span style="color:#909090;font-size:10px;">👍{c["likes"]}</span>' if c.get("likes", 0) > 0 else ''}
                            </div>
                            <div style="margin-top:2px;font-size:13px;color:#030303;line-height:1.3;">{comment_text}</div>
                            {tr_html}
                          </div>
                        </div>
                        """)
                    with _c3:
                        if not is_skipped:
                            if st.button("Skip", key=f"skip_{cid}"):
                                _hidden.add(cid)
                                _clear_selections()
                        else:
                            if st.button("Incl", key=f"unskip_{cid}"):
                                _hidden.discard(cid)
                                _clear_selections()
                    with _c4:
                        _cur_lc = c.get("matched_language", "en")
                        _cur_disp = LANGUAGE_NAMES.get(_cur_lc, _cur_lc)
                        _lk = f"lang_{cid}"
                        if _lk not in st.session_state:
                            st.session_state[_lk] = _cur_disp
                        _new_ld = st.selectbox("L", options=_lang_display, key=_lk, label_visibility="collapsed")
                        _new_lc = _n2c_r.get(_new_ld, _cur_lc)
                        if _new_lc != c.get("matched_language", "en"):
                            c["matched_language"] = _new_lc

        st.session_state["hidden_ids"] = _hidden
        st.session_state["_bulk_selected"] = _bsel

    _render_cards()



if __name__ == "__main__":
    main()

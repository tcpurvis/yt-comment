import html
import io
import json as _json
import urllib.request
from datetime import datetime, timezone, timedelta

_ET = timezone(timedelta(hours=-5))

from fpdf import FPDF

from config import SENTIMENT_COLORS, THEME_PALETTE
from analysis import get_theme_summary, get_sentiment_counts


def _fetch_thumbnail_bytes(video_id: str) -> bytes | None:
    """Download a YouTube thumbnail for embedding in the PDF. Tries maxres first,
    falling back to hq. Returns None on failure so callers can skip gracefully."""
    if not video_id:
        return None
    for quality in ("maxresdefault", "hqdefault"):
        url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            continue
    return None


def _initials(name: str) -> str:
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "?"


def _avatar_color(name: str) -> str:
    from config import THEME_PALETTE
    return THEME_PALETTE[hash(name) % len(THEME_PALETTE)]


def _sentiment_badge(label: str) -> str:
    color = SENTIMENT_COLORS.get(label, "#C94EFF")
    emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}.get(label, "")
    text_color = "#1a1a1a" if label == "Positive" else "#fff"
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'font-size:11px;font-weight:600;color:{text_color};background:{color};">'
        f'{emoji} {label}</span>'
    )


def _like_icon(count: int) -> str:
    if count == 0:
        return ""
    return (
        f'<span style="color:#606060;font-size:12px;margin-left:12px;">'
        f'👍 {count}</span>'
    )


def _reply_icon(count: int) -> str:
    if count == 0:
        return ""
    return (
        f'<span style="color:#606060;font-size:12px;margin-left:8px;">'
        f'💬 {count}</span>'
    )


def _format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return iso_str


def _video_tag(c: dict, show_video_tag: bool) -> str:
    if not show_video_tag or not c.get("video_title"):
        return ""
    vt = html.escape(c["video_title"])
    return (
        f'<div style="margin-bottom:4px;">'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'font-size:11px;font-weight:500;color:#4a5568;background:#f3f4f6;">'
        f'🎬 {vt}</span></div>'
    )


def _comment_card(c: dict, show_video_tag: bool = False) -> str:
    author = html.escape(c["author"])
    text = html.escape(c["comment"])
    avatar_bg = _avatar_color(c["author"])
    initials = _initials(c["author"])
    date_str = _format_date(c["date"])
    sentiment = _sentiment_badge(c["sentiment_label"])
    likes = _like_icon(c.get("likes", 0))
    replies = _reply_icon(c.get("replies", 0))
    vtag = _video_tag(c, show_video_tag)

    reply_marker = ""

    translation_block = ""
    if c.get("back_translation") and c.get("original_language"):
        bt = html.escape(c["back_translation"])
        translation_block = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#f0f4ff;'
            f'border-left:3px solid #00BCE7;border-radius:4px;font-size:13px;'
            f'color:#4a5568;font-style:italic;">'
            f'🌐 English: {bt}</div>'
        )

    return f"""
    <div style="display:flex;gap:12px;padding:14px 0;border-bottom:1px solid #f0f0f0;">
      <div style="flex-shrink:0;width:40px;height:40px;border-radius:50%;
                  background:{avatar_bg};display:flex;align-items:center;
                  justify-content:center;color:#fff;font-weight:700;font-size:14px;">
        {initials}
      </div>
      <div style="flex:1;min-width:0;">
        {vtag}
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          {reply_marker}
          <span style="font-weight:600;font-size:13px;color:#030303;">{author}</span>
          <span style="font-size:12px;color:#909090;">{date_str}</span>
          {sentiment}
        </div>
        <div style="margin-top:6px;font-size:14px;color:#030303;line-height:1.5;
                    word-wrap:break-word;">{text}</div>
        {translation_block}
        <div style="margin-top:6px;">{likes}{replies}</div>
      </div>
    </div>
    """


def _sentiment_bar(counts: dict, total: int) -> str:
    if total == 0:
        return ""
    bars = ""
    for label in ["Positive", "Neutral", "Negative"]:
        count = counts.get(label, 0)
        pct = count / total * 100
        color = SENTIMENT_COLORS[label]
        bars += (
            f'<div style="flex:{pct};background:{color};height:24px;'
            f'display:flex;align-items:center;justify-content:center;'
            f'color:#fff;font-size:11px;font-weight:600;'
            f'min-width:{30 if pct > 5 else 0}px;">'
            f'{count} ({pct:.0f}%)</div>'
        )
    return (
        f'<div style="display:flex;border-radius:12px;overflow:hidden;'
        f'margin:12px 0 20px 0;">{bars}</div>'
    )


def build_html_report(
    comments: list[dict], search_query: str, keywords: list[str],
    ai_summary: str = "",
) -> str:
    """Build a complete HTML report grouped by sentiment with AI summary."""
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)
    now = datetime.now(_ET).strftime("%B %d, %Y at %I:%M %p ET")

    kw_display = ", ".join(keywords) if keywords else "None"
    multi_video = len(set(c.get("video_title", "") for c in comments)) > 1

    # AI summary block
    summary_section = ""
    if ai_summary:
        paragraphs = "".join(
            f"<p style='margin-bottom:10px;'>{html.escape(p)}</p>"
            for p in ai_summary.strip().split("\n\n") if p.strip()
        )
        summary_section = f"""
        <div style="background:#e0f7fc;border:1px solid #b3e8f5;border-radius:12px;
                    padding:20px 24px;margin-bottom:32px;">
          <h2 style="margin:0 0 12px 0;font-size:16px;color:#00BCE7;">
            🔍 AI Theme Summary
          </h2>
          <div style="font-size:14px;color:#1a1a1a;line-height:1.6;">
            {paragraphs}
          </div>
        </div>
        """

    # Sentiment sections
    sentiment_sections = ""
    for label in ["Positive", "Neutral", "Negative"]:
        group = [c for c in comments if c["sentiment_label"] == label]
        if not group:
            continue
        emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}[label]
        color = SENTIMENT_COLORS[label]
        cards = "".join(_comment_card(c, show_video_tag=multi_video) for c in group)

        sentiment_sections += f"""
        <div style="margin-bottom:36px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
            <div style="width:6px;height:28px;border-radius:3px;background:{color};"></div>
            <h2 style="margin:0;font-size:18px;color:#1a1a1a;">{emoji} {label}</h2>
            <span style="background:#f3f4f6;color:#6b7280;font-size:12px;
                         padding:2px 10px;border-radius:10px;font-weight:600;">
              {len(group)} comment{"s" if len(group) != 1 else ""}
            </span>
          </div>
          <div style="padding-left:16px;">{cards}</div>
        </div>
        """

    css = (
        "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');"
        "* { margin: 0; padding: 0; box-sizing: border-box; }"
        "body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;"
        "  background: #ffffff; color: #1a1a1a; padding: 40px; max-width: 900px; margin: 0 auto; }"
        "@media print { body { padding: 20px; } }"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{css}</style>
</head>
<body>
  <div style="text-align:center;margin-bottom:36px;">
    <h1 style="font-size:26px;font-weight:700;color:#1a1a1a;margin-bottom:4px;">
      YouTube Comment Analysis
    </h1>
    <p style="font-size:14px;color:#6b7280;">Generated {now}</p>
  </div>

  <div style="background:linear-gradient(135deg,#00BCE7,#C94EFF);border-radius:16px;
              padding:24px 28px;color:#fff;margin-bottom:32px;">
    <div style="display:flex;flex-wrap:wrap;gap:24px;justify-content:space-between;">
      <div>
        <div style="font-size:12px;opacity:0.85;text-transform:uppercase;letter-spacing:1px;">
          Search Query</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px;">
          {html.escape(search_query)}</div>
      </div>
      <div>
        <div style="font-size:12px;opacity:0.85;text-transform:uppercase;letter-spacing:1px;">
          Keywords</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px;">
          {html.escape(kw_display)}</div>
      </div>
      <div>
        <div style="font-size:12px;opacity:0.85;text-transform:uppercase;letter-spacing:1px;">
          Total Comments</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px;">{total}</div>
      </div>
    </div>
  </div>

  {summary_section}

  <h2 style="font-size:18px;margin-bottom:4px;">Overall Sentiment</h2>
  {_sentiment_bar(sentiment_counts, total)}

  {sentiment_sections}

  <div style="text-align:center;padding:24px 0;border-top:1px solid #e5e7eb;
              margin-top:24px;font-size:12px;color:#9ca3af;">
    Built with YouTube Comment Scraper &middot; Sentiment by VADER
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF report via fpdf2
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _safe(text: str) -> str:
    """Sanitise text for fpdf."""
    return text


_SENTIMENT_TAG_COLORS = {
    "POS": ("POSITIVE", (28, 232, 181)),   # mint
    "NEG": ("NEGATIVE", (255, 94, 91)),    # coral
    "NEU": ("NEUTRAL",  (201, 78, 255)),   # purple
}


def _render_markdown_text(pdf: FPDF, text: str, font_size: float = 9, line_height: float = 4.5):
    """Render text with **bold** markdown and - bullet points into the PDF.
    Also converts leading [POS]/[NEG]/[NEU] tags into colored pill badges."""
    import re as _re
    width = pdf.w - 20

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            pdf.ln(line_height)
            continue

        # Handle bullet points
        is_bullet = line.startswith("- ")
        if is_bullet:
            pdf.ln(2)  # extra spacing before bullet
            pdf.set_x(14)
            pdf.set_font("Lato", "", font_size)
            pdf.cell(4, line_height, chr(8226), new_x="END")  # bullet char
            line = line[2:]
            indent_w = width - 8
        else:
            pdf.set_x(10)
            indent_w = width

        # Sentiment tag pill ([POS]/[NEG]/[NEU]) — consume it if present and draw a pill
        _tag_match = _re.match(r"\[(POS|NEG|NEU)\]\s*", line)
        if _tag_match:
            tag = _tag_match.group(1)
            label, (tr, tg, tb) = _SENTIMENT_TAG_COLORS[tag]
            pill_w = 16
            pill_h = 3.8
            x_pill = pdf.get_x()
            y_pill = pdf.get_y() + 0.5
            pdf.set_fill_color(tr, tg, tb)
            pdf.rect(x_pill, y_pill, pill_w, pill_h, "F")
            pdf.set_font("Lato", "B", 6.5)
            pdf.set_text_color(255, 255, 255)
            pdf.set_xy(x_pill, y_pill - 0.4)
            pdf.cell(pill_w, pill_h + 0.8, label, align="C")
            pdf.set_xy(x_pill + pill_w + 2, y_pill - 0.5)
            pdf.set_text_color(26, 26, 26)
            pdf.set_font("Lato", "", font_size)
            line = line[_tag_match.end():]

        # Split by formatting markers: **bold**, *italic*, <u>underline</u>
        parts = _re.split(r"(\*\*.*?\*\*|\*.*?\*|<u>.*?</u>)", line)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                pdf.set_font("Lato", "B", font_size)
                pdf.write(line_height, part[2:-2])
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                pdf.set_font("Lato", "I", font_size)
                pdf.write(line_height, part[1:-1])
            elif part.startswith("<u>") and part.endswith("</u>"):
                pdf.set_font("Lato", "", font_size)
                inner = part[3:-4]
                # Draw underline manually
                x_before = pdf.get_x()
                pdf.write(line_height, inner)
                x_after = pdf.get_x()
                y_line = pdf.get_y() + line_height - 0.5
                pdf.set_draw_color(26, 26, 26)
                pdf.line(x_before, y_line, x_after, y_line)
            else:
                pdf.set_font("Lato", "", font_size)
                pdf.write(line_height, part)
        pdf.ln(line_height)


import os as _os
_FONT_DIR = _os.path.join(_os.path.dirname(__file__), "fonts")


class _ReportPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Lato", "", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def build_pdf_report(
    comments: list[dict], search_query: str, keywords: list[str],
    ai_summary: str = "", preset_name: str = "",
    multi_sections: list[dict] | None = None,
    thumbnail_video_id: str | None = None,
) -> bytes:
    """Build a styled PDF report grouped by sentiment.

    multi_sections: if provided, list of {"name", "comments", "ai_summary",
    "one_liner"} dicts for rendering multiple analysis sections (e.g.
    Subtitles + Dubbing). When multi_sections is set, the overall sentiment
    bar is omitted in favor of per-section bars.
    thumbnail_video_id: YouTube video ID to fetch and embed as a header image.
    """
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)
    now = datetime.now(_ET).strftime("%B %d, %Y at %I:%M %p ET")
    multi_video = len(set(c.get("video_title", "") for c in comments)) > 1

    # Determine keyword display: preset name or keyword list
    if preset_name and preset_name != "Custom":
        kw_display = f"Preset: {preset_name}"
    else:
        kw_display = ", ".join(keywords) if keywords else "None"

    # Video title for the main heading
    video_titles = sorted(set(c.get("video_title", "") for c in comments if c.get("video_title")))
    if len(video_titles) == 1:
        main_title = video_titles[0]
    elif video_titles:
        main_title = f"{video_titles[0]} + {len(video_titles) - 1} more"
    else:
        main_title = search_query

    pdf = _ReportPDF()
    # Register Lato font
    pdf.add_font("Lato", "", _os.path.join(_FONT_DIR, "Lato-Regular.ttf"))
    pdf.add_font("Lato", "B", _os.path.join(_FONT_DIR, "Lato-Bold.ttf"))
    pdf.add_font("Lato", "I", _os.path.join(_FONT_DIR, "Lato-Italic.ttf"))
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ---- Optional thumbnail at top ----
    if thumbnail_video_id:
        _thumb_bytes = _fetch_thumbnail_bytes(thumbnail_video_id)
        if _thumb_bytes:
            try:
                _thumb_h = 45  # mm
                _thumb_w = _thumb_h * 16 / 9
                _x_center = (pdf.w - _thumb_w) / 2
                pdf.image(io.BytesIO(_thumb_bytes), x=_x_center,
                          y=pdf.get_y(), w=_thumb_w, h=_thumb_h)
                pdf.set_y(pdf.get_y() + _thumb_h + 4)
            except Exception:
                pass

    # ---- Title: video name ----
    pdf.set_font("Lato", "B", 20)
    pdf.set_text_color(26, 26, 26)
    pdf.multi_cell(pdf.w - 20, 10, _safe(main_title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Lato", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(0, 6, f"YouTube Comment Analysis  |  Generated {now}", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ---- Divider line 1 (under title) ----
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
    pdf.ln(6)

    # ---- Summary block ----
    if multi_sections:
        # Rounded overall-summary box: sentiment bar + two-column one-liners
        _draw_overall_summary_box(pdf, sentiment_counts, total, multi_sections)
    else:
        # Plain-text summary for single-analysis exports
        pdf.set_font("Lato", "", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 5, "KEYWORDS", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Lato", "B", 11)
        pdf.set_text_color(26, 26, 26)
        pdf.multi_cell(pdf.w - 20, 6, _safe(kw_display), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Lato", "", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(30, 5, "TOTAL COMMENTS", new_x="END")
        pdf.set_font("Lato", "B", 11)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(0, 5, f"  {total}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

    # ---- Overall sentiment (single-analysis only; multi_sections draws per-section bars) ----
    if not multi_sections:
        pdf.set_font("Lato", "B", 13)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(0, 8, "Overall Sentiment", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        _draw_sentiment_bar(pdf, sentiment_counts, total)
        bar_w = pdf.w - 20
        x0 = 10
        pdf.set_font("Lato", "", 7)
        for lbl in ["Positive", "Neutral", "Negative"]:
            count = sentiment_counts.get(lbl, 0)
            pct = count / total if total else 0
            seg_w = bar_w * pct
            if seg_w > 10:
                sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[lbl])
                pdf.set_text_color(sr, sg, sb)
                pdf.set_x(x0)
                pdf.cell(seg_w, 5, lbl, align="C", new_x="END")
            x0 += seg_w
        pdf.ln(8)

    # ---- Determine sections to render ----
    if multi_sections:
        sections_to_render = multi_sections
    else:
        sections_to_render = [{"name": None, "comments": comments, "ai_summary": ai_summary}]

    for sec_idx, section in enumerate(sections_to_render):
        sec_comments = section["comments"]
        sec_summary = section.get("ai_summary", "")
        sec_name = section.get("name")

        if not sec_comments:
            continue

        # Section header for multi-analysis
        if sec_name:
            if sec_idx > 0:
                pdf.add_page()
            pdf.set_font("Lato", "B", 16)
            pdf.set_text_color(26, 26, 26)
            r_a, g_a, b_a = _hex_to_rgb("#00BCE7")
            pdf.set_fill_color(r_a, g_a, b_a)
            pdf.rect(10, pdf.get_y(), 4, 10, "F")
            pdf.set_x(16)
            pdf.cell(0, 10, _safe(sec_name), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            # One-line summary (if provided)
            _one_liner = section.get("one_liner", "")
            if _one_liner:
                pdf.set_font("Lato", "I", 10)
                pdf.set_text_color(75, 85, 99)
                pdf.multi_cell(pdf.w - 20, 5, _safe(_one_liner),
                               new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            # Section sentiment bar
            sec_sc = get_sentiment_counts(sec_comments)
            sec_total = len(sec_comments)
            _draw_sentiment_bar(pdf, sec_sc, sec_total)
            bar_w = pdf.w - 20
            x0 = 10
            pdf.set_font("Lato", "", 7)
            for lbl in ["Positive", "Neutral", "Negative"]:
                cnt = sec_sc.get(lbl, 0)
                pct = cnt / sec_total if sec_total else 0
                seg_w = bar_w * pct
                if seg_w > 10:
                    sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[lbl])
                    pdf.set_text_color(sr, sg, sb)
                    pdf.set_x(x0)
                    pdf.cell(seg_w, 5, lbl, align="C", new_x="END")
                x0 += seg_w
            pdf.ln(6)

        # AI Summary for this section
        if sec_summary:
            pdf.ln(2)
            pdf.set_font("Lato", "B", 13)
            pdf.set_text_color(26, 26, 26)
            pdf.cell(0, 8, "Summary", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            pdf.set_text_color(26, 26, 26)
            _render_markdown_text(pdf, sec_summary)
            pdf.ln(4)

        # Divider
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(8)

        # Sentiment-grouped comments for this section, with theme sub-groups
        _sent_rank = {"Positive": 2, "Neutral": 1, "Negative": 0}
        for label in ["Positive", "Neutral", "Negative"]:
            group = [c for c in sec_comments if c["sentiment_label"] == label]
            if not group:
                continue

            emoji_text = {"Positive": "(+)", "Negative": "(-)", "Neutral": "(~)"}[label]
            color = SENTIMENT_COLORS[label]

            if pdf.get_y() > pdf.h - 50:
                pdf.add_page()
            r, g, b = _hex_to_rgb(color)
            pdf.set_fill_color(r, g, b)
            pdf.rect(10, pdf.get_y(), 4, 8, "F")
            pdf.set_x(16)
            pdf.set_font("Lato", "B", 13)
            pdf.set_text_color(26, 26, 26)
            pdf.cell(0, 8, f"{emoji_text} {label}  ({len(group)} comments)",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)

            # Cluster by theme within the sentiment group. Themes sorted by
            # size desc; within each theme, comments sorted by likes desc (ties
            # broken by positive sentiment rank).
            theme_buckets: dict[str, list[dict]] = {}
            for _c in group:
                theme_buckets.setdefault(_c.get("theme", "General"), []).append(_c)
            ordered_themes = sorted(
                theme_buckets.keys(),
                key=lambda t: (-len(theme_buckets[t]), t),
            )
            for theme_name in ordered_themes:
                theme_cs = theme_buckets[theme_name]
                theme_cs.sort(
                    key=lambda c: (
                        c.get("likes", 0),
                        _sent_rank.get(c.get("sentiment_label"), 0),
                    ),
                    reverse=True,
                )
                if pdf.get_y() > pdf.h - 30:
                    pdf.add_page()
                pdf.set_x(14)
                pdf.set_font("Lato", "B", 9)
                pdf.set_text_color(107, 114, 128)
                pdf.cell(0, 5, _safe(f"{theme_name.upper()} · {len(theme_cs)}"),
                         new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
                for c in theme_cs:
                    _draw_comment(pdf, c, show_video_tag=multi_video)

            pdf.ln(6)

    # ---- Footer text ----
    pdf.set_font("Lato", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Sentiment by VADER  |  Themes by TF-IDF + KMeans",
             align="C", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def _draw_overall_summary_box(pdf: FPDF, counts: dict, total: int,
                               sections: list[dict]):
    """Draw the rounded-edge overall-summary box on the first PDF page.
    Includes the overall sentiment bar plus two-column section one-liners."""
    margin = 10
    padding = 6
    box_x = margin
    box_w = pdf.w - 2 * margin

    # Pre-measure content height so we can draw the box first
    label_h = 5
    bar_h = 7
    bar_lbl_h = 5
    oneliner_max_lines = 3

    # Section one-liners — figure out the tallest column
    col_gap = 6
    col_w = (box_w - 2 * padding - col_gap) / max(1, min(2, len(sections))) \
        if sections else box_w - 2 * padding
    pdf.set_font("Lato", "I", 10)
    oneliner_heights = []
    for s in sections[:2]:
        _text = s.get("one_liner") or "—"
        _lines = pdf.multi_cell(col_w, 4.8, _safe(_text), split_only=True)
        oneliner_heights.append(max(1, min(oneliner_max_lines, len(_lines))) * 4.8)
    oneliner_h = max(oneliner_heights) if oneliner_heights else 0
    section_header_h = 5

    box_h = padding + label_h + bar_h + 2 + bar_lbl_h + 6 + \
        section_header_h + oneliner_h + padding

    box_y = pdf.get_y()
    # Draw the rounded rectangle (fpdf2 supports round_corners)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_fill_color(249, 250, 251)
    pdf.set_line_width(0.25)
    try:
        pdf.rect(box_x, box_y, box_w, box_h, "DF",
                 round_corners=True, corner_radius=3)
    except TypeError:
        pdf.rect(box_x, box_y, box_w, box_h, "DF")

    # Header label
    pdf.set_xy(box_x + padding, box_y + padding)
    pdf.set_font("Lato", "", 8)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(0, label_h, "OVERALL SENTIMENT", new_x="LMARGIN", new_y="NEXT")

    # Sentiment bar (inset to box width)
    pdf.set_x(box_x + padding)
    _bar_y = pdf.get_y() + 1
    _bar_w = box_w - 2 * padding
    _x = box_x + padding
    if total > 0:
        for label in ["Positive", "Neutral", "Negative"]:
            count = counts.get(label, 0)
            pct = count / total
            seg_w = _bar_w * pct
            if seg_w < 1:
                continue
            r, g, b = _hex_to_rgb(SENTIMENT_COLORS[label])
            pdf.set_fill_color(r, g, b)
            pdf.rect(_x, _bar_y, seg_w, bar_h, "F")
            if seg_w > 22:
                pdf.set_xy(_x, _bar_y)
                pdf.set_font("Lato", "B", 7)
                if label == "Positive":
                    pdf.set_text_color(26, 26, 26)
                else:
                    pdf.set_text_color(255, 255, 255)
                pdf.cell(seg_w, bar_h, f"{count} ({pct:.0%})", align="C")
            _x += seg_w
    pdf.set_y(_bar_y + bar_h + 1)

    # Sentiment labels under bar
    _lbl_y = pdf.get_y()
    _x = box_x + padding
    pdf.set_font("Lato", "", 7)
    for lbl in ["Positive", "Neutral", "Negative"]:
        count = counts.get(lbl, 0)
        pct = count / total if total else 0
        seg_w = _bar_w * pct
        if seg_w > 15:
            sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[lbl])
            pdf.set_text_color(sr, sg, sb)
            pdf.set_xy(_x, _lbl_y)
            pdf.cell(seg_w, bar_lbl_h, lbl, align="C")
        _x += seg_w
    pdf.set_y(_lbl_y + bar_lbl_h + 4)

    # Two-column section one-liners
    _cols_y = pdf.get_y()
    for i, s in enumerate(sections[:2]):
        col_x = box_x + padding + i * (col_w + col_gap)
        pdf.set_xy(col_x, _cols_y)
        pdf.set_font("Lato", "B", 10)
        pdf.set_text_color(0, 188, 231)  # cyan
        pdf.cell(col_w, section_header_h, _safe(s.get("name", "")),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_xy(col_x, pdf.get_y())
        pdf.set_font("Lato", "I", 10)
        pdf.set_text_color(55, 65, 81)
        _text = s.get("one_liner") or "—"
        pdf.multi_cell(col_w, 4.8, _safe(_text), new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(box_y + box_h + 6)


def _draw_sentiment_bar(pdf: FPDF, counts: dict, total: int):
    if total == 0:
        return
    bar_w = pdf.w - 20
    bar_h = 7
    x0 = 10
    y0 = pdf.get_y()

    for label in ["Positive", "Neutral", "Negative"]:
        count = counts.get(label, 0)
        pct = count / total
        seg_w = bar_w * pct
        if seg_w < 1:
            continue
        r, g, b = _hex_to_rgb(SENTIMENT_COLORS[label])
        pdf.set_fill_color(r, g, b)
        pdf.rect(x0, y0, seg_w, bar_h, "F")
        if seg_w > 20:
            pdf.set_xy(x0, y0)
            pdf.set_font("Lato", "B", 7)
            if label == "Positive":
                pdf.set_text_color(26, 26, 26)
            else:
                pdf.set_text_color(255, 255, 255)
            pdf.cell(seg_w, bar_h, f"{count} ({pct:.0%})", align="C")
        x0 += seg_w

    pdf.set_y(y0 + bar_h)


def _draw_comment(pdf: FPDF, c: dict, show_video_tag: bool = False):
    """Draw a single comment card in the PDF."""
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()

    # Video title tag
    if show_video_tag and c.get("video_title"):
        pdf.set_x(14)
        pdf.set_font("Lato", "", 7)
        pdf.set_fill_color(243, 244, 246)
        pdf.set_text_color(74, 85, 104)
        tag_text = f"  {_safe(c['video_title'][:60])}  "
        tag_w = pdf.get_string_width(tag_text) + 4
        pdf.cell(tag_w, 5, tag_text, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    x_start = 14
    y_start = pdf.get_y()

    # Avatar circle
    avatar_color = _avatar_color(c["author"])
    r, g, b = _hex_to_rgb(avatar_color)
    pdf.set_fill_color(r, g, b)
    avatar_size = 10
    cx, cy = x_start + avatar_size / 2, y_start + avatar_size / 2
    pdf.ellipse(cx - avatar_size / 2, cy - avatar_size / 2, avatar_size, avatar_size, "F")
    initials = _initials(c["author"])
    pdf.set_xy(cx - avatar_size / 2, cy - 2.5)
    pdf.set_font("Lato", "B", 7)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(avatar_size, 5, _safe(initials), align="C")

    # Author + date + sentiment
    content_x = x_start + avatar_size + 4
    pdf.set_xy(content_x, y_start)

    pdf.set_font("Lato", "B", 9)
    pdf.set_text_color(3, 3, 3)
    pdf.cell(0, 5, _safe(c["author"]), new_x="END")

    pdf.set_font("Lato", "", 7)
    pdf.set_text_color(144, 144, 144)
    date_str = _format_date(c["date"])
    pdf.cell(0, 5, f"   {date_str}", new_x="END")

    # Sentiment badge — colored rounded rect
    label = c["sentiment_label"]
    badge_icon = {"Positive": "+", "Negative": "-", "Neutral": "~"}[label]
    sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[label])
    badge_x = pdf.get_x()
    badge_y = pdf.get_y()
    badge_text = f" {badge_icon} {label} "
    pdf.set_font("Lato", "B", 7)
    badge_w = pdf.get_string_width(badge_text) + 4
    pdf.set_fill_color(sr, sg, sb)
    pdf.rect(badge_x + 3, badge_y + 0.5, badge_w, 4, "F")
    pdf.set_xy(badge_x + 3, badge_y)
    if label == "Positive":
        pdf.set_text_color(26, 26, 26)
    else:
        pdf.set_text_color(255, 255, 255)
    pdf.cell(badge_w, 5, badge_text, new_x="END")

    # Language tag (next to sentiment badge)
    lang_code = c.get("matched_language", "en")
    if lang_code not in ("en", "all"):
        from config import LANGUAGE_NAMES as _LN
        lang_label = _LN.get(lang_code, lang_code)
        pdf.set_font("Lato", "", 7)
        pdf.set_fill_color(224, 247, 252)
        pdf.set_text_color(0, 188, 231)
        lt = f"  {_safe(lang_label)}  "
        lt_w = pdf.get_string_width(lt) + 4
        pdf.cell(2, 5, "")  # spacer
        pdf.cell(lt_w, 5, lt, fill=True, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.ln(5)

    # Comment text
    pdf.set_x(content_x)
    pdf.set_font("Lato", "", 9)
    pdf.set_text_color(3, 3, 3)
    comment_text = _safe(c["comment"])
    text_w = pdf.w - content_x - 10
    pdf.multi_cell(text_w, 4.5, comment_text, new_x="LMARGIN", new_y="NEXT")

    # Back-translation
    if c.get("back_translation") and c.get("original_language"):
        pdf.set_x(content_x)
        pdf.set_font("Lato", "I", 8)
        pdf.set_text_color(0, 188, 231)
        bt = _safe(c["back_translation"])
        pdf.multi_cell(text_w, 4, f"EN: {bt}", new_x="LMARGIN", new_y="NEXT")

    # Likes / replies
    meta_parts = []
    if c.get("likes", 0) > 0:
        meta_parts.append(f"Likes: {c['likes']}")
    if c.get("replies", 0) > 0:
        meta_parts.append(f"Replies: {c['replies']}")
    if meta_parts:
        pdf.set_x(content_x)
        pdf.set_font("Lato", "", 7)
        pdf.set_text_color(96, 96, 96)
        pdf.cell(0, 4, "  |  ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")

    # Separator line
    pdf.ln(3)
    pdf.set_draw_color(230, 230, 230)
    pdf.line(content_x, pdf.get_y(), pdf.w - 10, pdf.get_y())
    pdf.ln(4)


def build_interactive_html_report(
    search_query: str,
    sections: list[dict],
    keywords: list[str] | None = None,
    thumbnail_video_id: str | None = None,
    main_title: str | None = None,
) -> str:
    """Build a self-contained interactive HTML report.

    sections: list of {"name", "comments", "ai_summary", "one_liner"}.
    Returns a single HTML string with all data embedded as JSON — no network
    calls required except for the YouTube thumbnail.
    """
    now = datetime.now(_ET).strftime("%B %d, %Y at %I:%M %p ET")

    # Title: derive from sections' video titles if not supplied
    if not main_title:
        all_vt = sorted({c.get("video_title", "") for s in sections for c in s.get("comments", []) if c.get("video_title")})
        if len(all_vt) == 1:
            main_title = all_vt[0]
        elif all_vt:
            main_title = f"{all_vt[0]} + {len(all_vt) - 1} more"
        else:
            main_title = search_query or "YouTube Comment Analysis"

    # Overall totals across all sections
    total_comments = sum(len(s.get("comments", [])) for s in sections)

    # Build the data payload (stripped down — only fields the UI needs)
    payload_sections = []
    for s in sections:
        payload_comments = []
        for c in s.get("comments", []):
            payload_comments.append({
                "id": c.get("_id"),
                "author": c.get("author", ""),
                "comment": c.get("comment", ""),
                "back_translation": c.get("back_translation", ""),
                "original_language": c.get("original_language", ""),
                "matched_language": c.get("matched_language", "en"),
                "likes": c.get("likes", 0),
                "replies": c.get("replies", 0),
                "date": c.get("date", ""),
                "sentiment_label": c.get("sentiment_label", "Neutral"),
                "sentiment_score": c.get("sentiment_score", 0),
                "theme": c.get("theme", "General"),
                "video_id": c.get("video_id", ""),
                "video_title": c.get("video_title", ""),
            })
        payload_sections.append({
            "name": s.get("name", ""),
            "one_liner": s.get("one_liner", ""),
            "ai_summary": s.get("ai_summary", ""),
            "comments": payload_comments,
        })

    thumbnail_url = (
        f"https://img.youtube.com/vi/{thumbnail_video_id}/hqdefault.jpg"
        if thumbnail_video_id else ""
    )

    payload = {
        "title": main_title,
        "search_query": search_query or "",
        "keywords": keywords or [],
        "thumbnail_url": thumbnail_url,
        "generated_at": now,
        "total_comments": total_comments,
        "sentiment_colors": SENTIMENT_COLORS,
        "sections": payload_sections,
    }
    # Serialize data: escape </script> sequences so the JSON is safe inside
    # a <script type="application/json"> block.
    data_json = _json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return _HTML_TEMPLATE.format(
        title=html.escape(main_title),
        data_json=data_json,
    )


# The interactive HTML template. Uses f-style format substitution for {title}
# and {data_json} only — all literal braces inside JS/CSS are doubled.
_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Comment Analysis</title>
<style>
:root {{
  --cyan: #00BCE7;
  --pink: #E64783;
  --mint: #1CE8B5;
  --purple: #C94EFF;
  --yellow: #FFD93D;
  --coral: #FF5E5B;
  --text: #0f172a;
  --muted: #6b7280;
  --border: #e5e7eb;
  --bg: #ffffff;
  --card-bg: #ffffff;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.45;
}}
body {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
.rainbow {{ display: flex; height: 3px; overflow: hidden; margin: 12px 0 20px; }}
.rainbow > div {{ flex: 1; }}
.rainbow > div:nth-child(1) {{ background: #00BCE7; }}
.rainbow > div:nth-child(2) {{ background: #E64783; }}
.rainbow > div:nth-child(3) {{ background: #1CE8B5; }}
.rainbow > div:nth-child(4) {{ background: #C94EFF; }}
.rainbow > div:nth-child(5) {{ background: #FFD93D; }}
.rainbow > div:nth-child(6) {{ background: #FF5E5B; }}
.rainbow > div:nth-child(7) {{ background: #CCF913; }}
.rainbow > div:nth-child(8) {{ background: #FF9500; }}
header {{ display: flex; gap: 20px; align-items: center; margin-bottom: 4px; }}
header img {{ height: 96px; width: auto; border-radius: 8px; object-fit: cover; flex-shrink: 0; }}
header h1 {{ font-size: 28px; font-weight: 700; margin: 0; line-height: 1.15; }}
.meta {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
.tabs {{ display: flex; gap: 4px; border-bottom: 2px solid var(--border); margin: 16px 0 20px; }}
.tab-btn {{
  padding: 10px 20px; background: none; border: none; border-bottom: 3px solid transparent;
  font-size: 15px; font-weight: 600; cursor: pointer; color: var(--muted);
  margin-bottom: -2px; transition: all 0.15s ease;
}}
.tab-btn.active {{ color: var(--cyan); border-bottom-color: var(--cyan); }}
.tab-btn:hover:not(.active) {{ color: var(--text); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.one-liner {{
  font-style: italic; color: #4b5563; font-size: 15px;
  padding: 10px 14px; background: #f9fafb; border-left: 3px solid var(--cyan);
  border-radius: 4px; margin-bottom: 16px;
}}
.ai-summary {{
  background: #f0fcff; border: 1px solid #b3e8f5; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 18px; font-size: 14px;
}}
.ai-summary p {{ margin: 0 0 8px 0; }}
.ai-summary ul {{ margin: 4px 0 0 18px; }}
.ai-summary li {{ margin-bottom: 6px; }}
.sent-tag {{
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 700; letter-spacing: 0.4px; margin-right: 6px;
  vertical-align: middle;
}}
.sent-tag.pos {{ background: #1CE8B5; color: #033d33; }}
.sent-tag.neg {{ background: #FF5E5B; color: #5a1111; }}
.sent-tag.neu {{ background: #C94EFF; color: #2e0b3d; }}
.sent-bar {{ display: flex; height: 10px; border-radius: 5px; overflow: hidden; margin-bottom: 14px; }}
.sent-bar > div {{ display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 10px; font-weight: 700; }}
.filters {{
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  padding: 12px; background: #f9fafb; border-radius: 8px;
  margin-bottom: 14px; font-size: 13px;
}}
.filters input[type="text"], .filters input[type="number"], .filters select {{
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 13px; font-family: inherit;
}}
.filters input[type="text"] {{ flex: 1; min-width: 180px; }}
.filter-group {{ display: flex; align-items: center; gap: 6px; }}
.filter-group label {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
.pill-toggle {{
  padding: 4px 12px; border-radius: 16px; border: 2px solid; cursor: pointer;
  font-size: 12px; font-weight: 600; background: #fff; user-select: none;
  transition: all 0.15s ease;
}}
.pill-toggle.active {{ color: #fff; }}
.pill-toggle.Positive.active {{ background: #1CE8B5; border-color: #1CE8B5; color: #033d33; }}
.pill-toggle.Positive {{ border-color: #1CE8B5; color: #1CE8B5; }}
.pill-toggle.Negative.active {{ background: #FF5E5B; border-color: #FF5E5B; color: #fff; }}
.pill-toggle.Negative {{ border-color: #FF5E5B; color: #FF5E5B; }}
.pill-toggle.Neutral.active {{ background: #C94EFF; border-color: #C94EFF; color: #fff; }}
.pill-toggle.Neutral {{ border-color: #C94EFF; color: #C94EFF; }}
.empty {{ color: var(--muted); padding: 20px; text-align: center; font-style: italic; }}
.card {{
  display: flex; gap: 10px; padding: 10px 0;
  border-bottom: 1px solid #f3f4f6;
}}
.card .avatar {{
  width: 30px; height: 30px; border-radius: 50%; background: var(--cyan);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 11px; flex-shrink: 0;
}}
.card .body {{ flex: 1; min-width: 0; }}
.card .row1 {{
  display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 12px;
}}
.card .author {{ font-weight: 600; color: #030303; }}
.card .date, .card .likes {{ color: #909090; font-size: 11px; }}
.badge {{
  display: inline-block; padding: 1px 6px; border-radius: 4px;
  font-size: 10px; font-weight: 600; color: #fff;
}}
.badge.Positive {{ background: #1CE8B5; color: #033d33; }}
.badge.Negative {{ background: #FF5E5B; }}
.badge.Neutral {{ background: #C94EFF; }}
.card .text {{ margin-top: 3px; font-size: 13px; color: #0f172a; line-height: 1.4; }}
.card .translation {{
  margin-top: 4px; padding: 4px 8px; background: #f0f4ff;
  border-left: 2px solid var(--cyan); border-radius: 3px;
  font-size: 12px; color: #4a5568; font-style: italic;
}}
.lang-pill {{
  padding: 1px 6px; border-radius: 4px; font-size: 10px;
  font-weight: 500; color: var(--cyan); background: #e0f7fc;
}}
.section-header {{ margin: 18px 0 8px; font-size: 14px; font-weight: 700; }}
.theme-sub {{
  margin: 14px 0 6px; padding: 4px 0; border-top: 1px solid #e5e7eb;
  font-size: 11px; font-weight: 700; color: #6b7280; letter-spacing: 0.5px;
  text-transform: uppercase;
}}
.controls-row {{ display: flex; gap: 16px; margin-bottom: 14px; font-size: 13px; color: var(--muted); }}
.count-summary {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; }}
.no-results {{ padding: 30px; text-align: center; color: var(--muted); font-style: italic; }}
</style>
</head>
<body>
<header id="hdr"></header>
<div class="rainbow">
  <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
</div>
<div class="meta" id="meta"></div>

<div class="tabs" id="tabs"></div>
<div id="panels"></div>

<script id="report-data" type="application/json">{data_json}</script>
<script>
(function() {{
  const DATA = JSON.parse(document.getElementById('report-data').textContent);
  const LANG_NAMES = {{
    en: 'English', es: 'Spanish', fr: 'French', de: 'German', pt: 'Portuguese',
    it: 'Italian', ja: 'Japanese', ko: 'Korean', 'zh-CN': 'Chinese', hi: 'Hindi',
    ar: 'Arabic', ru: 'Russian', tr: 'Turkish', th: 'Thai', vi: 'Vietnamese',
    id: 'Indonesian', pl: 'Polish', nl: 'Dutch', sv: 'Swedish', he: 'Hebrew',
  }};
  function langName(code) {{ return LANG_NAMES[code] || code || 'Unknown'; }}
  function escapeHTML(s) {{
    return String(s || '').replace(/[&<>\"']/g, c =>
      ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
  }}
  function initials(name) {{
    const parts = String(name || '?').replace(/^@/, '').split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    return (parts[0][0] + (parts[1] ? parts[1][0] : '')).toUpperCase();
  }}
  function avatarColor(name) {{
    const palette = ['#00BCE7','#E64783','#1CE8B5','#C94EFF','#FFD93D','#FF5E5B','#CCF913','#FF9500'];
    let h = 0; for (const ch of name || '') h = (h * 31 + ch.charCodeAt(0)) | 0;
    return palette[Math.abs(h) % palette.length];
  }}
  function formatDate(iso) {{
    if (!iso) return '';
    const d = new Date(iso); if (isNaN(d)) return '';
    const now = new Date();
    const days = Math.floor((now - d) / 86400000);
    if (days === 0) return 'today';
    if (days === 1) return 'yesterday';
    if (days < 7) return days + ' days ago';
    if (days < 30) return Math.floor(days / 7) + 'w ago';
    if (days < 365) return Math.floor(days / 30) + 'mo ago';
    return Math.floor(days / 365) + 'y ago';
  }}
  function renderAISummary(md) {{
    if (!md) return '';
    // Convert [POS]/[NEG]/[NEU] tags to pills
    md = md.replace(/\[(POS|NEG|NEU)\]/g, (_, t) => {{
      const label = {{POS:'POSITIVE', NEG:'NEGATIVE', NEU:'NEUTRAL'}}[t];
      const cls = {{POS:'pos', NEG:'neg', NEU:'neu'}}[t];
      return '<span class="sent-tag ' + cls + '">' + label + '</span>';
    }});
    const lines = md.split('\n');
    let html = '', inUL = false;
    for (const line of lines) {{
      const trimmed = line.trim();
      if (trimmed.startsWith('- ')) {{
        if (!inUL) {{ html += '<ul>'; inUL = true; }}
        html += '<li>' + inlineFmt(trimmed.slice(2)) + '</li>';
      }} else {{
        if (inUL) {{ html += '</ul>'; inUL = false; }}
        if (trimmed) html += '<p>' + inlineFmt(trimmed) + '</p>';
      }}
    }}
    if (inUL) html += '</ul>';
    return html;
  }}
  function inlineFmt(s) {{
    // Preserve sentiment pills as already-emitted HTML (they have < and >).
    // Use tokenization to protect them during bold/italic replacement.
    const tokens = []; let idx = 0;
    s = s.replace(/<span class="sent-tag[^"]*">[^<]*<\/span>/g, m => {{
      tokens.push(m); return '' + (idx++) + '';
    }});
    s = escapeHTML(s);
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*]+)\*([^*]|$)/g, '$1<em>$2</em>$3');
    s = s.replace(/(\d+)/g, (_, i) => tokens[+i]);
    return s;
  }}
  function sentimentBar(counts) {{
    const total = counts.Positive + counts.Negative + counts.Neutral;
    if (!total) return '';
    const bits = [];
    for (const lbl of ['Positive', 'Neutral', 'Negative']) {{
      const n = counts[lbl] || 0;
      if (!n) continue;
      const pct = (n / total * 100).toFixed(1);
      const color = DATA.sentiment_colors[lbl];
      bits.push('<div style="width:' + pct + '%;background:' + color + ';">' +
                (pct >= 8 ? n + ' · ' + pct + '%' : '') + '</div>');
    }}
    return '<div class="sent-bar">' + bits.join('') + '</div>';
  }}
  function countSentiments(comments) {{
    const c = {{Positive: 0, Negative: 0, Neutral: 0}};
    for (const x of comments) c[x.sentiment_label]++;
    return c;
  }}
  function renderCard(c) {{
    const ini = initials(c.author);
    const bg = avatarColor(c.author);
    const dateStr = formatDate(c.date);
    const langPill = c.matched_language && !['en','all'].includes(c.matched_language)
      ? '<span class="lang-pill">' + langName(c.matched_language) + '</span>' : '';
    const likes = c.likes > 0 ? '<span class="likes">👍 ' + c.likes + '</span>' : '';
    const translation = c.back_translation && c.back_translation !== c.comment
      ? '<div class="translation">🌐 ' + escapeHTML(c.back_translation) + '</div>' : '';
    return '<div class="card" data-id="' + c.id + '">' +
      '<div class="avatar" style="background:' + bg + ';">' + ini + '</div>' +
      '<div class="body">' +
        '<div class="row1">' +
          '<span class="author">' + escapeHTML(c.author) + '</span>' +
          '<span class="date">' + dateStr + '</span>' +
          '<span class="badge ' + c.sentiment_label + '">' + c.sentiment_label + '</span>' +
          langPill + likes +
        '</div>' +
        '<div class="text">' + escapeHTML(c.comment) + '</div>' +
        translation +
      '</div>' +
    '</div>';
  }}

  // ----- Header -----
  const hdr = document.getElementById('hdr');
  const thumb = DATA.thumbnail_url
    ? '<img src="' + DATA.thumbnail_url + '" alt="">' : '';
  hdr.innerHTML = thumb + '<h1>' + escapeHTML(DATA.title) + '</h1>';
  document.getElementById('meta').textContent =
    'Generated ' + DATA.generated_at + ' · ' + DATA.total_comments.toLocaleString() + ' total comments';

  // ----- Tabs -----
  const tabsEl = document.getElementById('tabs');
  const panelsEl = document.getElementById('panels');
  DATA.sections.forEach((sec, i) => {{
    const btn = document.createElement('button');
    btn.className = 'tab-btn' + (i === 0 ? ' active' : '');
    btn.dataset.tab = i;
    btn.textContent = sec.name + ' (' + sec.comments.length.toLocaleString() + ')';
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + i).classList.add('active');
    }});
    tabsEl.appendChild(btn);

    const panel = document.createElement('section');
    panel.id = 'panel-' + i;
    panel.className = 'tab-content' + (i === 0 ? ' active' : '');
    panelsEl.appendChild(panel);
    renderPanel(panel, sec, i);
  }});

  function renderPanel(panel, sec, i) {{
    const counts = countSentiments(sec.comments);
    const langs = [...new Set(sec.comments.map(c => c.matched_language || 'en'))].sort();
    const langOptions = ['<option value="">All languages</option>']
      .concat(langs.map(l => '<option value="' + l + '">' + langName(l) + '</option>'))
      .join('');

    const oneLinerHTML = sec.one_liner
      ? '<div class="one-liner">' + escapeHTML(sec.one_liner) + '</div>' : '';
    const aiSummaryHTML = sec.ai_summary
      ? '<div class="ai-summary">' + renderAISummary(sec.ai_summary) + '</div>' : '';

    panel.innerHTML =
      oneLinerHTML + aiSummaryHTML + sentimentBar(counts) +
      '<div class="filters">' +
        '<input type="text" class="f-search" placeholder="Search within comments…">' +
        '<div class="filter-group"><label>Lang</label>' +
          '<select class="f-lang">' + langOptions + '</select>' +
        '</div>' +
        '<div class="filter-group"><label>Min likes</label>' +
          '<input type="number" class="f-likes" value="0" min="0" style="width:64px;">' +
        '</div>' +
        '<div class="filter-group"><label>Sort</label>' +
          '<select class="f-sort">' +
            '<option value="likes-desc" selected>Likes (most)</option>' +
            '<option value="likes-asc">Likes (fewest)</option>' +
            '<option value="date-desc">Date (newest)</option>' +
            '<option value="date-asc">Date (oldest)</option>' +
          '</select>' +
        '</div>' +
        '<div class="filter-group">' +
          '<span class="pill-toggle Positive active" data-s="Positive">Positive</span>' +
          '<span class="pill-toggle Neutral active" data-s="Neutral">Neutral</span>' +
          '<span class="pill-toggle Negative active" data-s="Negative">Negative</span>' +
        '</div>' +
      '</div>' +
      '<div class="count-summary"></div>' +
      '<div class="comments-host"></div>';

    const state = {{
      sentiments: new Set(['Positive', 'Neutral', 'Negative']),
      lang: '', minLikes: 0, search: '', sort: 'likes-desc',
    }};
    const SENT_RANK = {{Positive: 2, Neutral: 1, Negative: 0}};
    const host = panel.querySelector('.comments-host');
    const countEl = panel.querySelector('.count-summary');

    function refresh() {{
      const search = state.search.toLowerCase().trim();
      let filtered = sec.comments.filter(c => {{
        if (!state.sentiments.has(c.sentiment_label)) return false;
        if (state.lang && c.matched_language !== state.lang) return false;
        if ((c.likes || 0) < state.minLikes) return false;
        if (search) {{
          const hay = (c.comment + ' ' + (c.back_translation || '') + ' ' + c.author).toLowerCase();
          if (!hay.includes(search)) return false;
        }}
        return true;
      }});
      const [field, dir] = state.sort.split('-');
      filtered.sort((a, b) => {{
        let av = field === 'date' ? (a.date || '') : (a.likes || 0);
        let bv = field === 'date' ? (b.date || '') : (b.likes || 0);
        let cmp = av < bv ? -1 : av > bv ? 1 : 0;
        if (cmp === 0) {{
          // Tie-break on sentiment rank (most positive first when likes tie)
          cmp = (SENT_RANK[a.sentiment_label] || 0) - (SENT_RANK[b.sentiment_label] || 0);
        }}
        return dir === 'asc' ? cmp : -cmp;
      }});

      countEl.textContent = 'Showing ' + filtered.length.toLocaleString() + ' of '
        + sec.comments.length.toLocaleString() + ' comments';

      if (!filtered.length) {{
        host.innerHTML = '<div class="no-results">No comments match the current filters.</div>';
        return;
      }}
      // Group by sentiment, then cluster by theme within each sentiment
      let out = '';
      for (const lbl of ['Positive', 'Neutral', 'Negative']) {{
        const grp = filtered.filter(c => c.sentiment_label === lbl);
        if (!grp.length) continue;
        const emoji = {{Positive:'😊', Negative:'😞', Neutral:'😐'}}[lbl];
        out += '<div class="section-header" style="color:' + DATA.sentiment_colors[lbl] + ';">' +
               emoji + ' ' + lbl + ' (' + grp.length + ')</div>';
        // Bucket by theme, keeping within-theme sort order from filtered
        const themeBuckets = {{}};
        for (const c of grp) {{
          const t = c.theme || 'General';
          if (!themeBuckets[t]) themeBuckets[t] = [];
          themeBuckets[t].push(c);
        }}
        const orderedThemes = Object.keys(themeBuckets).sort(
          (a, b) => themeBuckets[b].length - themeBuckets[a].length || a.localeCompare(b)
        );
        for (const themeName of orderedThemes) {{
          const bucket = themeBuckets[themeName];
          out += '<div class="theme-sub">' + escapeHTML(themeName) +
                 ' <span style="color:#9ca3af;font-weight:500;">(' + bucket.length + ')</span></div>';
          out += bucket.map(renderCard).join('');
        }}
      }}
      host.innerHTML = out;
    }}

    panel.querySelector('.f-search').addEventListener('input', e => {{ state.search = e.target.value; refresh(); }});
    panel.querySelector('.f-lang').addEventListener('change', e => {{ state.lang = e.target.value; refresh(); }});
    panel.querySelector('.f-likes').addEventListener('input', e => {{ state.minLikes = +e.target.value || 0; refresh(); }});
    panel.querySelector('.f-sort').addEventListener('change', e => {{ state.sort = e.target.value; refresh(); }});
    panel.querySelectorAll('.pill-toggle').forEach(p => {{
      p.addEventListener('click', () => {{
        const s = p.dataset.s;
        if (state.sentiments.has(s)) {{ state.sentiments.delete(s); p.classList.remove('active'); }}
        else {{ state.sentiments.add(s); p.classList.add('active'); }}
        refresh();
      }});
    }});

    refresh();
  }}
}})();
</script>
</body>
</html>
"""

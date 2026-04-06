import html
from datetime import datetime, timezone, timedelta

_ET = timezone(timedelta(hours=-5))

from fpdf import FPDF

from config import SENTIMENT_COLORS, THEME_PALETTE
from analysis import get_theme_summary, get_sentiment_counts


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
    if c.get("is_reply"):
        reply_marker = (
            '<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
            'font-size:10px;font-weight:500;color:#00BCE7;background:#e0f7fc;'
            'margin-right:4px;">↩ reply</span>'
        )

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


def _render_markdown_text(pdf: FPDF, text: str, font_size: float = 9, line_height: float = 4.5):
    """Render text with **bold** markdown and - bullet points into the PDF."""
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
) -> bytes:
    """Build a styled PDF report grouped by sentiment.

    multi_sections: if provided, list of {"name", "comments", "ai_summary"} dicts
    for rendering multiple analysis sections (e.g. Subtitles + Dubbing).
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

    # ---- Summary info (plain text) ----
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
    pdf.ln(3)

    # ---- Languages detected ----
    from config import LANGUAGE_NAMES as _lc_to_name
    _lang_counts: dict[str, int] = {}
    for c in comments:
        lc = c.get("matched_language", "en")
        name = _lc_to_name.get(lc, lc)
        _lang_counts[name] = _lang_counts.get(name, 0) + 1

    if len(_lang_counts) > 1 or (len(_lang_counts) == 1 and "English" not in _lang_counts):
        pdf.set_font("Lato", "", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 5, "LANGUAGES DETECTED", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Lato", "", 9)
        pdf.set_text_color(26, 26, 26)
        lang_parts = [f"{name}: {count:,}" for name, count in
                      sorted(_lang_counts.items(), key=lambda x: -x[1])]
        pdf.cell(0, 5, "  ".join(lang_parts), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ---- Overall sentiment ----
    pdf.set_font("Lato", "B", 13)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 8, "Overall Sentiment", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _draw_sentiment_bar(pdf, sentiment_counts, total)
    # Labels under bar segments
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
            pdf.ln(4)

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

        # Sentiment-grouped comments for this section
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

            for c in group:
                _draw_comment(pdf, c, show_video_tag=multi_video)

            pdf.ln(6)

    # ---- Footer text ----
    pdf.set_font("Lato", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Sentiment by VADER  |  Themes by TF-IDF + KMeans",
             align="C", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


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

    # Reply marker
    if c.get("is_reply"):
        pdf.set_font("Lato", "I", 6)
        pdf.set_fill_color(224, 247, 252)
        pdf.set_text_color(0, 188, 231)
        pdf.cell(12, 4, " reply", fill=True, new_x="END")
        pdf.cell(3, 4, "", new_x="END")  # spacer

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
    pdf.set_text_color(255, 255, 255)
    pdf.cell(badge_w, 5, badge_text, new_x="LMARGIN", new_y="NEXT")

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

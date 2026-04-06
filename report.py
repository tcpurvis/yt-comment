import html
from datetime import datetime

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
    color = SENTIMENT_COLORS.get(label, "#A78BFA")
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
            'font-size:10px;font-weight:500;color:#5BC8F0;background:#e6f8fc;'
            'margin-right:4px;">↩ reply</span>'
        )

    translation_block = ""
    if c.get("back_translation") and c.get("original_language"):
        bt = html.escape(c["back_translation"])
        translation_block = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#f0f4ff;'
            f'border-left:3px solid #5BC8F0;border-radius:4px;font-size:13px;'
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
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

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
        <div style="background:#f0fbfd;border:1px solid #c5edf5;border-radius:12px;
                    padding:20px 24px;margin-bottom:32px;">
          <h2 style="margin:0 0 12px 0;font-size:16px;color:#5BC8F0;">
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

  <div style="background:linear-gradient(135deg,#5BC8F0,#A78BFA);border-radius:16px;
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
    """Sanitise text for fpdf (replace chars it can't encode in latin-1)."""
    return text.encode("latin-1", "replace").decode("latin-1")


class _ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(160, 160, 160)
        self.cell(0, 6, "YouTube Comment Analysis", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def build_pdf_report(
    comments: list[dict], search_query: str, keywords: list[str],
    ai_summary: str = "",
) -> bytes:
    """Build a styled PDF report grouped by sentiment."""
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    kw_display = ", ".join(keywords) if keywords else "None"
    multi_video = len(set(c.get("video_title", "") for c in comments)) > 1

    pdf = _ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ---- Title ----
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 12, "YouTube Comment Analysis", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(0, 6, f"Generated {now}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # ---- Summary box ----
    r, g, b = _hex_to_rgb("#5BC8F0")
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    box_y = pdf.get_y()
    usable = pdf.w - 20
    col_w = usable / 4
    box_h = 32
    pdf.rect(10, box_y, usable, box_h, "F")

    # Also draw a subtle gradient overlay (lighter right half)
    r2, g2, b2 = _hex_to_rgb("#A78BFA")
    pdf.set_fill_color(r2, g2, b2)
    pdf.rect(10 + usable / 2, box_y, usable / 2, box_h, "F")

    summary_items = [
        ("SEARCH QUERY", _safe(search_query[:35])),
        ("KEYWORDS", _safe(kw_display[:35])),
        ("TOTAL COMMENTS", str(total)),
        ("SENTIMENT", f"+{sentiment_counts['Positive']} ~{sentiment_counts['Neutral']} -{sentiment_counts['Negative']}"),
    ]
    for j, (lbl, val) in enumerate(summary_items):
        x = 14 + j * col_w
        pdf.set_xy(x, box_y + 5)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(220, 220, 255)
        pdf.cell(col_w - 4, 4, lbl, new_x="LMARGIN")
        pdf.set_xy(x, box_y + 12)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(col_w - 4, 8, val, new_x="LMARGIN")

    pdf.set_y(box_y + box_h + 8)

    # ---- Overall sentiment section ----
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Overall Sentiment", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Emoji-style summary counts above the bar
    pdf.set_font("Helvetica", "", 9)
    for lbl, icon in [("Positive", "(+)"), ("Neutral", "(~)"), ("Negative", "(-)")]:
        count = sentiment_counts.get(lbl, 0)
        pct = f"{count / total * 100:.0f}%" if total else "0%"
        sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[lbl])
        pdf.set_text_color(sr, sg, sb)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, f"  {icon} {lbl}: {count} ({pct})", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _draw_sentiment_bar(pdf, sentiment_counts, total)
    pdf.ln(8)

    # ---- AI Summary ----
    if ai_summary:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(91, 200, 240)
        pdf.cell(0, 8, "AI Theme Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(26, 26, 26)
        summary_text = _safe(ai_summary)
        pdf.multi_cell(pdf.w - 20, 4.5, summary_text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

    # ---- Sentiment sections ----
    for label in ["Positive", "Neutral", "Negative"]:
        group = [c for c in comments if c["sentiment_label"] == label]
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
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(0, 8, f"{emoji_text} {label}  ({len(group)} comments)",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        for c in group:
            _draw_comment(pdf, c, show_video_tag=multi_video)

        pdf.ln(6)

    # ---- Footer text ----
    pdf.set_font("Helvetica", "I", 8)
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
            pdf.set_font("Helvetica", "B", 7)
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
        pdf.set_font("Helvetica", "", 7)
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
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(avatar_size, 5, _safe(initials), align="C")

    # Author + date + sentiment
    content_x = x_start + avatar_size + 4
    pdf.set_xy(content_x, y_start)

    # Reply marker
    if c.get("is_reply"):
        pdf.set_font("Helvetica", "I", 6)
        pdf.set_fill_color(230, 248, 252)
        pdf.set_text_color(91, 200, 240)
        pdf.cell(12, 4, " reply", fill=True, new_x="END")
        pdf.cell(3, 4, "", new_x="END")  # spacer

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(3, 3, 3)
    pdf.cell(0, 5, _safe(c["author"]), new_x="END")

    pdf.set_font("Helvetica", "", 7)
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
    pdf.set_font("Helvetica", "B", 7)
    badge_w = pdf.get_string_width(badge_text) + 4
    pdf.set_fill_color(sr, sg, sb)
    pdf.rect(badge_x + 3, badge_y + 0.5, badge_w, 4, "F")
    pdf.set_xy(badge_x + 3, badge_y)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(badge_w, 5, badge_text, new_x="LMARGIN", new_y="NEXT")

    # Comment text
    pdf.set_x(content_x)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(3, 3, 3)
    comment_text = _safe(c["comment"])
    text_w = pdf.w - content_x - 10
    pdf.multi_cell(text_w, 4.5, comment_text, new_x="LMARGIN", new_y="NEXT")

    # Back-translation
    if c.get("back_translation") and c.get("original_language"):
        pdf.set_x(content_x)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(91, 200, 240)
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
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(96, 96, 96)
        pdf.cell(0, 4, "  |  ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")

    # Separator line
    pdf.ln(3)
    pdf.set_draw_color(230, 230, 230)
    pdf.line(content_x, pdf.get_y(), pdf.w - 10, pdf.get_y())
    pdf.ln(4)

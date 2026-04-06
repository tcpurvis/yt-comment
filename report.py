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
    colors = [
        "#6366f1", "#ec4899", "#f59e0b", "#10b981",
        "#3b82f6", "#ef4444", "#8b5cf6", "#14b8a6",
    ]
    return colors[hash(name) % len(colors)]


def _sentiment_badge(label: str) -> str:
    color = SENTIMENT_COLORS.get(label, "#616161")
    emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}.get(label, "")
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'font-size:11px;font-weight:600;color:#fff;background:{color};">'
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


def _comment_card(c: dict) -> str:
    author = html.escape(c["author"])
    text = html.escape(c["comment"])
    avatar_bg = _avatar_color(c["author"])
    initials = _initials(c["author"])
    date_str = _format_date(c["date"])
    sentiment = _sentiment_badge(c["sentiment_label"])
    likes = _like_icon(c.get("likes", 0))
    replies = _reply_icon(c.get("replies", 0))

    translation_block = ""
    if c.get("back_translation") and c.get("original_language"):
        bt = html.escape(c["back_translation"])
        translation_block = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#f0f4ff;'
            f'border-left:3px solid #6366f1;border-radius:4px;font-size:13px;'
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
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
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
    comments: list[dict], search_query: str, keywords: list[str]
) -> str:
    """Build a complete HTML report with themed sections and styled comments."""
    themes = get_theme_summary(comments)
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    kw_display = ", ".join(keywords) if keywords else "None"

    # Theme sections
    theme_sections = ""
    for i, (theme_name, theme_comments) in enumerate(themes.items()):
        color = THEME_PALETTE[i % len(THEME_PALETTE)]
        cards = "".join(_comment_card(c) for c in theme_comments)

        # Mini sentiment breakdown for this theme
        t_counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
        for c in theme_comments:
            t_counts[c["sentiment_label"]] += 1
        mini_bar = _sentiment_bar(t_counts, len(theme_comments))

        theme_sections += f"""
        <div style="margin-bottom:36px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
            <div style="width:6px;height:28px;border-radius:3px;background:{color};"></div>
            <h2 style="margin:0;font-size:18px;color:#1a1a1a;">{html.escape(theme_name)}</h2>
            <span style="background:#f3f4f6;color:#6b7280;font-size:12px;
                         padding:2px 10px;border-radius:10px;font-weight:600;">
              {len(theme_comments)} comment{"s" if len(theme_comments) != 1 else ""}
            </span>
          </div>
          {mini_bar}
          <div style="padding-left:16px;">{cards}</div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #ffffff;
    color: #1a1a1a;
    padding: 40px;
    max-width: 900px;
    margin: 0 auto;
  }}
  @media print {{
    body {{ padding: 20px; }}
  }}
</style>
</head>
<body>
  <!-- Header -->
  <div style="text-align:center;margin-bottom:36px;">
    <div style="font-size:40px;margin-bottom:8px;">💬</div>
    <h1 style="font-size:26px;font-weight:700;color:#1a1a1a;margin-bottom:4px;">
      YouTube Comment Analysis
    </h1>
    <p style="font-size:14px;color:#6b7280;">Generated {now}</p>
  </div>

  <!-- Summary card -->
  <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:16px;
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
      <div>
        <div style="font-size:12px;opacity:0.85;text-transform:uppercase;letter-spacing:1px;">
          Themes Found</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px;">{len(themes)}</div>
      </div>
    </div>
  </div>

  <!-- Overall sentiment -->
  <h2 style="font-size:18px;margin-bottom:4px;">Overall Sentiment</h2>
  {_sentiment_bar(sentiment_counts, total)}

  <!-- Themes -->
  {theme_sections}

  <!-- Footer -->
  <div style="text-align:center;padding:24px 0;border-top:1px solid #e5e7eb;
              margin-top:24px;font-size:12px;color:#9ca3af;">
    Built with YouTube Comment Scraper &middot; Sentiment by VADER &middot; Themes by TF-IDF + KMeans
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
    comments: list[dict], search_query: str, keywords: list[str]
) -> bytes:
    """Build a styled PDF report and return the bytes."""
    themes = get_theme_summary(comments)
    sentiment_counts = get_sentiment_counts(comments)
    total = len(comments)
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    kw_display = ", ".join(keywords) if keywords else "None"

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
    r, g, b = _hex_to_rgb("#6366f1")
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    box_y = pdf.get_y()
    pdf.rect(10, box_y, pdf.w - 20, 28, "F")

    pdf.set_xy(14, box_y + 3)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(42, 4, "SEARCH QUERY", new_x="END")
    pdf.cell(42, 4, "KEYWORDS", new_x="END")
    pdf.cell(42, 4, "TOTAL COMMENTS", new_x="END")
    pdf.cell(42, 4, "THEMES FOUND", new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(42, 8, _safe(search_query[:30]), new_x="END")
    pdf.cell(42, 8, _safe(kw_display[:30]), new_x="END")
    pdf.cell(42, 8, str(total), new_x="END")
    pdf.cell(42, 8, str(len(themes)), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # ---- Overall sentiment bar ----
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Overall Sentiment", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _draw_sentiment_bar(pdf, sentiment_counts, total)
    pdf.ln(8)

    # ---- Theme sections ----
    for i, (theme_name, theme_comments) in enumerate(themes.items()):
        color = THEME_PALETTE[i % len(THEME_PALETTE)]

        # Theme heading
        if pdf.get_y() > pdf.h - 50:
            pdf.add_page()
        r, g, b = _hex_to_rgb(color)
        pdf.set_fill_color(r, g, b)
        pdf.rect(10, pdf.get_y(), 4, 8, "F")
        pdf.set_x(16)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(0, 8, f"{_safe(theme_name)}  ({len(theme_comments)} comments)",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        # Theme sentiment mini-bar
        t_counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
        for c in theme_comments:
            t_counts[c["sentiment_label"]] += 1
        _draw_sentiment_bar(pdf, t_counts, len(theme_comments))
        pdf.ln(4)

        # Comments
        for c in theme_comments:
            _draw_comment(pdf, c)

        pdf.ln(6)

    # ---- Footer text ----
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Sentiment by VADER  |  Themes by TF-IDF + KMeans",
             align="C", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()


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
            pdf.set_text_color(255, 255, 255)
            pdf.cell(seg_w, bar_h, f"{count} ({pct:.0%})", align="C")
        x0 += seg_w

    pdf.set_y(y0 + bar_h)


def _draw_comment(pdf: FPDF, c: dict):
    """Draw a single comment card in the PDF."""
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()

    x_start = 14
    y_start = pdf.get_y()

    # Avatar circle
    avatar_color = _avatar_color(c["author"])
    r, g, b = _hex_to_rgb(avatar_color)
    pdf.set_fill_color(r, g, b)
    cx, cy = x_start + 4, y_start + 4
    pdf.ellipse(cx - 4, cy - 4, 8, 8, "F")
    initials = _initials(c["author"])
    pdf.set_xy(cx - 4, cy - 2.5)
    pdf.set_font("Helvetica", "B", 6)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(8, 5, _safe(initials), align="C")

    # Author + date + sentiment
    pdf.set_xy(x_start + 11, y_start)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(3, 3, 3)
    pdf.cell(0, 5, _safe(c["author"]), new_x="END")

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(144, 144, 144)
    date_str = _format_date(c["date"])
    pdf.cell(0, 5, f"   {date_str}", new_x="END")

    # Sentiment badge
    label = c["sentiment_label"]
    badge_text = {"Positive": "(+) Positive", "Negative": "(-) Negative", "Neutral": "(~) Neutral"}[label]
    sr, sg, sb = _hex_to_rgb(SENTIMENT_COLORS[label])
    pdf.set_text_color(sr, sg, sb)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(0, 5, f"   {badge_text}", new_x="LMARGIN", new_y="NEXT")

    # Comment text
    pdf.set_x(x_start + 11)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(3, 3, 3)
    comment_text = _safe(c["comment"])
    pdf.multi_cell(pdf.w - x_start - 22, 4.5, comment_text, new_x="LMARGIN", new_y="NEXT")

    # Back-translation
    if c.get("back_translation") and c.get("original_language"):
        pdf.set_x(x_start + 11)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(99, 102, 241)
        bt = _safe(c["back_translation"])
        pdf.multi_cell(pdf.w - x_start - 22, 4, f"EN: {bt}", new_x="LMARGIN", new_y="NEXT")

    # Likes / replies
    meta_parts = []
    if c.get("likes", 0) > 0:
        meta_parts.append(f"Likes: {c['likes']}")
    if c.get("replies", 0) > 0:
        meta_parts.append(f"Replies: {c['replies']}")
    if meta_parts:
        pdf.set_x(x_start + 11)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(96, 96, 96)
        pdf.cell(0, 4, "  |  ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")

    # Separator line
    pdf.ln(2)
    pdf.set_draw_color(240, 240, 240)
    pdf.line(x_start + 11, pdf.get_y(), pdf.w - 10, pdf.get_y())
    pdf.ln(3)

import html
from datetime import datetime

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

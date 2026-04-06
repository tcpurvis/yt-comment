# YouTube Comment Scraper

A Streamlit app that searches YouTube videos by keyword, fetches their comments, filters by keywords, and exports results as CSV.

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/tcpurvis/yt-comment.git
   cd yt-comment
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API key**

   **Locally:** Create `.streamlit/secrets.toml`:
   ```toml
   YOUTUBE_API_KEY = "your_api_key_here"
   ```

   **Streamlit Cloud:** Add `YOUTUBE_API_KEY` in the app's Secrets panel.

   Get a key from the [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) console.

4. **Run the app**
   ```bash
   streamlit run app.py
   ```

## Features

- Search YouTube videos by query
- Filter comments by multiple keywords (comma-separated, case-insensitive, any match)
- **Sentiment analysis** (VADER) — each comment tagged Positive / Neutral / Negative
- **Theme discovery** — comments auto-grouped by topic using TF-IDF + KMeans clustering
- **Multi-language search** — keywords are translated to selected languages, matching foreign comments are fetched with a back-translation to English
- Playful YouTube-style HTML report with avatars, sentiment badges, and theme sections
- In-app report preview + downloadable **PDF export**

## Architecture

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI, orchestration |
| `config.py` | Constants, supported languages, color palettes |
| `analysis.py` | VADER sentiment + TF-IDF/KMeans theme clustering |
| `translate.py` | Keyword translation + back-translation via Google Translate |
| `report.py` | YouTube-styled HTML report builder |

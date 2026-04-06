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
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) key.

4. **Run the app**
   ```bash
   streamlit run app.py
   ```

## Features

- Search YouTube videos by query
- Filter comments by multiple keywords (comma-separated, case-insensitive, any match)
- Configurable limits for videos and comments per video
- Interactive data table with full results
- CSV export with: author, comment text, like count, reply count, date posted

## CSV Columns

| Column | Description |
|---|---|
| author | Comment author display name |
| comment | Comment text |
| like_count | Number of likes on the comment |
| reply_count | Number of replies |
| date_posted | ISO 8601 timestamp |
| video_title | Title of the source video |
| video_id | YouTube video ID |

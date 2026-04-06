import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from config import YOUTUBE_API_KEY, MAX_RESULTS_PER_PAGE


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


def fetch_comments(youtube, video_id: str, max_comments: int = 100) -> list[dict]:
    """Fetch top-level comments for a video."""
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
            comments.append(
                {
                    "author": snippet["authorDisplayName"],
                    "comment": snippet["textDisplay"],
                    "likes": snippet["likeCount"],
                    "replies": item["snippet"]["totalReplyCount"],
                    "date": snippet["publishedAt"],
                    "video_id": video_id,
                }
            )
        request = youtube.commentThreads().list_next(request, response)
    return comments[:max_comments]


def filter_comments(comments: list[dict], keywords: list[str]) -> list[dict]:
    """Keep comments where any keyword appears (case-insensitive)."""
    if not keywords:
        return comments
    return [
        c
        for c in comments
        if any(kw.lower() in c["comment"].lower() for kw in keywords)
    ]


def main():
    st.set_page_config(page_title="YouTube Comment Scraper", layout="wide")
    st.title("YouTube Comment Scraper")

    api_key = st.sidebar.text_input(
        "YouTube API Key", value=YOUTUBE_API_KEY, type="password"
    )
    if not api_key:
        st.info("Enter your YouTube Data API v3 key in the sidebar to get started.")
        return

    search_query = st.text_input("Search YouTube for videos", placeholder="e.g. python tutorial")
    keyword_input = st.text_input(
        "Filter comments by keywords (comma-separated)",
        placeholder="e.g. great, awesome, helpful",
    )
    keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

    col1, col2 = st.columns(2)
    max_videos = col1.slider("Max videos to search", 1, 50, 10)
    max_comments = col2.slider("Max comments per video", 10, 500, 100)

    if st.button("Fetch Comments", type="primary"):
        if not search_query:
            st.warning("Please enter a search query.")
            return

        youtube = get_youtube_client(api_key)

        with st.spinner("Searching videos..."):
            videos = search_videos(youtube, search_query, max_videos)

        if not videos:
            st.warning("No videos found.")
            return

        st.write(f"Found **{len(videos)}** videos. Fetching comments...")

        all_comments = []
        progress = st.progress(0)
        for i, video in enumerate(videos):
            comments = fetch_comments(youtube, video["video_id"], max_comments)
            for c in comments:
                c["video_title"] = video["title"]
            all_comments.extend(comments)
            progress.progress((i + 1) / len(videos))

        filtered = filter_comments(all_comments, keywords)

        st.success(
            f"Fetched **{len(all_comments)}** comments, "
            f"**{len(filtered)}** match keyword filter."
        )

        if not filtered:
            st.info("No comments matched your keywords.")
            return

        df = pd.DataFrame(filtered)
        df = df[["author", "comment", "likes", "replies", "date", "video_title", "video_id"]]
        df = df.rename(columns={"likes": "like_count", "replies": "reply_count", "date": "date_posted"})

        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name="youtube_comments.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()

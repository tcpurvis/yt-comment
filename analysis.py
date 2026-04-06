from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
import numpy as np


_analyzer = SentimentIntensityAnalyzer()


def analyze_sentiment(text: str) -> dict:
    """Return sentiment label and compound score for a piece of text."""
    scores = _analyzer.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.05:
        label = "Positive"
    elif compound <= -0.05:
        label = "Negative"
    else:
        label = "Neutral"
    return {"label": label, "score": compound}


def add_sentiment(comments: list[dict]) -> list[dict]:
    """Add sentiment_label and sentiment_score to each comment dict."""
    for c in comments:
        text = c.get("back_translation") or c["comment"]
        result = analyze_sentiment(text)
        c["sentiment_label"] = result["label"]
        c["sentiment_score"] = result["score"]
    return comments


def cluster_into_themes(
    comments: list[dict], max_themes: int = 8, min_comments: int = 3
) -> list[dict]:
    """Assign a theme label to each comment using TF-IDF + KMeans clustering."""
    if len(comments) < min_comments:
        for c in comments:
            c["theme"] = "General"
        return comments

    texts = [c.get("back_translation") or c["comment"] for c in comments]

    vectorizer = TfidfVectorizer(
        max_features=2000,
        stop_words="english",
        min_df=1,
        max_df=0.95,
        ngram_range=(1, 2),
    )
    tfidf = vectorizer.fit_transform(texts)
    feature_names = vectorizer.get_feature_names_out()

    n_clusters = min(max_themes, max(2, len(comments) // 5))
    n_clusters = min(n_clusters, len(comments))

    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    km.fit(tfidf)

    # Build a readable label per cluster from top TF-IDF terms
    order_centroids = km.cluster_centers_.argsort()[:, ::-1]
    theme_labels = {}
    for i in range(n_clusters):
        top_terms = [feature_names[idx] for idx in order_centroids[i, :3]]
        theme_labels[i] = " / ".join(top_terms).title()

    for c, label_id in zip(comments, km.labels_):
        c["theme"] = theme_labels[label_id]

    return comments


def get_theme_summary(comments: list[dict]) -> dict:
    """Return {theme: [comments]} grouping."""
    themes: dict[str, list[dict]] = {}
    for c in comments:
        themes.setdefault(c["theme"], []).append(c)
    return dict(sorted(themes.items(), key=lambda x: -len(x[1])))


def get_sentiment_counts(comments: list[dict]) -> dict:
    """Return count of each sentiment label."""
    counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
    for c in comments:
        counts[c["sentiment_label"]] = counts.get(c["sentiment_label"], 0) + 1
    return counts

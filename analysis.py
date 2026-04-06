from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
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


def _optimal_k(tfidf, max_k: int) -> int:
    """Find the best number of clusters using silhouette score."""
    best_k = 2
    best_score = -1
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(tfidf)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(tfidf, labels)
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


def cluster_into_themes(comments: list[dict]) -> list[dict]:
    """Assign a theme label to each comment using TF-IDF + KMeans.

    The number of clusters is chosen automatically via silhouette analysis.
    """
    if len(comments) < 3:
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

    # Auto-detect optimal cluster count (try 2 up to sqrt(n), capped at 15)
    max_k = min(15, max(2, int(len(comments) ** 0.5)))
    max_k = min(max_k, len(comments) - 1)
    n_clusters = _optimal_k(tfidf, max_k)

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

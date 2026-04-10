from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import numpy as np


_analyzer = SentimentIntensityAnalyzer()

# Extend VADER with YouTube/internet slang
_YOUTUBE_SLANG = {
    # Positive slang
    "goat": 3.0, "goated": 3.0, "fire": 2.5, "🔥": 2.5,
    "lit": 2.5, "bussin": 2.5, "slaps": 2.5, "banger": 3.0,
    "bangers": 3.0, "w": 2.0, "dub": 2.0, "based": 2.0,
    "slay": 2.5, "slayed": 2.5, "slaying": 2.5, "iconic": 2.5,
    "peak": 2.5, "valid": 1.5, "goosebumps": 2.0, "chef's kiss": 3.0,
    "no cap": 2.0, "fr fr": 2.0, "ong": 2.0, "real talk": 2.0,
    "fax": 2.0, "facts": 2.0, "respect": 2.0, "king": 2.0,
    "queen": 2.0, "legend": 3.0, "legendary": 3.0, "masterpiece": 3.5,
    "perfection": 3.5, "underrated": 2.0, "bless": 2.0, "blessed": 2.0,
    "clutch": 2.5, "insane": 2.0, "heat": 2.0, "pog": 2.5,
    "poggers": 2.5, "pogchamp": 2.5, "hype": 2.5, "hyped": 2.5,
    "vibes": 2.0, "vibe": 2.0, "chef kiss": 3.0, "immaculate": 3.0,
    "elite": 2.5, "top tier": 3.0, "s tier": 3.0, "10/10": 3.5,
    "100": 2.0, "💯": 2.0, "gem": 2.5, "hidden gem": 3.0,
    "chills": 2.0, "sheesh": 2.5, "bussin bussin": 3.0,
    "nailed it": 2.5, "spot on": 2.0, "on point": 2.0,
    "lets go": 2.5, "let's go": 2.5, "lfg": 2.5, "les go": 2.5,
    "preach": 2.0, "spitting": 2.0, "spittin": 2.0,
    "wholesome": 2.5, "heartwarming": 2.5, "goosebump": 2.0,
    "W take": 2.5, "big W": 2.5, "massive W": 3.0,
    "ate": 2.5, "ate that": 2.5, "understood the assignment": 3.0,
    "rent free": 2.0, "hits different": 2.5, "hit different": 2.5,
    "chef's kiss": 3.0, "muah": 2.0,
    "❤️": 2.0, "😍": 2.5, "🥰": 2.5, "👏": 2.0, "🙌": 2.0,
    "😭": 1.5,  # often used positively on YouTube ("I'm crying this is so good")
    "💀": 1.0,  # "I'm dead" = funny/great
    "bruh moment": 1.0, "i'm dead": 1.5, "im dead": 1.5,

    # Negative slang
    "mid": -2.0, "L": -2.0, "ratio": -2.0, "ratioed": -2.5,
    "cap": -1.5, "capping": -1.5, "sus": -1.5, "sussy": -1.5,
    "cringe": -2.5, "cringy": -2.5, "cringey": -2.5, "cringe af": -3.0,
    "trash": -3.0, "garbage": -3.0, "ass": -2.0, "dogwater": -3.0,
    "dog water": -3.0, "L take": -2.5, "big L": -2.5, "massive L": -3.0,
    "cope": -2.0, "copium": -2.0, "seethe": -2.5, "touch grass": -2.0,
    "clown": -2.5, "🤡": -2.5, "clown behavior": -3.0,
    "fell off": -3.5, "falling off": -3.0, "washed": -2.5,
    "washed up": -2.5, "overrated": -2.0, "overhyped": -2.0,
    "clickbait": -2.5, "click bait": -2.5, "scam": -3.0,
    "flop": -2.5, "flopped": -2.5, "dead channel": -3.0,
    "unsubbed": -2.5, "unsubscribed": -2.5, "dislike": -2.0,
    "unwatchable": -3.0, "skip": -1.5, "boring af": -3.0,
    "yikes": -2.0, "oof": -1.5, "bruh": -1.0,
    "no one asked": -2.5, "nobody asked": -2.5, "didn't ask": -2.0,
    "nah": -1.0, "nope": -1.0, "meh": -1.5, "ew": -2.0,
    "tf": -1.5, "wtf": -1.5, "smh": -1.5,
    "💩": -2.5, "🗑️": -2.5, "👎": -2.0, "😒": -1.5, "🙄": -1.5,
    "rigged": -2.5, "robbed": -2.5, "unfair": -2.0,
    "sellout": -2.5, "sell out": -2.5, "sold out": -2.0,
    "lazy": -2.0, "low effort": -2.5, "half assed": -2.5,
}

_analyzer.lexicon.update(_YOUTUBE_SLANG)


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

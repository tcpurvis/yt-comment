YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENT_THREADS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
MAX_RESULTS_PER_PAGE = 50

SUPPORTED_LANGUAGES = {
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Portuguese": "pt",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Simplified)": "zh-CN",
    "Hindi": "hi",
    "Arabic": "ar",
    "Russian": "ru",
    "Turkish": "tr",
    "Thai": "th",
    "Vietnamese": "vi",
    "Indonesian": "id",
}

SENTIMENT_COLORS = {
    "Positive": "#2e7d32",
    "Negative": "#c62828",
    "Neutral": "#616161",
}

# Pre-built keyword filter presets
KEYWORD_PRESETS = {
    "Subtitles & Captions": {
        "keywords": ["subtitle", "subtitles", "caption", "captions", "subs", "cc",
                      "closed caption", "closed captions", "sub", "dub", "dubbed"],
        "translations": {
            "es": ["subtítulos", "subtitulo", "leyendas", "subs", "subtitulado",
                    "subtitulados", "cc"],
            "fr": ["sous-titres", "sous-titre", "sous titres", "subs", "st",
                    "sous-titré", "cc"],
            "de": ["Untertitel", "UT", "subs", "Untertitelung", "untertitelt"],
            "pt": ["legendas", "legenda", "legendado", "legendas automáticas",
                    "subs", "cc"],
            "it": ["sottotitoli", "sottotitolo", "didascalie", "sub", "subs",
                    "sottotitolato", "cc"],
            "ja": ["字幕", "じまく", "サブタイトル", "キャプション", "cc"],
            "ko": ["자막", "짜막", "캡션", "서브타이틀", "cc"],
            "zh-CN": ["字幕", "cc", "弹幕", "文字"],
            "hi": ["उपशीर्षक", "कैप्शन", "सबटाइटल", "subtitle", "cc"],
            "ar": ["ترجمة", "ترجمه", "تعليقات توضيحية", "الترجمة", "cc"],
            "ru": ["субтитры", "сабы", "субтитр", "субы", "cc"],
            "tr": ["altyazı", "altyazi", "alt yazı", "subs", "cc"],
            "th": ["คำบรรยาย", "ซับ", "ซับไตเติ้ล", "แคปชั่น", "cc"],
            "vi": ["phụ đề", "phude", "sub", "subs", "cc"],
            "id": ["subtitle", "teks terjemahan", "teks", "sub", "subs",
                    "keterangan", "cc"],
        },
    },
}

THEME_PALETTE = [
    "#6366f1",  # indigo
    "#ec4899",  # pink
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#14b8a6",  # teal
]

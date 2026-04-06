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
        "keywords": ["subtitle", "subtitles", "caption", "captions", "cc",
                      "closed caption", "closed captions"],
        "translations": {
            "es": ["subtítulos", "subtitulo", "leyendas", "subtitulado",
                    "subtitulados", "cc"],
            "fr": ["sous-titres", "sous-titre", "sous titres", "st",
                    "sous-titré", "cc"],
            "de": ["Untertitel", "UT", "Untertitelung", "untertitelt"],
            "pt": ["legendas", "legenda", "legendado", "legendas automáticas",
                    "cc"],
            "it": ["sottotitoli", "sottotitolo", "didascalie",
                    "sottotitolato", "cc"],
            "ja": ["字幕", "じまく", "サブタイトル", "キャプション", "cc"],
            "ko": ["자막", "짜막", "캡션", "서브타이틀", "cc"],
            "zh-CN": ["字幕", "cc", "弹幕", "文字"],
            "hi": ["उपशीर्षक", "कैप्शन", "सबटाइटल", "subtitle", "cc"],
            "ar": ["ترجمة", "ترجمه", "تعليقات توضيحية", "الترجمة", "cc"],
            "ru": ["субтитры", "сабы", "субтитр", "субы", "cc"],
            "tr": ["altyazı", "altyazi", "alt yazı", "cc"],
            "th": ["คำบรรยาย", "ซับ", "ซับไตเติ้ล", "แคปชั่น", "cc"],
            "vi": ["phụ đề", "phude", "cc"],
            "id": ["subtitle", "teks terjemahan", "teks",
                    "keterangan", "cc"],
        },
    },
    "Dubbing & Voice": {
        "keywords": ["dub", "dubbed", "dubbing", "voice", "voice actor",
                      "voice acting", "voice over", "voiceover",
                      "audio track", "original audio", "voice cast"],
        "translations": {
            "es": ["doblaje", "doblado", "doblar", "voz", "actor de voz",
                    "actriz de voz", "voces", "pista de audio",
                    "audio original", "doblaje latino", "castellano"],
            "fr": ["doublage", "doublé", "doubler", "voix", "comédien de doublage",
                    "acteur de doublage", "voix off", "piste audio",
                    "VF", "VO", "version française", "version originale"],
            "de": ["Synchronisation", "synchronisiert", "Stimme", "Sprecher",
                    "Synchronsprecher", "Tonspur", "Originalton",
                    "deutsche Synchro", "Synchro"],
            "pt": ["dublagem", "dublado", "dublar", "voz", "ator de voz",
                    "dublador", "dubladora", "faixa de áudio",
                    "áudio original", "dub brasileiro"],
            "it": ["doppiaggio", "doppiato", "doppiare", "voce", "doppiatore",
                    "doppiatrice", "traccia audio", "audio originale",
                    "doppiaggio italiano"],
            "ja": ["吹き替え", "ふきかえ", "声優", "せいゆう", "ボイス",
                    "音声", "日本語吹き替え", "英語吹き替え",
                    "声", "アフレコ", "CV"],
            "ko": ["더빙", "더빙판", "성우", "음성", "보이스",
                    "오디오 트랙", "원어", "한국어 더빙",
                    "목소리", "한국어판"],
            "zh-CN": ["配音", "配音演员", "声优", "音轨", "原声",
                       "中文配音", "日语配音", "英语配音",
                       "声音", "国语配音"],
            "hi": ["डबिंग", "डब", "आवाज", "वॉइस एक्टर",
                    "ऑडियो ट्रैक", "हिंदी डब", "voice actor",
                    "dubbed", "dubbing"],
            "ar": ["دبلجة", "مدبلج", "صوت", "ممثل صوتي",
                    "المسار الصوتي", "الصوت الأصلي",
                    "دبلجة عربية", "عربي مدبلج"],
            "ru": ["дубляж", "дублированный", "озвучка", "голос",
                    "актёр озвучки", "озвучивание", "звуковая дорожка",
                    "оригинальная озвучка", "русская озвучка",
                    "русский дубляж"],
            "tr": ["dublaj", "dublajlı", "seslendirme", "ses", "ses aktörü",
                    "seslendirmen", "ses kaydı", "orijinal ses",
                    "Türkçe dublaj"],
            "th": ["พากย์", "พากย์เสียง", "พากย์ไทย", "นักพากย์",
                    "เสียง", "เสียงพากย์", "เสียงต้นฉบับ",
                    "แทร็กเสียง"],
            "vi": ["lồng tiếng", "thuyết minh", "diễn viên lồng tiếng",
                    "giọng nói", "bản lồng tiếng", "tiếng Việt",
                    "âm thanh gốc"],
            "id": ["dubbing", "sulih suara", "pengisi suara", "suara",
                    "aktor suara", "trek audio", "audio asli",
                    "dubbing Indonesia"],
        },
    },
}

THEME_PALETTE = [
    "#00BCE7",  # cyan accent
    "#ec4899",  # pink
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#14b8a6",  # teal
]

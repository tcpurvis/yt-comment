import streamlit as st
from deep_translator import GoogleTranslator
from lingua import Language, LanguageDetectorBuilder

# Build detector once for supported languages
_LINGUA_LANGS = [
    Language.ENGLISH, Language.SPANISH, Language.FRENCH, Language.GERMAN,
    Language.PORTUGUESE, Language.ITALIAN, Language.JAPANESE, Language.KOREAN,
    Language.CHINESE, Language.HINDI, Language.ARABIC, Language.RUSSIAN,
    Language.TURKISH, Language.THAI, Language.VIETNAMESE, Language.INDONESIAN,
]
_detector = LanguageDetectorBuilder.from_languages(*_LINGUA_LANGS).build()

# Map lingua Language enum to ISO codes used by Google Translate
_LINGUA_TO_CODE = {
    Language.ENGLISH: "en",
    Language.SPANISH: "es",
    Language.FRENCH: "fr",
    Language.GERMAN: "de",
    Language.PORTUGUESE: "pt",
    Language.ITALIAN: "it",
    Language.JAPANESE: "ja",
    Language.KOREAN: "ko",
    Language.CHINESE: "zh-CN",
    Language.HINDI: "hi",
    Language.ARABIC: "ar",
    Language.RUSSIAN: "ru",
    Language.TURKISH: "tr",
    Language.THAI: "th",
    Language.VIETNAMESE: "vi",
    Language.INDONESIAN: "id",
}


def detect_language(text: str) -> str:
    """Detect the language of a text string. Returns ISO code."""
    try:
        lang = _detector.detect_language_of(text)
        if lang:
            return _LINGUA_TO_CODE.get(lang, "en")
    except Exception:
        pass
    return "en"


def translate_keywords(keywords: list[str], target_lang: str) -> list[str]:
    """Translate a list of keywords from English to the target language."""
    translator = GoogleTranslator(source="en", target=target_lang)
    translated = []
    for kw in keywords:
        try:
            result = translator.translate(kw.strip())
            if result:
                translated.append(result)
        except Exception:
            continue
    return translated


def _translate_with_claude(text: str, target: str = "en") -> str | None:
    """Try translating with Claude API. Returns None if unavailable."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": (
                    f"Translate the following text to English. "
                    f"Return ONLY the translation, nothing else.\n\n{text}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception:
        return None


def _translate_with_google(text: str, source_lang: str) -> str | None:
    """Try translating with Google Translate."""
    try:
        translator = GoogleTranslator(source=source_lang, target="en")
        result = translator.translate(text)
        if result and result.strip() != text.strip():
            return result
    except Exception:
        pass
    return None


def back_translate(text: str, source_lang: str = "auto") -> str:
    """Translate text to English. Tries Claude first, falls back to Google."""
    if source_lang == "auto":
        source_lang = detect_language(text)

    if source_lang == "en":
        return text

    # Try Claude first (more accurate for informal/slang text)
    result = _translate_with_claude(text)
    if result:
        return result

    # Fall back to Google Translate with detected language
    result = _translate_with_google(text, source_lang)
    if result:
        return result

    # Last resort: try Google with auto-detect
    result = _translate_with_google(text, "auto")
    if result:
        return result

    return text


def add_back_translations(
    comments: list[dict], source_lang: str = "auto"
) -> list[dict]:
    """Add back_translation and detected_language fields to each comment."""
    for c in comments:
        detected = detect_language(c["comment"])
        c["detected_language"] = detected

        if detected == "en":
            c["back_translation"] = c["comment"]
        else:
            c["back_translation"] = back_translate(c["comment"], detected)

        c["original_language"] = detected
    return comments

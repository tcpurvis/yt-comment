import streamlit as st
from deep_translator import GoogleTranslator


def detect_language(text: str) -> str:
    """Detect the language of a text string. Returns ISO code."""
    # Try pycld2 first (fast, offline)
    try:
        import pycld2
        _, _, details = pycld2.detect(text)
        code = details[0][1]
        if code and code != "un":
            # Normalize Chinese codes
            if code == "zh":
                return "zh-CN"
            return code
    except Exception:
        pass

    # Fallback: use Google Translate's auto-detect via a dummy translation
    try:
        translator = GoogleTranslator(source="auto", target="en")
        translator.translate(text[:200])
        # deep-translator doesn't expose detected lang directly,
        # so we check if the result differs from input
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


def _translate_with_claude(text: str) -> str | None:
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

import streamlit as st
from deep_translator import GoogleTranslator


def detect_language(text: str) -> str:
    """Detect the language of a text string. Returns ISO code."""
    if not text or len(text.strip()) < 3:
        return "en"

    # Try pycld2 (fast, offline)
    try:
        import pycld2
        is_reliable, _, details = pycld2.detect(text)
        code = details[0][1]
        confidence = details[0][2]

        if code and code != "un":
            # Normalize Chinese codes
            if code == "zh":
                code = "zh-CN"
            # Trust the result if reliable or high confidence
            if is_reliable or confidence > 80:
                return code
            # For unreliable short text, check if it has non-ASCII chars
            # that suggest non-English
            has_non_ascii = any(ord(ch) > 127 for ch in text)
            if has_non_ascii and code != "en":
                return code
    except Exception:
        pass

    # Fallback: check for common non-English character patterns
    import re as _re
    # Spanish indicators
    if _re.search(r"[áéíóúñ¿¡]", text, _re.IGNORECASE):
        return "es"
    # French indicators
    if _re.search(r"[àâçéèêëîïôùûüÿœæ]", text, _re.IGNORECASE):
        return "fr"
    # German indicators
    if _re.search(r"[äöüß]", text, _re.IGNORECASE):
        return "de"
    # Portuguese indicators
    if _re.search(r"[ãõçà]", text, _re.IGNORECASE) and _re.search(r"\b(não|sim|muito|também)\b", text, _re.IGNORECASE):
        return "pt"
    # Russian/Cyrillic
    if _re.search(r"[а-яА-Я]", text):
        return "ru"
    # Arabic
    if _re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    # Japanese
    if _re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text):
        return "ja"
    # Korean
    if _re.search(r"[\uAC00-\uD7AF]", text):
        return "ko"
    # Thai
    if _re.search(r"[\u0E00-\u0E7F]", text):
        return "th"

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
    """Try translating a single text with Claude API."""
    results = _batch_translate_with_claude([text])
    return results[0] if results else None


def _batch_translate_with_claude(texts: list[str], batch_size: int = 25) -> list[str] | None:
    """Translate multiple texts in batched Claude API calls. Returns None if unavailable."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None

    all_results: list[str] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        numbered = "\n".join(f"[{j+1}] {t}" for j, t in enumerate(batch))
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Translate each numbered text below to English. "
                        f"Return ONLY the translations, one per line, keeping the same [N] numbering. "
                        f"Do not add any other text.\n\n{numbered}"
                    ),
                }],
            )
            reply = response.content[0].text.strip()
            # Parse numbered responses
            translations = {}
            for line in reply.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Match [N] prefix
                import re as _re
                m = _re.match(r"\[(\d+)\]\s*(.*)", line)
                if m:
                    translations[int(m.group(1))] = m.group(2)

            for j, t in enumerate(batch):
                all_results.append(translations.get(j + 1, t))
        except Exception:
            # If batch fails, return None so caller falls back
            return None

    return all_results if len(all_results) == len(texts) else None


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


def batch_back_translate(texts: list[str]) -> list[str]:
    """Translate a list of texts to English in as few API calls as possible."""
    # Try Claude batch first
    results = _batch_translate_with_claude(texts)
    if results:
        return results

    # Fall back to one-by-one Google Translate
    return [back_translate(t) for t in texts]


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

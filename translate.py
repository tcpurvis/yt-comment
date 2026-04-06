from deep_translator import GoogleTranslator


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


def back_translate(text: str, source_lang: str) -> str:
    """Translate text from source_lang back to English."""
    try:
        translator = GoogleTranslator(source=source_lang, target="en")
        result = translator.translate(text)
        return result or text
    except Exception:
        return text


def add_back_translations(
    comments: list[dict], source_lang: str
) -> list[dict]:
    """Add back_translation field to each comment."""
    translator = GoogleTranslator(source=source_lang, target="en")
    for c in comments:
        try:
            result = translator.translate(c["comment"])
            c["back_translation"] = result or c["comment"]
        except Exception:
            c["back_translation"] = c["comment"]
        c["original_language"] = source_lang
    return comments

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from dotenv import load_dotenv
import json
import os

# Language code to language name mapping

LANG_CODE_TO_NAME = {}

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _CONFIG = json.load(f)
    LANG_CODE_TO_NAME = _CONFIG.get("LANG_CODE_TO_NAME", {})

class TranslateRequest(BaseModel):
    texts: List[str]
    source_language: str
    target_languages: List[str]
    ai_model: Optional[str] = None
    hardcoded_translations: Optional[Dict[str, Dict[str, str]]] = None

class ValidateRequest(BaseModel):
    texts: List[str]
    ai_model: Optional[str] = None

class ConfigResponse(BaseModel):
    config: Dict

@app.get("/config", response_model=ConfigResponse)
def get_config():
    # Place your config.json in the same directory as this server.py file
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {"config": config}
        except Exception:
            return {"config": {}}
    else:
        return {"config": {}}

@app.post("/translate")
def translate(req: TranslateRequest):
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not found on server.")

    if not req.texts or not req.target_languages:
        return {"translations": {}}

    client = OpenAI(api_key=api_key)
    texts_list = list(req.texts)
    target_languages = list(req.target_languages)
    source_language = req.source_language
    ai_model = req.ai_model or "gpt-4.1-nano"
    hardcoded_translations = req.hardcoded_translations or {}
    retranslate = getattr(req, 'retranslate', False)
    full_source_language = LANG_CODE_TO_NAME.get(source_language, source_language)
    mapped_target_languages = [(lang, LANG_CODE_TO_NAME.get(lang, lang)) for lang in target_languages]

    # Build hardcoded translations reference for the prompt for all target languages
    hardcoded_examples = ""
    for lang_code, mapped_name in mapped_target_languages:
        if mapped_name in hardcoded_translations:
            language_translations = hardcoded_translations.get(mapped_name, {})
            if language_translations:
                hardcoded_examples += f"\n\nFor {lang_code}, prefer these translations when applicable:\n"
                for key, value in language_translations.items():
                    hardcoded_examples += f"- '{key}' → '{value}'\n"
    if hardcoded_examples:
        hardcoded_examples += "\nUse these preferred translations when the terms appear standalone or can be naturally incorporated."

    # Create format example for the prompt that works with any number of languages
    format_example_lines = []
    for lang_code, mapped_name in mapped_target_languages:
        format_example_lines.append(f"   {lang_code}: [translation]")
    format_example = "\n".join(format_example_lines)

    # Always return both first and retranslated results if retranslate is True
    keys_text = "\n".join([f"{i+1}. {key}" for i, key in enumerate(texts_list)])

    language_display = ', '.join([
        f"{mapped_name} ({lang_code})" for lang_code, mapped_name in mapped_target_languages
    ])
    target_names = {mapped_name for _, mapped_name in mapped_target_languages}
    specific_translate = (
        full_source_language == "English"
        and target_names == {"Traditional Chinese", "Simplified Chinese"}
    )
    try:
        # First translation
        if specific_translate:
            system_prompt_first = "\n".join([
                f"You are a professional translator. Translate the following numbered list of texts that appear on a website from {full_source_language} ({source_language}) to each of these languages: {language_display}.",
                "Instructions:",
                "Use formal written language only, not spoken or colloquial forms.",
                "For Traditional Chinese, use expressions and vocabulary as spoken and written by Cantonese speakers in Hong Kong.",
                "For Simplified Chinese, use expressions and vocabulary as spoken and written by Mainland China speakers.",
                "If it is appropriate, try to use similar sentence structure and vocabulary in both Traditional Chinese and Simplified Chinese translations, to maintain consistency and clarity across both versions.",
                "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
                f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
                f"Return ONLY the translations in this exact format without any explanations.{hardcoded_examples}"
            ])
        else:
            system_prompt_first = "\n".join([
                f"You are a professional translator. Translate the following numbered list of texts from {full_source_language} ({source_language}) to each of these languages: {language_display}.",
                "Instructions:",
                "Use formal written language only, not spoken or colloquial forms.",
                "Use regionally appropriate vocabulary, expressions, and tone.",
                "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
                f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
                f"Return ONLY the translations in this exact format without any explanations.{hardcoded_examples}"
            ])
        chat_params_first = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt_first,
                },
                {
                    "role": "user",
                    "content": keys_text,
                },
            ],
            "model": ai_model
        }
        if not ai_model.lower().startswith("gpt-5"):
            chat_params_first["temperature"] = 0.3
        chat_completion_first = client.chat.completions.create(**chat_params_first)
        translation_response_first = chat_completion_first.choices[0].message.content
        translations_first = {lang: {} for lang in target_languages}
        sections_first = translation_response_first.strip().split('\n\n')
        for i, original_key in enumerate(texts_list):
            if i < len(sections_first):
                section = sections_first[i].strip()
                lines = section.split('\n')
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    for target_language in target_languages:
                        if line.startswith(f"{target_language}:"):
                            translation = line[len(f"{target_language}:"):].strip()
                            if (translation.startswith('"') and translation.endswith('"')) or \
                               (translation.startswith("'") and translation.endswith("'")):
                                translation = translation[1:-1]
                            if not original_key.endswith('.') and translation.endswith('.'):
                                translation = translation.rstrip('.')
                            translations_first[target_language][original_key] = translation
                            break
        if retranslate:
            # Second translation (retranslation)
            first_translations = getattr(req, 'first_translations', {})
            re_keys_text = ""
            for i, key in enumerate(texts_list):
                re_keys_text += f"{i+1}. {key}\n"
                for lang in target_languages:
                    first_tr = first_translations.get(lang, {}).get(key, "")
                    re_keys_text += f"   {lang} (first): {first_tr}\n"
            if specific_translate:
                system_prompt_re = "\n".join([
                    f"You are a professional translator. The previous translations for these website texts were not satisfactory. Translate the following numbered list of texts that appear on a website from {full_source_language} ({source_language}) to each of these languages: {language_display}.",
                    "For each numbered text, you are given the original text and the first translation for each target language. Provide a different, better translation for each language.",
                    "Instructions:",
                    "DO NOT reuse the previous translations; provide NEW, improved translations.",
                    "Use formal written language only, not spoken or colloquial forms.",
                    "For Traditional Chinese, use expressions and vocabulary as spoken and written by Cantonese speakers in Hong Kong.",
                    "For Simplified Chinese, use expressions and vocabulary as spoken and written by Mainland China speakers.",
                    "If it is appropriate, try to use similar sentence structure and vocabulary in both Traditional Chinese and Simplified Chinese translations, to maintain consistency and clarity across both versions.",
                    "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
                    f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
                    f"Return ONLY the improved translations in this exact format without any explanations.{hardcoded_examples}"
                ])
            else:
                system_prompt_re = "\n".join([
                    f"You are a professional translator. The previous translations for these website texts were not satisfactory. Translate the following numbered list of texts from {full_source_language} ({source_language}) to each of these languages: {language_display}.",
                    "For each numbered text, you are given the original text and the first translation for each target language. Provide a different, better translation for each language.",
                    "Instructions:",
                    "DO NOT reuse the previous translations; provide NEW, improved translations.",
                    "Use formal written language only, not spoken or colloquial forms.",
                    "Use regionally appropriate vocabulary, expressions, and tone.",
                    "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
                    f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
                    f"Return ONLY the improved translations in this exact format without any explanations.{hardcoded_examples}"
                ])
            chat_params_re = {
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt_re,
                    },
                    {
                        "role": "user",
                        "content": re_keys_text,
                    },
                ],
                "model": ai_model
            }
            if not ai_model.lower().startswith("gpt-5"):
                chat_params_re["temperature"] = 0.3
            chat_completion_re = client.chat.completions.create(**chat_params_re)
            translation_response_re = chat_completion_re.choices[0].message.content
            translations_re = {lang: {} for lang in target_languages}
            sections_re = translation_response_re.strip().split('\n\n')
            for i, original_key in enumerate(texts_list):
                if i < len(sections_re):
                    section = sections_re[i].strip()
                    lines = section.split('\n')
                    for line in lines[1:]:
                        line = line.strip()
                        if not line:
                            continue
                        for target_language in target_languages:
                            if line.startswith(f"{target_language}:"):
                                translation = line[len(f"{target_language}:"):].strip()
                                if (translation.startswith('"') and translation.endswith('"')) or \
                                   (translation.startswith("'") and translation.endswith("'")):
                                    translation = translation[1:-1]
                                if not original_key.endswith('.') and translation.endswith('.'):
                                    translation = translation.rstrip('.')
                                translations_re[target_language][original_key] = translation
                                break
            return {"translations": translations_re}
        else:
            return {"translations": translations_first}
    except Exception as e:
        translations_first = {lang: {key: "" for key in texts_list} for lang in target_languages}
        return {"translations": translations_first, "error": str(e)}

@app.post("/validate")
def validate(req: ValidateRequest):
    from openai import OpenAI
    # Use environment variable for OpenAI key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not found on server.")

    if not req.texts:
        return {"validated": []}

    try:
        client = OpenAI(api_key=api_key)
        texts_list = list(req.texts)
        texts_content = "\n".join([f"{i+1}. {text}" for i, text in enumerate(texts_list)])
        validation_prompt = f"""You are reviewing text content found in a web application for translation purposes. \n\nFor each numbered text below, determine if it should be translated for international users or not.\n\nSHOULD BE TRANSLATED:\n- User-facing text content (buttons, labels, messages, descriptions, headings)\n- Error messages and notifications that users see\n- Complete sentences or phrases with semantic meaning that users will read\n- Navigation text, menu items, form labels\n- Standalone meaningful text without code context\n\nSHOULD NOT BE TRANSLATED:\n- CSS class names (like 'form-control', 'btn-primary', 'container-fluid', 'search-form')\n- HTML attribute values (like 'off', 'text', 'email', 'submit', 'button')\n- Database field names, API endpoints, or variable names\n- File names\n- Mixed code/text strings that contain PHP variables or functions (like "__('alt_prefix') . strip_tags($title)")\n- Partial code snippets or incomplete programming constructs\n- JavaScript class names or selectors\n- Any text that appears to be part of code rather than user-facing content\n\nCRITICAL RULES:\n1. If text contains programming keywords like 'new', '__', 'HtmlString', function calls, or appears within code syntax, it should NOT be translated\n2. If text looks like it was extracted from a line of code rather than standalone user content, it should NOT be translated  \nRespond with ONLY the numbers (separated by commas) of texts that SHOULD BE TRANSLATED.\n\nIf none should be translated, respond with 'NONE'.\n\nTexts to review:\n{texts_content}"""

        ai_model = req.ai_model or "gpt-4o-mini"
        chat_params = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert in internationalization and localization. You help identify which text content in web applications should be translated for international users."
                },
                {
                    "role": "user",
                    "content": validation_prompt
                }
            ],
            "model": ai_model
        }
        if not ai_model.lower().startswith("gpt-5"):
            chat_params["temperature"] = 0.1
        chat_completion = client.chat.completions.create(**chat_params)
        response = chat_completion.choices[0].message.content.strip()
        if response.upper() == "NONE":
            return {"validated": []}
        try:
            numbers = [int(num.strip()) for num in response.split(',')]
            validated_texts = [texts_list[i-1] for i in numbers if 1 <= i <= len(texts_list)]
            return {"validated": validated_texts}
        except (ValueError, IndexError):
            # If parsing fails, return all texts
            return {"validated": texts_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI validation failed: {e}")
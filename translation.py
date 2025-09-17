import os
import json
import warnings
from ctypes import cdll, c_void_p
from tree_sitter import Language, Parser
import argparse
import requests

# Suppress the specific DeprecationWarning from py-tree-sitter for cleaner output
warnings.filterwarnings("ignore", category=DeprecationWarning, message="int argument support is deprecated")

# --- Configuration ---
GRAMMAR_LIB_PATH = 'build/blade-grammar.so'
CONFIG_FILE_PATH = 'config.json'
API_SERVICE_ENDPOINT = 'http://localhost:8000/'
MAX_SERVICE_ENDPOINT = 'http://localhost:8080/tasks/translation/'

# --- Default configuration if config.json is not found ---
DEFAULT_CONFIG = {
    "source_language": "en",
    "translatable_attributes": ["placeholder", "image-alt", "aria-label"],
    "excluded_directories": [
        "dummy",
        "node_modules",
        "storage",
        "bootstrap",
        "vendor"
    ],
    "target_languages": ["zh_HK", "zh_CN"],
    "validate_ai_model": "gpt-4o-mini",
    "translate_ai_model": "gpt-4.1-nano",
    "use_cmscore_ai_first": False,
    "cmscore_ai_token": "arstneio",
    "hardcoded_translations": {
        "zh_HK": {
            "Skip to main content": "跳至主要內容",
            "Top": "置頂",
            "Home": "首頁",
            "Previous": "上一頁",
            "Next": "下一頁",
            "Play Slide": "播放幻燈片",
            "Pause Slide": "暫停幻燈片",
            "Upcoming": "即將舉行",
            "Highlight": "精選",
            "YYYY-MM-DD": "年-月-日",
            "Whatsapp": "Whatsapp",
            "Line": "Line",
            "Instagram": "Instagram",
            "LinkedIn": "LinkedIn",
            "Threads": "Threads"
        },
        "zh_CN": {
            "Skip to main content": "跳至主要内容",
            "Top": "置顶",
            "Home": "首页",
            "Previous": "上一页",
            "Next": "下一页",
            "Play Slide": "播放幻灯片",
            "Pause Slide": "暂停幻灯片",
            "Upcoming": "即将举行",
            "Highlight": "精选",
            "YYYY-MM-DD": "年-月-日",
            "Whatsapp": "Whatsapp",
            "Line": "Line",
            "Instagram": "Instagram",
            "LinkedIn": "LinkedIn",
            "Threads": "Threads"
        }
    }
}

def load_config():
    """Loads configuration: 1) FastAPI server, 2) fallback to default, 3) user config.json overwrites fields."""
    config = None
    # 1. Try FastAPI server config
    try:
        response = requests.get(API_SERVICE_ENDPOINT+"config", timeout=3)
        if response.status_code == 200:
            server_config = response.json().get("config", {})
            if server_config:
                print("Loaded configuration from FastAPI server.")
                config = DEFAULT_CONFIG.copy()
                config.update(server_config)
            else:
                print("⚠️ Warning: FastAPI server returned empty config. Using default config.")
                config = DEFAULT_CONFIG.copy()
        else:
            print(f"⚠️ Warning: FastAPI server returned status {response.status_code}. Using default config.")
            config = DEFAULT_CONFIG.copy()
    except Exception as e:
        print(f"⚠️ Warning: Could not fetch config from FastAPI server: {e}. Using default config.")
        config = DEFAULT_CONFIG.copy()

    # 2. If user config.json exists, overwrite only specified fields
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, 'r') as f:
                user_config = json.load(f)
                print("Loaded user configuration from config.json (overwriting fields)")
                for key, value in user_config.items():
                    config[key] = value
        except json.JSONDecodeError:
            print(f"⚠️ Warning: Could not parse {CONFIG_FILE_PATH}. Using previous config.")

    return config


def is_path_excluded(file_path, excluded_dirs):
    """
    Checks if a given file path is inside an excluded directory.
    Supports both simple directory names and specific path patterns.
    
    Examples:
    - 'component' will exclude any directory named 'component'
    - 'views/component' will only exclude 'component' directories inside 'views'
    """
    normalized_path = os.path.normpath(file_path)
    path_parts = normalized_path.split(os.sep)
    
    for excluded_pattern in excluded_dirs:
        # If the pattern contains path separators, treat it as a specific path pattern
        if '/' in excluded_pattern or os.sep in excluded_pattern:
            # Normalize the pattern to use the correct path separator
            pattern_parts = os.path.normpath(excluded_pattern).split(os.sep)
            
            # Check if this pattern sequence appears anywhere in the path
            for i in range(len(path_parts) - len(pattern_parts) + 1):
                if path_parts[i:i + len(pattern_parts)] == pattern_parts:
                    return True
        else:
            # Simple directory name - check if it appears anywhere in the path
            if excluded_pattern in path_parts:
                return True
    
    return False

def is_already_escaped(text):
    """
    Check if text is already escaped by looking for escaped quotes and backslashes.
    Returns True if the text appears to be already escaped.
    """
    # Simple heuristic: if we find \' or \\ in the text, it's likely already escaped
    # But we need to be careful not to confuse legitimate backslashes with escape sequences
    return "\\'" in text or "\\\\" in text

def unescape_php_string(text):
    """
    Unescape PHP string literals if needed.
    """
    return text.replace("\\'", "'").replace("\\\\", "\\")

def is_blade_directive(text):
    """
    Check if text is a Blade directive (not just any text starting with @).
    Returns True if it's likely a Blade directive, False if it's probably regular text.
    """
    if text.startswith('block('):
        return True
    if not text.startswith('@'):
        return False
    
    # Common Blade directives
    blade_directives = {
        'if', 'elseif', 'else', 'endif',
        'foreach', 'endforeach', 'for', 'endfor', 'while', 'endwhile',
        'switch', 'case', 'break', 'default', 'endswitch',
        'php', 'endphp', 'push', 'endpush', 'stack',
        'section', 'endsection', 'yield', 'show', 'stop',
        'include', 'extends', 'component', 'endcomponent',
        'slot', 'endslot', 'props', 'aware',
        'auth', 'endauth', 'guest', 'endguest',
        'can', 'endcan', 'cannot', 'endcannot',
        'error', 'enderror', 'empty', 'endempty',
        'isset', 'endisset', 'unless', 'endunless',
        'hasSection', 'sectionMissing', 'continue'
    }
    
    # Extract the directive name (everything after @ until first space or parenthesis)
    directive_part = text[1:]  # Remove @
    directive_name = directive_part.split('(')[0].split(' ')[0].strip()
    
    # Check if it's a known directive
    if directive_name in blade_directives:
        return True
    
    # Check for custom Blade directives (typically follow @word pattern)
    # If it looks like @word or @word(...), it's probably a directive
    # If it has spaces or other characters that don't fit the pattern, it's probably text
    if directive_name.isalpha() and (
        len(directive_part) == len(directive_name) or  # @word
        directive_part[len(directive_name):].startswith('(')  # @word(...)
    ):
        return True
    
    return False

def find_translatable_nodes(node, changes_list, translatable_attributes, original_content):
    """
    Recursively traverses the syntax tree and collects translatable nodes into a list.
    """
    # Part 1: Find Literal Text Nodes
    if node.type == 'text':
        original_text_bytes = node.text
        stripped_text = original_text_bytes.decode('utf8').strip()
        
        # Skip Blade directives (more specific matching)
        if is_blade_directive(stripped_text):
            return
        
        if stripped_text and not stripped_text.isnumeric() and len(stripped_text) > 1:
            start_offset = original_text_bytes.find(stripped_text.encode('utf8'))
            if start_offset != -1:
                start_byte = node.start_byte + start_offset
                end_byte = start_byte + len(stripped_text)
                
                # Check if text is already wrapped with __('...')
                pure_text = is_already_wrapped(original_content, start_byte, end_byte)
                if pure_text is not None:
                    # Text is wrapped, extract the pure content
                    change = {
                        'text': pure_text,
                        'start_byte': start_byte,
                        'end_byte': end_byte,
                        'line': node.start_point[0] + 1
                    }
                    changes_list.append(change)
                    print(f"Found wrapped literal text (extracted): '{pure_text}' at Line {change['line']}")
                else:
                    # Text is not wrapped, use as is
                    change = {
                        'text': stripped_text,
                        'start_byte': start_byte,
                        'end_byte': end_byte,
                        'line': node.start_point[0] + 1
                    }
                    changes_list.append(change)
                    print(f"Found Literal Text: '{stripped_text}' at Line {change['line']}")

    # Part 2: Find Translatable Attributes
    if node.type == 'attribute':
        attr_name_node = node.children[0]
        original_attr = attr_name_node.text.decode('utf8')
        attr_name = original_attr.lstrip(':')
        is_dynamic_attribute = len(original_attr) != len(attr_name)

        if attr_name in translatable_attributes and len(node.children) > 2:
            attr_value_node = node.children[2]
            
            if attr_value_node.type == 'quoted_attribute_value':
                for child in attr_value_node.children:
                    if child.type == 'attribute_value':
                        attr_text = child.text.decode('utf8')
                        stripped_attr_text = attr_text.strip()

                        if stripped_attr_text.startswith("$"):
                            break

                        if stripped_attr_text and not stripped_attr_text.isnumeric() and len(stripped_attr_text) > 1:
                            start_offset = attr_text.find(stripped_attr_text)
                            start_byte = child.start_byte + start_offset
                            end_byte = start_byte + len(stripped_attr_text)

                            # Check if attribute text is already wrapped with __('...')
                            pure_text = is_already_wrapped(original_content, start_byte, end_byte)
                            if pure_text is not None:
                                # Attribute is wrapped, extract and unescape the pure content
                                unescaped_pure_text = unescape_php_string(pure_text)
                                change = {
                                    'text': unescaped_pure_text,
                                    'start_byte': start_byte,
                                    'end_byte': end_byte,
                                    'line': child.start_point[0] + 1,
                                    'is_dynamic_attribute': is_dynamic_attribute,
                                    'attribute_name': attr_name
                                }
                                changes_list.append(change)
                                print(f"Found wrapped translatable attribute (extracted): {original_attr}, Text: '{unescaped_pure_text}' at Line {change['line']}")
                            else:
                                # Handle literal quotes in dynamic attributes and regular attributes
                                text_to_store = stripped_attr_text
                                
                                # For dynamic attributes with literal strings, remove outer quotes
                                if is_dynamic_attribute and stripped_attr_text.startswith("'") and stripped_attr_text.endswith("'"):
                                    text_to_store = stripped_attr_text[1:-1]  # Remove outer quotes
                                
                                # Unescape the text for clean storage
                                unescaped_text = unescape_php_string(text_to_store)
                                
                                change = {
                                    'text': unescaped_text,
                                    'start_byte': start_byte,
                                    'end_byte': end_byte,
                                    'line': child.start_point[0] + 1,
                                    'is_dynamic_attribute': is_dynamic_attribute,
                                    'attribute_name': attr_name
                                }
                                changes_list.append(change)
                                print(f"Found Translatable Attribute: {original_attr}, Text: '{unescaped_text}' at Line {change['line']}")
            elif attr_value_node.type == 'attribute_value':
                print(f"⚠️ Warning: Quotes are missing in Attribute '{original_attr}' at Line {attr_value_node.start_point[0] + 1}")

    # Recursively check all children
    for child in node.children:
        find_translatable_nodes(child, changes_list, translatable_attributes, original_content)


def is_already_wrapped(original_content, start_byte, end_byte):
    """
    Checks if the text at the given position is already wrapped with __('...') localization syntax.
    Returns the pure text content if wrapped, None if not wrapped.
    """
    try:
        # Get the actual text at the position
        actual_text = original_content[start_byte:end_byte].decode('utf8', errors='ignore')
        
        # If the actual text starts with __(' and ends with '), then it's wrapped
        if actual_text.startswith("__('") and actual_text.endswith("')"):
            # Extract the pure text content between __(' and ')
            pure_text = actual_text[4:-2]
            return pure_text
            
    except UnicodeDecodeError:
        # If we can't decode the content, assume it's not wrapped
        pass
    
    return None

def apply_changes(original_content, changes, is_interactive=False):
    """
    Applies the collected changes to the original file content, with an interactive option.
    """
    # Sort changes by start_byte in reverse order to avoid messing up indices
    changes.sort(key=lambda c: c['start_byte'], reverse=True)
    
    modified_content = original_content
    changes_applied = 0
    approved_changes = []  # Track changes that user approved
    
    for change in changes:
        start = change['start_byte']
        end = change['end_byte']
        text_to_wrap = change['text']
        is_attribute = 'attribute_name' in change
        is_dynamic = change.get('is_dynamic_attribute', False)
        
        # Check if already wrapped with __('')
        already_wrapped_pure_text = is_already_wrapped(modified_content, start, end)
        already_wrapped = already_wrapped_pure_text is not None
        
        approved = False
        if is_interactive:
            print("-" * 50)
            if already_wrapped and not is_attribute:
                print(f"Found __('') wrapped literal text on line {change['line']}: '{text_to_wrap}' - will add {{{{ }}}}")
            elif already_wrapped and is_attribute and not is_dynamic:
                print(f"Found __('') wrapped static attribute on line {change['line']}: '{text_to_wrap}' - will add {{!! !!}}")
            elif already_wrapped and is_attribute and is_dynamic:
                print(f"Found __('') wrapped dynamic attribute on line {change['line']}: '{text_to_wrap}' - already properly wrapped")
                approved_changes.append(change)
                continue
            else:
                print(f"Found on line {change['line']}: '{text_to_wrap}'")
            choice = input("Apply this change? (y/n): ").strip().lower()
            if choice == 'y':
                approved = True
            else:
                print("Skipping this change.")
        else:
            approved = True

        if approved:
            approved_changes.append(change)
            
            if already_wrapped:
                # Text is already wrapped with __('...'), get the original wrapped text
                original_wrapped = original_content[start:end].decode('utf8', errors='ignore')
                
                if is_attribute:
                    if is_dynamic:
                        # Dynamic attribute: keep __('...') as-is
                        wrapped_text = original_wrapped
                    else:
                        # Static attribute: add quotes and {!! !!} around the existing __('...')
                        wrapped_text = f"{{!! {original_wrapped} !!}}"
                else:
                    # Text node: add {{ }} around the existing __('...')
                    wrapped_text = f"{{{{ {original_wrapped} }}}}"
                
                # Replace the entire wrapped text
                modified_content = modified_content[:start] + wrapped_text.encode('utf8') + modified_content[end:]
            else:
                # Text is not wrapped, apply normal wrapping
                # Check if text is already escaped to avoid double-escaping
                if is_already_escaped(text_to_wrap):
                    # Text is already escaped, use as-is
                    escaped_text = text_to_wrap
                    print(f"  Text appears already escaped, using as-is: '{text_to_wrap}'")
                else:
                    # Text needs escaping
                    escaped_text = text_to_wrap.replace('\\', '\\\\').replace("'", "\\'")
                
                if is_attribute:
                    if is_dynamic:
                        wrapped_text = f"__('{escaped_text}')"
                    else:
                        wrapped_text = f"{{!! __(\'{escaped_text}\') !!}}"
                else:
                    wrapped_text = f"{{{{ __('{escaped_text}') }}}}"
                
                modified_content = modified_content[:start] + wrapped_text.encode('utf8') + modified_content[end:]
            
            changes_applied += 1
    
    # Replace the original changes list with only approved changes
    if is_interactive:
        changes.clear()
        changes.extend(approved_changes)
            
    if changes_applied > 0:
        print(f"Applied {changes_applied} changes.")
    return modified_content

def validate_translatable_content(texts_to_validate, ai_model):
    """
    Uses FastAPI backend to validate if text content is actually meaningful for translation.
    Returns a list of texts that should be translated.
    """
    if not texts_to_validate:
        return []
    try:
        response = requests.post(
            API_SERVICE_ENDPOINT+"validate",
            json={"texts": list(texts_to_validate), "ai_model": ai_model},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            validated = data.get("validated", [])
            removed_count = len(texts_to_validate) - len(validated)
            if removed_count > 0:
                print(f"🔍 AI Validation: Removed {removed_count} non-semantic texts from translation queue")
                removed_texts = [text for text in texts_to_validate if text not in validated]
                for removed in removed_texts:
                    print(f"  ❌ Removed: '{removed}'")
            if not validated:
                print("🔍 AI Validation: No texts deemed suitable for translation")
            return validated
        else:
            print(f"⚠️ Warning: FastAPI /validate returned status {response.status_code}. Proceeding with all original texts.")
            return texts_to_validate
    except Exception as e:
        print(f"⚠️ Warning: Could not reach FastAPI /validate endpoint: {e}")
        print("Proceeding with all original texts.")
        return texts_to_validate

def process_file(file_path, parser, is_interactive, translatable_attributes, validate_ai_model, validate=False):
    """
    Processes a single Blade file and returns a list of new keys found.
    """
    print(f"\n--- Scanning file: {file_path} ---\n")
    with open(file_path, 'rb') as f:
        blade_content = f.read()

    tree = parser.parse(blade_content)
    root_node = tree.root_node

    nodes_to_wrap = []
    find_translatable_nodes(root_node, nodes_to_wrap, translatable_attributes, blade_content)

    if not nodes_to_wrap:
        print("No new translatable text found.")
        return []

    # AI validation step - filter out non-semantic content (if enabled)
    if validate:
        original_texts = [change['text'] for change in nodes_to_wrap]
        validated_texts = validate_translatable_content(original_texts, validate_ai_model)
        
        # Filter nodes_to_wrap to only include validated texts
        if len(validated_texts) < len(original_texts):
            validated_nodes = []
            for change in nodes_to_wrap:
                if change['text'] in validated_texts:
                    validated_nodes.append(change)
            nodes_to_wrap = validated_nodes
            
            if not nodes_to_wrap:
                print("No semantically meaningful text found after AI validation.")
                return []

    modified_content = apply_changes(blade_content, nodes_to_wrap, is_interactive)

    with open(file_path, 'wb') as f:
        f.write(modified_content)
        
    print(f"Successfully updated file: {file_path}")
    
    # Return a list of unique text strings found in this file
    return list(set([change['text'] for change in nodes_to_wrap]))

def update_lang_file(lang_code, new_keys, lang_dir='../lang', is_interactive=False):
    """
    Updates a specific language JSON file with new keys.
    If is_interactive=True, prompts user when existing keys would be overwritten.
    """
    if not os.path.exists(lang_dir):
        os.makedirs(lang_dir, exist_ok=True)
        abs_dir = os.path.abspath(lang_dir)
        print(f"✅ Created language directory at: {abs_dir}")

    file_path = os.path.join(lang_dir, f"{lang_code}.json")

    # Ensure the language file exists
    if not os.path.exists(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        print(f"✅ Created language file: {os.path.abspath(file_path)}")

    existing_translations = {}
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                existing_translations = json.load(f)
            except json.JSONDecodeError:
                print(f"⚠️ Warning: Could not parse existing JSON file: {file_path}")

    # Check for existing keys and handle them based on interactive mode
    keys_to_update = {}
    conflicting_keys = {}
    
    for key, new_value in new_keys.items():
        if key in existing_translations and existing_translations[key].strip():
            # Key exists and has a non-empty value
            existing_value = existing_translations[key]
            if existing_value != new_value:
                # Values are different
                conflicting_keys[key] = {
                    'existing': existing_value,
                    'new': new_value
                }
            else:
                # Values are the same, no conflict
                keys_to_update[key] = new_value
        else:
            # Key doesn't exist or is empty, safe to add
            keys_to_update[key] = new_value
    
    # Handle conflicting keys
    if conflicting_keys and is_interactive:
        print(f"\n--- ⚠️Found existing translation conflicts in {lang_code}.json ---")
        for key, values in conflicting_keys.items():
            print(f"\nKey: '{key}'")
            print(f"Existing translation: '{values['existing']}'")
            print(f"New translation: '{values['new']}'")

            while True:
                choice = input("Keep which version? (e)existing / (n)ew: ").strip().lower()
                if choice in ['e', 'existing']:
                    # Keep existing, don't update
                    print(f"✅ Keeping existing translation for '{key}'")
                    break
                elif choice in ['n', 'new']:
                    # Use new translation
                    keys_to_update[key] = values['new']
                    print(f"✅ Using new translation for '{key}'")
                    break
                else:
                    print("Please enter 'e' or 'n'")
    elif conflicting_keys and not is_interactive:
        # Non-interactive mode: keep existing translations, report conflicts
        print(f"\n⚠️ Found {len(conflicting_keys)} conflicting keys in {lang_code}.json:")
        for key, values in conflicting_keys.items():
            print(f"  '{key}': keeping existing '{values['existing']}' (new was '{values['new']}')")
        # Don't update conflicting keys in non-interactive mode
    
    # Apply the updates
    if keys_to_update:
        existing_translations.update(keys_to_update)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(existing_translations, f, indent=4, ensure_ascii=False)
        
        print(f"Updated language file: {file_path} ({len(keys_to_update)} keys)")
    else:
        print(f"No updates needed for: {file_path}")

def filter_existing_keys(keys_to_check, target_language, lang_dir='../lang'):
    """
    Filters out keys that already exist in the target language file.
    Returns a new set with only the keys that need translation.
    """
    lang_file_path = os.path.join(lang_dir, f"{target_language}.json")
    existing_translations = {}
    
    if os.path.exists(lang_file_path):
        try:
            with open(lang_file_path, 'r', encoding='utf-8') as f:
                existing_translations = json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ Warning: Could not parse existing JSON file: {lang_file_path}")
    
    # Create a copy and remove existing keys
    filtered_keys = set(keys_to_check)
    original_count = len(filtered_keys)
    filtered_keys = {key for key in filtered_keys if key not in existing_translations or not existing_translations.get(key, '').strip()}
    
    if original_count > len(filtered_keys):
        print(f"\nFound {original_count - len(filtered_keys)} existing translations for {target_language}, skipping those keys")
    
    return filtered_keys

def gen_format_example(target_languages):
    format_example_lines = []
    for lang in target_languages:
        format_example_lines.append(f"   {lang}: [translation]")
    return "\n".join(format_example_lines)

def gen_hardcoded_example(hardcoded_translations, target_languages):
    hardcoded_examples = ""
    for target_language in target_languages:
        if target_language in hardcoded_translations:
            language_translations = hardcoded_translations.get(target_language, {})
            if language_translations:
                hardcoded_examples += f"\n\nFor {target_language}, prefer these translations when applicable:\n"
                for key, value in language_translations.items():
                    hardcoded_examples += f"- '{key}' → '{value}'\n"
    if hardcoded_examples:
        hardcoded_examples += "\nUse these preferred translations when the terms appear standalone or can be naturally incorporated."
    return hardcoded_examples

def parse_request_output(response_text, texts_list, target_languages):
    translations = {lang: {} for lang in target_languages}
    sections = response_text.strip().split('\n\n')
    for i, original_key in enumerate(texts_list):
        if i < len(sections):
            section = sections[i].strip()
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
                        translations[target_language][original_key] = translation
                        break
    return {"translations": translations}

def translate_and_save(keys_to_translate, source_language, target_languages, ai_model, cmscore_ai_token, hardcoded_translations=None, use_cmscore_ai_first=False, is_interactive=False):
    """
    Translates keys using OpenAI and saves them to language files.
    """
    print(f"\n--- Translating {len(keys_to_translate)} keys to {', '.join(target_languages)}... ---")
    keys_list = list(keys_to_translate)
    translated_keys_by_language = {lang: {} for lang in target_languages}
    using_cmscore_ai = use_cmscore_ai_first
    primary_endpoint = API_SERVICE_ENDPOINT+"translate"
    secondary_endpoint = MAX_SERVICE_ENDPOINT+ai_model
    primary_headers = None
    primary_body = {
        "texts": keys_list,
        "source_language": source_language,
        "target_languages": target_languages,
        "ai_model": ai_model,
        "hardcoded_translations": hardcoded_translations,
        "retranslate": False
    }
    secondary_headers = {
        "Authorization": f"Bearer {cmscore_ai_token}",
        "Content-Type": "application/json"
    }

    format_example = gen_format_example(target_languages)
    hardcoded_examples = gen_hardcoded_example(hardcoded_translations, target_languages)

    keys_text = "\n".join([f"{i+1}. {key}" for i, key in enumerate(keys_list)])

    system_prompt_first = "\n".join([
        f"You are a professional translator. Translate the following numbered list of texts from {source_language} to each of these languages: {', '.join(target_languages)}.",
        "Instructions:",
        "Use formal written language only, not spoken or colloquial forms.",
        "Use regionally appropriate vocabulary, expressions, and tone.",
        "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
        f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
        f"Return ONLY the translations in this exact format without any explanations.{hardcoded_examples}"
    ])

    secondary_body = {
        "state": {
            "prompt": [
                {
                    "role": "system",
                    "content": system_prompt_first
                },
                {
                    "role": "user",
                    "content": "Translate the following text based on the instructions. You can refer to <context> to reference similar text.\n<context>\n{context}\n</context>\n"+keys_text
                }
            ]
        }
    }
    if use_cmscore_ai_first:
        primary_endpoint, secondary_endpoint = secondary_endpoint, primary_endpoint
        primary_headers, secondary_headers = secondary_headers, primary_headers
        primary_body, secondary_body = secondary_body, primary_body

    try:
        response = requests.post(
            primary_endpoint,
            json=primary_body,
            headers=primary_headers,
            timeout=60
        )
    except Exception as e:
        print(f"❌ Error: Primary translation endpoint exception: {e}")
        response = None

    if not response or response.status_code != 200:
        print(f"⚠️ Warning: Translation request to {primary_endpoint} failed, retrying...")
        using_cmscore_ai = not using_cmscore_ai
        try:
            response = requests.post(
                secondary_endpoint,
                json=secondary_body,
                headers=secondary_headers,
                timeout=60
            )
        except Exception as e:
            print(f"❌ Error: Secondary translation endpoint exception: {e}")
            response = None

    if response and response.status_code == 200:
        if using_cmscore_ai:
            translations = parse_request_output(response.json(), keys_list, target_languages).get("translations", {})
        else:
            translations = response.json().get("translations", {})
        if is_interactive:
            keys_to_retranslate = []
            # Store first translation for later reference
            first_translations = {lang: dict(translations.get(lang, {})) for lang in target_languages}
            for original_key in keys_list:
                print(f"\n--- Translation Review ---")
                print(f"Original: '{original_key}'")
                for lang in target_languages:
                    translation = translations.get(lang, {}).get(original_key, original_key)
                    print(f"{lang}: '{translation}'")
                while True:
                    choice = input("Accept these translations? (y)es / (r)etranslate / (m)anual: ").strip().lower()
                    if choice in ['y', 'yes']:
                        for lang in target_languages:
                            translated_keys_by_language[lang][original_key] = translations.get(lang, {}).get(original_key, original_key)
                            print(f"✅ Accepted {lang}: '{original_key}' -> '{translations.get(lang, {}).get(original_key, original_key)}'")
                        break
                    elif choice in ['r', 'retranslate']:
                        keys_to_retranslate.append(original_key)
                        print(f"🔄 Marked '{original_key}' for retranslation.")
                        break
                    elif choice in ['m', 'manual']:
                        for lang in target_languages:
                            manual_translation = input(f"Enter manual translation for {lang}: ").strip()
                            translated_keys_by_language[lang][original_key] = manual_translation
                            print(f"✅ Using manual {lang}: '{original_key}' -> '{manual_translation}'")
                        break
                    else:
                        print("Please enter 'y', 'r', or 'm'")
            # Batch retranslate for all marked keys
            if keys_to_retranslate:
                print(f"\n--- Retranslating {len(keys_to_retranslate)} keys ---")
                # Prepare retranslation payload: include first translations for each key and language
                first_translations_payload = {}
                for lang in target_languages:
                    first_translations_payload[lang] = {
                        key: first_translations.get(lang, {}).get(key, "")
                        for key in keys_to_retranslate
                    }
                if use_cmscore_ai_first:
                    secondary_retranslate_body = {
                        "texts": keys_to_retranslate,
                        "source_language": source_language,
                        "target_languages": target_languages,
                        "ai_model": ai_model,
                        "hardcoded_translations": hardcoded_translations,
                        "retranslate": True,
                        "first_translations": first_translations_payload
                    }
                else:
                    system_prompt_re = "\n".join([
                        f"You are a professional translator. The previous translations for these website texts were not satisfactory. Translate the following numbered list of texts from {source_language} to each of these languages: {', '.join(target_languages)}.",
                        "For each numbered text, you are given the original text and the first translation for each target language. Provide a different, better translation for each language.",
                        "Instructions:",
                        "Use formal written language only, not spoken or colloquial forms.",
                        "Use regionally appropriate vocabulary, expressions, and tone.",
                        "Adapt meaning for clarity and naturalness in a web context; do not translate word-for-word.",
                        f"For each numbered text, provide translations for all languages in this format:\n\n1. [Original text]\n{format_example}\n\n2. [Next text]\n{format_example}",
                        f"Return ONLY the improved translations in this exact format without any explanations.{hardcoded_examples}"
                    ])

                    re_keys_text = ""
                    for i, key in enumerate(keys_to_retranslate):
                        re_keys_text += f"{i+1}. {key}\n"
                        for lang in target_languages:
                            first_tr = first_translations_payload.get(lang, {}).get(key, "")
                            re_keys_text += f"   {lang} (first): {first_tr}\n"

                    secondary_retranslate_body = {
                        "state": {
                            "prompt": [
                                {
                                    "role": "system",
                                    "content": system_prompt_re
                                },
                                {
                                    "role": "user",
                                    "content": "Translate the following text based on the instructions. You can refer to <context> to reference similar text.\n<context>\n{context}\n</context>\n"+re_keys_text
                                }
                            ]
                        }
                    }
                try:
                    response = requests.post(
                        secondary_endpoint,
                        json=secondary_retranslate_body,
                        headers=secondary_headers,
                        timeout=60
                    )
                except Exception as e:
                    print(f"❌ Error: Secondary translation endpoint exception: {e}")
                    response = None
                if response and response.status_code == 200:
                    if use_cmscore_ai_first:
                        retranslate_results = response.json().get("translations", {})
                    else:
                        retranslate_results = parse_request_output(response.json(), keys_list, target_languages).get("translations", {})
                    for original_key in keys_to_retranslate:
                        print(f"\n--- Retranslation Review ---")
                        print(f"Original: '{original_key}'")
                        for lang in target_languages:
                            first_translation = first_translations.get(lang, {}).get(original_key, original_key)
                            retranslation = retranslate_results.get(lang, {}).get(original_key, original_key)
                            print(f"{lang} (1st): '{first_translation}'")
                            print(f"{lang} (re): '{retranslation}'")
                            while True:
                                choice = input(f"Choose translation for {lang}: (1) First / (2) Retranslation / (m) Manual: ").strip().lower()
                                if choice == '1':
                                    translated_keys_by_language[lang][original_key] = first_translation
                                    print(f"✅ Using first translation for {lang}: '{original_key}' -> '{first_translation}'")
                                    break
                                elif choice == '2':
                                    translated_keys_by_language[lang][original_key] = retranslation
                                    print(f"✅ Using retranslation for {lang}: '{original_key}' -> '{retranslation}'")
                                    break
                                elif choice == 'm':
                                    manual_translation = input(f"Enter manual translation for {lang}: ").strip()
                                    translated_keys_by_language[lang][original_key] = manual_translation
                                    print(f"✅ Using manual {lang}: '{original_key}' -> '{manual_translation}'")
                                    break
                                else:
                                    print("Please enter '1', '2', or 'm'")
                else:
                    print(f"❌ Error: Secondary translation endpoint retranslate failed with status {response.status_code}")
                    print(f"Falling back to first translation for all retranslated keys.")
                    for original_key in keys_to_retranslate:
                        for lang in target_languages:
                            first_translation = first_translations.get(lang, {}).get(original_key, original_key)
                            translated_keys_by_language[lang][original_key] = first_translation
                            print(f"✅ Fallback: Using first translation for {lang}: '{original_key}' -> '{first_translation}'")
        else:
            for lang in target_languages:
                for original_key in keys_list:
                    translation = translations.get(lang, {}).get(original_key, original_key)
                    translated_keys_by_language[lang][original_key] = translation
                    print(f"  {lang}: '{original_key}' -> '{translation}'")
    else:
        print(f"❌ Error: Translation endpoint failed with status {response.status_code}")
        for lang in target_languages:
            for original_key in keys_list:
                translated_keys_by_language[lang][original_key] = ""
    # Update language files for all target languages
    for target_language in target_languages:
        update_lang_file(target_language, translated_keys_by_language[target_language], is_interactive=is_interactive)

def main():
    """
    Main function to handle arguments and run the parser.
    """
    parser = argparse.ArgumentParser(description='Process Blade files for localization')
    parser.add_argument('files', nargs='+', help='One or more Blade files or directories to process')
    parser.add_argument('--interactive', '-i', action='store_true', help='Run in interactive mode, prompting for each change')
    parser.add_argument('--no-translate', action='store_true', help='Wrap text but do not call translation APIs.')
    parser.add_argument('--validate', '-v',  action='store_true', help='Use AI to validate if text content should be translated (removes technical/non-semantic text)')
    args = parser.parse_args()

    config = load_config()
    source_language = config['source_language']
    translatable_attributes = config['translatable_attributes']
    excluded_directories = config['excluded_directories']
    target_languages = config['target_languages'] 
    validate_ai_model = config['validate_ai_model']
    translate_ai_model = config['translate_ai_model']
    use_cmscore_ai_first = config['use_cmscore_ai_first']
    cmscore_ai_token = config['cmscore_ai_token']
    hardcoded_translations = config['hardcoded_translations']

    if not os.path.exists(GRAMMAR_LIB_PATH):
        print(f"❌ Error: Grammar library not found at '{GRAMMAR_LIB_PATH}'")
        return

    lib = cdll.LoadLibrary(GRAMMAR_LIB_PATH)
    
    # 2. Get the language function pointer from the library.
    language_function = getattr(lib, 'tree_sitter_blade')
    
    # 3. Tell ctypes that the function returns a C pointer (void*).
    language_function.restype = c_void_p
    
    # 4. Call the function to get the actual pointer value (as an integer).
    language_pointer = language_function()

    # 5. Create the Language object using the integer pointer.
    blade_language = Language(language_pointer)
    
    parser = Parser(blade_language)

    all_new_keys = set()
    file_found = False
    for path_arg in args.files:
        if os.path.isfile(path_arg):
            if path_arg.endswith('.blade.php') and not is_path_excluded(path_arg, excluded_directories):
                file_found = True
                new_keys_from_file = process_file(path_arg, parser, args.interactive, translatable_attributes, validate_ai_model, args.validate)
                all_new_keys.update(new_keys_from_file)
        elif os.path.isdir(path_arg):
            for root, dirs, files in os.walk(path_arg, topdown=True):
                dirs[:] = [d for d in dirs if d not in excluded_directories]
                
                for file in files:
                    if file.endswith('.blade.php'):
                        full_path = os.path.join(root, file)
                        if not is_path_excluded(full_path, excluded_directories):
                            file_found = True
                            new_keys_from_file = process_file(full_path, parser, args.interactive, translatable_attributes, validate_ai_model, args.validate)
                            all_new_keys.update(new_keys_from_file)
    if not file_found:
        print("No Blade files found to process. Please check your file paths or directories.")
        return

    print("\n--- Scan complete. ---")
    if all_new_keys:
        # Collect all filtered keys across all target languages
        all_filtered_keys = set()
        languages_needing_translation = []
        
        for target_language in target_languages:
            # Filter out keys that already exist in the target language
            filtered_new_keys = filter_existing_keys(all_new_keys, target_language)
            
            if filtered_new_keys:
                all_filtered_keys.update(filtered_new_keys)
                languages_needing_translation.append(target_language)
            else:
                print(f"\nAll keys for {target_language} already exist. No updates on {target_language}.json")
        
        # If any languages need translation, make a single API call for all
        if all_filtered_keys and languages_needing_translation:
            if not args.no_translate:
                translate_and_save(all_filtered_keys, source_language, languages_needing_translation, translate_ai_model, cmscore_ai_token, hardcoded_translations, use_cmscore_ai_first, args.interactive)
            else:
                # For --no-translate, create empty translations for each language
                for target_language in languages_needing_translation:
                    filtered_keys_for_lang = filter_existing_keys(all_new_keys, target_language)
                    empty_translations = {key: "" for key in filtered_keys_for_lang}
                    update_lang_file(target_language, empty_translations, is_interactive=args.interactive)
                    print(f"Added {len(filtered_keys_for_lang)} new empty keys to {target_language}.json for future translation")
    else:
        print("\nNo new translatable text found in the provided files. No updates made to language files.")
    print("\n--- Scan and translation process complete ---")

if __name__ == "__main__":
    main()

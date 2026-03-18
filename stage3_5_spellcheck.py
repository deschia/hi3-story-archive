import language_tool_python
from pathlib import Path
from utils import (
    load_json, save_json, load_config, load_progress, update_progress,
    logger, log_error, RAW_DIR, SPELLCHECKED_DIR, REVIEWED_DIR,
    PROGRESS_DIR, DICTIONARY_FILE, get_videos_at_stage
)


def load_dictionary():
    words = set()
    if DICTIONARY_FILE.exists():
        with open(DICTIONARY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    words.add(line.lower())
    return words


def save_dictionary(words):
    existing_comments = []
    if DICTIONARY_FILE.exists():
        with open(DICTIONARY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('#'):
                    existing_comments.append(line.rstrip())
    
    with open(DICTIONARY_FILE, 'w', encoding='utf-8') as f:
        for comment in existing_comments:
            f.write(comment + '\n')
        for word in sorted(words):
            f.write(word + '\n')


def is_in_dictionary(text, dictionary):
    if not text:
        return False
    return text.lower() in dictionary


def get_match_attr(match, *attrs):
    for attr in attrs:
        val = getattr(match, attr, None)
        if val is not None:
            return val
    return None


def calculate_match_confidence(match):
    rule_confidence = {
        'MORFOLOGIK_RULE_EN_US': 0.9,
        'UPPERCASE_SENTENCE_START': 0.7,
        'COMMA_PARENTHESIS_WHITESPACE': 0.95,
        'WHITESPACE_RULE': 0.95,
        'EN_QUOTES': 0.8,
        'SENTENCE_WHITESPACE': 0.9,
    }
    
    rule_id = get_match_attr(match, 'ruleId', 'rule_id') or ''
    if rule_id in rule_confidence:
        return rule_confidence[rule_id]
    
    replacements = get_match_attr(match, 'replacements') or []
    if replacements:
        return 0.85
    return 0.5


def process_text(tool, text, dictionary, threshold):
    if not text:
        return text, [], [], False
    
    matches = tool.check(text)
    corrections_applied = []
    flagged_issues = []
    corrected_text = text
    auto_corrected = False
    
    offset_adjustment = 0
    
    for match in matches:
        error_length = get_match_attr(match, 'errorLength', 'error_length') or len(get_match_attr(match, 'matchedText', 'matched_text') or '') or 1
        offset = get_match_attr(match, 'offset') or 0
        original_text = text[offset:offset + error_length]
        
        if is_in_dictionary(original_text, dictionary):
            continue
        
        confidence = calculate_match_confidence(match)
        replacements = get_match_attr(match, 'replacements') or []
        rule_id = get_match_attr(match, 'ruleId', 'rule_id') or ''
        
        if replacements:
            suggestion = replacements[0]
            
            if confidence >= threshold:
                corrected_text = (
                    corrected_text[:offset + offset_adjustment] +
                    suggestion +
                    corrected_text[offset + offset_adjustment + error_length:]
                )
                offset_adjustment += len(suggestion) - error_length
                
                corrections_applied.append({
                    "original": original_text,
                    "corrected": suggestion,
                    "type": "spelling" if "MORFOLOGIK" in rule_id else "grammar"
                })
                auto_corrected = True
            else:
                context_start = max(0, offset - 20)
                context_end = min(len(text), offset + error_length + 20)
                context = text[context_start:context_end]
                
                flagged_issues.append({
                    "text": original_text,
                    "suggestion": suggestion,
                    "type": "spelling" if "MORFOLOGIK" in rule_id else "grammar",
                    "context": f"...{context}..."
                })
    
    return corrected_text, corrections_applied, flagged_issues, auto_corrected


def spellcheck_entry(tool, entry, dictionary, threshold):
    try:
        original_speaker = entry.get("speaker")
        original_dialogue = entry.get("dialogue", "")
        
        corrected_dialogue, dialogue_corrections, dialogue_flags, dialogue_auto = process_text(
            tool, original_dialogue, dictionary, threshold
        )
        
        corrected_speaker, speaker_corrections, speaker_flags, speaker_auto = process_text(
            tool, original_speaker, dictionary, threshold
        )
        
        all_corrections = speaker_corrections + dialogue_corrections
        all_flags = speaker_flags + dialogue_flags
        auto_corrected = speaker_auto or dialogue_auto
        
        return {
            "timestamp": entry.get("timestamp"),
            "speaker": corrected_speaker,
            "dialogue": corrected_dialogue,
            "original_speaker": original_speaker,
            "original_dialogue": original_dialogue,
            "confidence": entry.get("confidence", 1.0),
            "frame": entry.get("frame"),
            "auto_corrected": auto_corrected,
            "corrections_applied": all_corrections,
            "flagged_issues": all_flags
        }
    except Exception as e:
        logger.error(f"Error processing entry: {e}")
        return {
            **entry,
            "original_speaker": entry.get("speaker"),
            "original_dialogue": entry.get("dialogue"),
            "auto_corrected": False,
            "corrections_applied": [],
            "flagged_issues": []
        }


def get_video_order():
    """Get video IDs in urls.txt order."""
    urls_path = Path(__file__).parent / "urls.txt"
    if not urls_path.exists():
        return None
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    from utils import extract_video_id
    return [extract_video_id(url) for url in urls if extract_video_id(url)]


def run_spellcheck(video_id=None):
    config = load_config()
    threshold = config.get("spellcheck_confidence_threshold", 0.85)
    
    SPELLCHECKED_DIR.mkdir(exist_ok=True)
    
    video_order = get_video_order()
    
    if video_id:
        video_ids = [video_id]
    elif video_order:
        completed = set(get_videos_at_stage("extract", "complete"))
        video_ids = [v for v in video_order if v in completed]
        video_ids = [v for v in video_ids if not (SPELLCHECKED_DIR / f"{v}.json").exists()]
    else:
        video_ids = get_videos_at_stage("extract", "complete")
        video_ids = [v for v in video_ids if not (SPELLCHECKED_DIR / f"{v}.json").exists()]
    
    if not video_ids:
        logger.info("No videos to spellcheck")
        return {"processed": 0, "skipped": 0}
    
    logger.info(f"Initializing LanguageTool...")
    try:
        tool = language_tool_python.LanguageTool('en-US')
    except Exception as e:
        logger.error(f"Failed to initialize LanguageTool: {e}")
        logger.error("Make sure Java is installed (required by language_tool_python)")
        return {"processed": 0, "errors": 1}
    
    dictionary = load_dictionary()
    logger.info(f"Loaded {len(dictionary)} custom dictionary words")
    
    stats = {"processed": 0, "skipped": 0, "errors": 0}
    
    for vid in video_ids:
        logger.info(f"Processing {vid}...")
        
        raw_path = RAW_DIR / f"{vid}.json"
        if not raw_path.exists():
            logger.warning(f"Raw file not found: {raw_path}")
            stats["skipped"] += 1
            continue
        
        spellchecked_path = SPELLCHECKED_DIR / f"{vid}.json"
        if spellchecked_path.exists():
            logger.info(f"Already spellchecked: {vid}")
            stats["skipped"] += 1
            continue
        
        update_progress(vid, "spellcheck", {"status": "in_progress"})
        
        try:
            raw_data = load_json(raw_path)
            entries = raw_data.get("entries", [])
            
            spellchecked_entries = []
            auto_corrected_count = 0
            flagged_count = 0
            errors = []
            
            total_entries = len(entries)
            for i, entry in enumerate(entries):
                print(f"\r  Processing entry {i + 1}/{total_entries}", end="", flush=True)
                try:
                    result = spellcheck_entry(tool, entry, dictionary, threshold)
                    spellchecked_entries.append(result)
                    
                    if result.get("auto_corrected"):
                        auto_corrected_count += 1
                    if result.get("flagged_issues"):
                        flagged_count += 1
                        
                except Exception as e:
                    error_msg = f"Entry {i}: {str(e)}"
                    errors.append(error_msg)
                    log_error(vid, error_msg)
                    spellchecked_entries.append({
                        **entry,
                        "original_speaker": entry.get("speaker"),
                        "original_dialogue": entry.get("dialogue"),
                        "auto_corrected": False,
                        "corrections_applied": [],
                        "flagged_issues": []
                    })
            
            print()
            
            output_data = {
                "video_id": vid,
                "entries": spellchecked_entries
            }
            save_json(spellchecked_path, output_data)
            
            update_progress(vid, "spellcheck", {
                "status": "complete",
                "entries_processed": len(entries),
                "auto_corrected_count": auto_corrected_count,
                "flagged_count": flagged_count,
                "errors": errors
            })
            
            logger.info(f"  Processed {len(entries)} entries, {auto_corrected_count} auto-corrected, {flagged_count} flagged")
            stats["processed"] += 1
            
        except Exception as e:
            error_msg = str(e)
            log_error(vid, error_msg)
            update_progress(vid, "spellcheck", {
                "status": "error",
                "errors": [error_msg]
            })
            stats["errors"] += 1
    
    tool.close()
    
    logger.info(f"Spellcheck complete: {stats}")
    return stats


def build_dictionary():
    existing_words = load_dictionary()
    new_words = set(existing_words)
    
    for reviewed_file in REVIEWED_DIR.glob("*.json"):
        try:
            data = load_json(reviewed_file)
            for entry in data.get("entries", []):
                if entry.get("reviewed", False) and not entry.get("deleted", False):
                    for field in ["speaker", "dialogue"]:
                        text = entry.get(field)
                        if text:
                            for word in text.split():
                                word = word.strip('.,!?"\'():;')
                                if word and len(word) > 1:
                                    new_words.add(word.lower())
        except Exception as e:
            logger.warning(f"Error reading {reviewed_file}: {e}")
    
    added = len(new_words) - len(existing_words)
    save_dictionary(new_words)
    
    logger.info(f"Dictionary updated: {len(new_words)} total words ({added} new)")
    return {"total": len(new_words), "added": added}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build-dictionary":
        build_dictionary()
    else:
        video_id = sys.argv[1] if len(sys.argv) > 1 else None
        run_spellcheck(video_id)

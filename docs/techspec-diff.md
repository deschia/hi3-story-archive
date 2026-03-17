# Techspec Diff: v1 → v2

## Summary

v2 introduces **Stage 3.5 (Spellcheck)** between Extract and Review stages, adding automated spelling/grammar correction with manual review integration. This requires changes to tools, directory structure, data schemas, progress tracking, and the Review UI.

---

## Change 1: New Tool Dependency

**Add to Tools table:**
| Tool | Purpose |
|------|---------|
| language_tool_python | Spelling and grammar correction |

**New system requirement:** Java runtime (required by language_tool_python)

---

## Change 2: New Directory

**Add to directory structure:**
```
├── hi3_dictionary.txt    # Custom dictionary for HI3 terms
├── spellchecked/         # Stage 3.5 output
│   └── {video_id}.json
```

---

## Change 3: Updated Data Flow Diagram

**Before (v1):**
```
Stage 1 → Stage 2 → Stage 3 → Stage 4 → Stage 5
Input    Acquire   Extract   Review    Output
```

**After (v2):**
```
Stage 1 → Stage 2 → Stage 3 → Stage 3.5 → Stage 4 → Stage 5
Input    Acquire   Extract   Spellcheck  Review    Output
```

---

## Change 4: New Stage 3.5 (Spellcheck)

**Tools:** Python, language_tool_python

**Input:**
- `raw/{video_id}.json`
- `hi3_dictionary.txt` (optional)

**Output:**
- `spellchecked/{video_id}.json`
- Updated `progress/{video_id}.json`

**Behavior:**
- Process raw OCR output through LanguageTool
- Auto-apply corrections with confidence >= 0.85
- Flag uncertain corrections for manual review
- Respect custom dictionary terms (character names, game-specific vocabulary)

**Spellchecked entry schema:**
```json
{
  "timestamp": 5,
  "speaker": "string or null",
  "dialogue": "string",
  "original_speaker": "string or null",
  "original_dialogue": "string",
  "confidence": 0.95,
  "frame": "frame_00005.png",
  "auto_corrected": true,
  "corrections_applied": [
    {"original": "teh", "corrected": "the", "type": "spelling"}
  ],
  "flagged_issues": [
    {"text": "Kiana", "suggestion": "Kiana's", "type": "grammar", "context": "..."}
  ]
}
```

**Fail behavior:** Skip entry on error, log error, continue processing.

---

## Change 5: New Custom Dictionary File

**File:** `hi3_dictionary.txt`

Contains game-specific terms to skip during spellcheck (character names, vocabulary).

**New CLI command:** `python main.py build-dictionary`
- Extracts speaker names from reviewed entries
- Builds/updates the dictionary file

---

## Change 6: Configuration Addition

**Add to `config.json`:**
```json
{
  "spellcheck_confidence_threshold": 0.85
}
```

---

## Change 7: Progress Tracking Schema Update

**Add new stage to `progress/{video_id}.json`:**

```json
{
  "status": "input | acquire | extract | spellcheck | review | complete",
  "stages": {
    "spellcheck": {
      "status": "pending | complete | error",
      "entries_processed": 0,
      "auto_corrected_count": 0,
      "flagged_count": 0,
      "errors": []
    }
  }
}
```

**Changes:**
- `status` enum adds `spellcheck` value
- `stages` object adds `spellcheck` key

---

## Change 8: Progress Query Interface Update

**Add spellcheck stats output:**
```python
if stage == "spellcheck":
    print(f"  Auto-corrected: {data.get('auto_corrected_count', 0)}")
    print(f"  Flagged: {data.get('flagged_count', 0)}")
```

---

## Change 9: Stage 4 (Review) Input Change

**Before:** Input from `raw/{video_id}.json`

**After:** Input from `spellchecked/{video_id}.json`

---

## Change 10: Stage 4 (Review) `init_reviewed()` Function Change

**Before:** Reads from `raw/` directory

**After:** Reads from `spellchecked/` directory

```python
SPELLCHECKED_DIR = Path("spellchecked")

def init_reviewed(video_id):
    spellchecked_path = SPELLCHECKED_DIR / f"{video_id}.json"
    # ... reads from spellchecked instead of raw
```

---

## Change 11: Stage 4 (Review) Dashboard Update

**Add spellcheck stats to video list:**
```python
videos.append({
    "video_id": progress["video_id"],
    "status": progress["status"],
    "review_progress": progress["stages"]["review"],
    "spellcheck_stats": progress["stages"]["spellcheck"]  # NEW
})
```

---

## Change 12: Stage 4 (Review) New API Route

**Add new route:**
- `GET /api/video/{video_id}/entries` - Paginated entries with filters

**Add new route:**
- `POST /video/{video_id}/flush` - Batch update entries

---

## Change 13: Stage 4 (Review) New Filter Options

**Add filter types to entries API:**
- `auto_corrected` - Entries with auto-applied corrections
- `flagged` - Entries with flagged issues needing review

```python
if filter_type == "auto_corrected":
    indexed_entries = [e for e in indexed_entries if e.get("auto_corrected", False)]
elif filter_type == "flagged":
    indexed_entries = [e for e in indexed_entries if e.get("flagged_issues")]
```

---

## Change 14: Stage 4 (Review) UI Diff View

**Add diff view for auto-corrected entries:**
- Display `original_speaker`/`original_dialogue` alongside corrected values
- Show list of `corrections_applied` with original → corrected mappings

**Add flagged issues display:**
- Show `flagged_issues` with text, suggestion, type, and context

---

## Change 15: New CLI Commands

**Add commands:**
```bash
python main.py spellcheck       # Run Stage 3.5
python main.py build-dictionary # Build custom dictionary from reviewed data
```

# HI3 Story Dialogue Archive - Technical Specification v2

## Task Summary

Archive Honkai Impact 3rd story dialogues from YouTube gameplay videos via OCR extraction. Process 200+ videos, extract subtitle text with speaker names, organize by chapter, and output as structured JSON files.

## Pipeline Technical Solution

### Tools

| Tool | Purpose |
|------|---------|
| Python 3.x | Pipeline orchestration, scripting |
| yt-dlp | Video metadata extraction, stream URL retrieval |
| ffmpeg | Frame extraction from video streams |
| EasyOCR | Optical character recognition |
| language_tool_python | Spelling and grammar correction |
| Flask | Review web UI |

### Directory Structure

```
project/
├── urls.txt              # Input URL list
├── config.json           # Pipeline configuration
├── hi3_dictionary.txt    # Custom dictionary for HI3 terms
├── metadata/             # Stage 1 output
│   └── {video_id}.json
├── frames/               # Stage 2 output
│   └── {video_id}/
│       ├── frame_00001.png
│       └── ...
├── raw/                  # Stage 3 output
│   └── {video_id}.json
├── spellchecked/         # Stage 3.5 output
│   └── {video_id}.json
├── reviewed/             # Stage 4 output
│   └── {video_id}.json
├── archive/              # Stage 5 output
│   └── {chapter}.json
└── progress/             # Progress tracking
    └── {video_id}.json
```

### Data Flow Diagram

```
urls.txt
    │
    ▼
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌────────────┐     ┌─────────┐     ┌─────────┐
│ Stage 1 │────>│ Stage 2 │────>│ Stage 3 │────>│ Stage 3.5  │────>│ Stage 4 │────>│ Stage 5 │
│  Input  │     │ Acquire │     │ Extract │     │ Spellcheck │     │ Review  │     │ Output  │
└─────────┘     └─────────┘     └─────────┘     └────────────┘     └─────────┘     └─────────┘
    │               │               │                 │                 │               │
    ▼               ▼               ▼                 ▼                 ▼               ▼
metadata/       frames/          raw/          spellchecked/       reviewed/       archive/
    │               │               │                 │                 │
    └───────────────┴───────────────┴─────────────────┴─────────────────┘
                                        │
                                        ▼
                                progress/{video_id}.json
```

---

## Stage 1: Input

### Tools
- Python
- yt-dlp

### Input
- `urls.txt` (one YouTube URL per line)

### Output
- `metadata/{video_id}.json`
- `progress/{video_id}.json` (initialized)

### Technical Solution

Read URLs from input file. Use yt-dlp to fetch video metadata without downloading. Extract video ID, title, upload date. Derive chapter name from title by splitting on `|` delimiter and taking the first segment. Skip videos already processed (incremental). Log errors for inaccessible videos.

**Metadata schema:**
```json
{
  "video_id": "string",
  "url": "string",
  "title": "string",
  "chapter": "string",
  "upload_date": "string"
}
```

**Chapter derivation:**
- Title format: `{Chapter Info} | Honkai Impact 3rd Story Mode Gameplay`
- Extract: split on `|`, trim whitespace, take first segment

**Fail behavior:** Log error to `errors.log`, continue to next URL.

### Pseudocode

```python
for url in read_lines("urls.txt"):
    video_id = extract_video_id(url)
    
    if file_exists(f"metadata/{video_id}.json"):
        continue
    
    result = run(f"yt-dlp --dump-json {url}")
    
    if result.error:
        log_error(video_id, result.error)
        continue
    
    metadata = parse_json(result.stdout)
    chapter = metadata["title"].split("|")[0].strip()
    
    save_json(f"metadata/{video_id}.json", {
        "video_id": video_id,
        "url": url,
        "title": metadata["title"],
        "chapter": chapter,
        "upload_date": metadata["upload_date"]
    })
    
    init_progress(video_id, url)
```

---

## Stage 2: Acquire

### Tools
- yt-dlp
- ffmpeg

### Input
- `metadata/{video_id}.json`
- `config.json` (subtitle crop coordinates)

### Output
- `frames/{video_id}/frame_XXXXX.png`
- Updated `progress/{video_id}.json`

### Technical Solution

For each video in metadata, retrieve direct stream URL via yt-dlp at 720p quality. Use ffmpeg to extract frames at 1 fps, cropped to subtitle region. Save frames with zero-padded sequential numbering. Track extraction progress for resume capability.

**Configuration (config.json):**
```json
{
  "subtitle_crop": {
    "width": 800,
    "height": 100,
    "x": 240,
    "y": 620
  },
  "video_quality": 720,
  "frame_rate": 1
}
```

**Resume support:**
- Track last extracted frame in `progress/{video_id}.json`
- On resume, use ffmpeg `-ss` to skip processed duration
- Mark complete when extraction finishes

**Fail behavior:** Log error, record last successful frame for resume, continue to next video.

### Pseudocode

```python
config = load_json("config.json")
crop = config["subtitle_crop"]
crop_filter = f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}"

for metadata_file in glob("metadata/*.json"):
    metadata = load_json(metadata_file)
    video_id = metadata["video_id"]
    
    progress = load_progress(video_id)
    if progress["stages"]["acquire"]["status"] == "complete":
        continue
    
    start_time = progress["stages"]["acquire"].get("last_frame", 0)
    
    stream_url = run(f"yt-dlp -g -f 'best[height<=720]' {metadata['url']}")
    
    if stream_url.error:
        log_error(video_id, stream_url.error)
        update_progress(video_id, "acquire", {"status": "error", "error": stream_url.error})
        continue
    
    mkdir(f"frames/{video_id}")
    
    ffmpeg_cmd = f"""
        ffmpeg -ss {start_time} -i "{stream_url.stdout}" 
        -vf "fps=1,{crop_filter}" 
        -start_number {start_time + 1}
        frames/{video_id}/frame_%05d.png
    """
    
    result = run(ffmpeg_cmd, on_frame=lambda n: update_progress(video_id, "acquire", {"last_frame": n}))
    
    if result.error:
        log_error(video_id, result.error)
        continue
    
    update_progress(video_id, "acquire", {"status": "complete", "frames_total": count_frames(video_id)})
```

### Calibration Tool

Separate script to determine subtitle crop coordinates from sample frame.

```python
# calibrate.py
# 1. Extract single frame from sample video at midpoint
# 2. Display frame in window
# 3. User draws rectangle over subtitle region
# 4. Save coordinates to config.json
```

---

## Stage 3: Extract

### Tools
- Python
- EasyOCR

### Input
- `frames/{video_id}/frame_XXXXX.png`

### Output
- `raw/{video_id}.json`
- Updated `progress/{video_id}.json`

### Technical Solution

Process frames sequentially. Run EasyOCR on each frame. Parse OCR result to extract speaker (first line) and dialogue (remaining lines). Deduplicate consecutive identical/similar text using 90% similarity threshold. Record confidence scores. Skip frames with empty OCR results.

**Subtitle format:**
```
Speaker Name       <- Line 1
Dialogue text...   <- Line 2+
```

Single line without speaker indicates narration.

**Raw extraction schema:**
```json
{
  "video_id": "string",
  "entries": [
    {
      "timestamp": 5,
      "speaker": "string or null",
      "dialogue": "string",
      "confidence": 0.95,
      "frame": "frame_00005.png"
    }
  ]
}
```

**Fail behavior:** Skip frame, log error, continue processing.

### Pseudocode

```python
import easyocr
from difflib import SequenceMatcher

reader = easyocr.Reader(['en'])
SIMILARITY_THRESHOLD = 0.90

def is_similar(text1, text2):
    if not text1 or not text2:
        return False
    return SequenceMatcher(None, text1, text2).ratio() >= SIMILARITY_THRESHOLD

for video_id in get_acquired_videos():
    progress = load_progress(video_id)
    if progress["stages"]["extract"]["status"] == "complete":
        continue
    
    frames = sorted(glob(f"frames/{video_id}/frame_*.png"))
    entries = []
    previous_text = None
    errors = []
    skipped = 0
    
    for frame_path in frames:
        frame_num = extract_frame_number(frame_path)
        timestamp = frame_num  # 1 fps means frame number = seconds
        
        try:
            result = reader.readtext(frame_path)
        except Exception as e:
            errors.append(f"{frame_path}: {str(e)}")
            continue
        
        if not result:
            skipped += 1
            continue
        
        text = "\n".join([r[1] for r in result])
        confidence = min([r[2] for r in result])
        
        if is_similar(text, previous_text):
            continue
        
        lines = text.strip().split("\n")
        if len(lines) >= 2:
            speaker = lines[0]
            dialogue = "\n".join(lines[1:])
        else:
            speaker = None
            dialogue = text
        
        entries.append({
            "timestamp": timestamp,
            "speaker": speaker,
            "dialogue": dialogue,
            "confidence": confidence,
            "frame": os.path.basename(frame_path)
        })
        
        previous_text = text
    
    save_json(f"raw/{video_id}.json", {"video_id": video_id, "entries": entries})
    
    low_confidence = sum(1 for e in entries if e["confidence"] < CONFIDENCE_THRESHOLD)
    
    update_progress(video_id, "extract", {
        "status": "complete",
        "frames_processed": len(frames),
        "frames_skipped": skipped,
        "entries_extracted": len(entries),
        "low_confidence_count": low_confidence,
        "errors": errors
    })
```

---

## Stage 3.5: Spellcheck

### Tools
- Python
- language_tool_python (requires Java runtime)

### Input
- `raw/{video_id}.json`
- `hi3_dictionary.txt` (optional)

### Output
- `spellchecked/{video_id}.json`
- Updated `progress/{video_id}.json`

### Technical Solution

Process raw OCR output through LanguageTool for spelling, grammar, punctuation, and capitalization corrections. Auto-apply corrections with confidence >= 0.85 threshold. Flag uncertain corrections for manual review in Stage 4. Respect custom dictionary terms (character names, game-specific vocabulary).

**Configuration addition (config.json):**
```json
{
  "spellcheck_confidence_threshold": 0.85
}
```

**Custom dictionary (`hi3_dictionary.txt`):**
```
Kiana
Mei
Bronya
Theresa
Himeko
Seele
Valkyrie
Stigmata
Hyperion
```

**Spellchecked entry schema:**
```json
{
  "video_id": "string",
  "entries": [
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
  ]
}
```

**Fail behavior:** Skip entry on error, log error, continue processing.

### Pseudocode

```python
import language_tool_python

CONFIDENCE_THRESHOLD = 0.85

def load_dictionary(path):
    if not file_exists(path):
        return set()
    return set(line.strip().lower() for line in read_lines(path))

def spellcheck_text(text, tool, custom_words, threshold):
    if not text:
        return text, [], []
    
    matches = tool.check(text)
    corrections_applied = []
    flagged_issues = []
    corrected_text = text
    offset_adjustment = 0
    
    for match in matches:
        original_word = text[match.offset:match.offset + match.errorLength]
        
        if original_word.lower() in custom_words:
            continue
        
        if not match.replacements:
            continue
        
        suggestion = match.replacements[0]
        correction_type = categorize_rule(match.ruleId)
        
        if match.confidence >= threshold:
            start = match.offset + offset_adjustment
            end = start + match.errorLength
            corrected_text = corrected_text[:start] + suggestion + corrected_text[end:]
            offset_adjustment += len(suggestion) - match.errorLength
            
            corrections_applied.append({
                "original": original_word,
                "corrected": suggestion,
                "type": correction_type
            })
        else:
            flagged_issues.append({
                "text": original_word,
                "suggestion": suggestion,
                "type": correction_type,
                "context": match.context
            })
    
    return corrected_text, corrections_applied, flagged_issues

def categorize_rule(rule_id):
    if "SPELL" in rule_id or "MORFOLOGIK" in rule_id:
        return "spelling"
    elif "GRAM" in rule_id:
        return "grammar"
    elif "PUNCT" in rule_id or "COMMA" in rule_id:
        return "punctuation"
    elif "CASE" in rule_id or "UPPER" in rule_id or "LOWER" in rule_id:
        return "capitalization"
    return "other"

tool = language_tool_python.LanguageTool('en-US')
custom_words = load_dictionary("hi3_dictionary.txt")
config = load_json("config.json")
threshold = config.get("spellcheck_confidence_threshold", 0.85)

for video_id in get_extracted_videos():
    progress = load_progress(video_id)
    if progress["stages"]["spellcheck"]["status"] == "complete":
        continue
    
    raw = load_json(f"raw/{video_id}.json")
    entries = []
    errors = []
    auto_corrected_count = 0
    flagged_count = 0
    
    for entry in raw["entries"]:
        try:
            corrected_speaker, speaker_corrections, speaker_flags = spellcheck_text(
                entry["speaker"], tool, custom_words, threshold
            )
            corrected_dialogue, dialogue_corrections, dialogue_flags = spellcheck_text(
                entry["dialogue"], tool, custom_words, threshold
            )
            
            all_corrections = speaker_corrections + dialogue_corrections
            all_flags = speaker_flags + dialogue_flags
            
            if all_corrections:
                auto_corrected_count += 1
            if all_flags:
                flagged_count += 1
            
            entries.append({
                "timestamp": entry["timestamp"],
                "speaker": corrected_speaker,
                "dialogue": corrected_dialogue,
                "original_speaker": entry["speaker"],
                "original_dialogue": entry["dialogue"],
                "confidence": entry["confidence"],
                "frame": entry["frame"],
                "auto_corrected": bool(all_corrections),
                "corrections_applied": all_corrections,
                "flagged_issues": all_flags
            })
        except Exception as e:
            errors.append(f"Entry {entry['frame']}: {str(e)}")
            entries.append({
                **entry,
                "original_speaker": entry["speaker"],
                "original_dialogue": entry["dialogue"],
                "auto_corrected": False,
                "corrections_applied": [],
                "flagged_issues": []
            })
    
    save_json(f"spellchecked/{video_id}.json", {"video_id": video_id, "entries": entries})
    
    update_progress(video_id, "spellcheck", {
        "status": "complete",
        "entries_processed": len(entries),
        "auto_corrected_count": auto_corrected_count,
        "flagged_count": flagged_count,
        "errors": errors
    })

tool.close()
```

### Dictionary Builder Command

Manual command to build custom dictionary from reviewed corrections.

```python
# Usage: python main.py build-dictionary

def build_dictionary():
    unique_terms = set()
    
    if file_exists("hi3_dictionary.txt"):
        unique_terms = load_dictionary("hi3_dictionary.txt")
    
    for reviewed_file in glob("reviewed/*.json"):
        reviewed = load_json(reviewed_file)
        
        for entry in reviewed["entries"]:
            if entry.get("corrected"):
                if entry["speaker"]:
                    unique_terms.add(entry["speaker"].strip())
    
    sorted_terms = sorted(unique_terms, key=str.lower)
    
    write_lines("hi3_dictionary.txt", sorted_terms)
    
    print(f"Dictionary updated: {len(sorted_terms)} terms")
```

---

## Stage 4: Review

### Tools
- Python
- Flask

### Input
- `spellchecked/{video_id}.json`
- `frames/{video_id}/`

### Output
- `reviewed/{video_id}.json`
- Updated `progress/{video_id}.json`

### Technical Solution

Flask web application with two main views:

1. **Dashboard:** List all videos with pipeline status, filter by stage, show progress stats, show spellcheck statistics
2. **Review page:** Display frame image alongside extracted text, allow inline editing, mark as reviewed, show diff view for auto-corrected and flagged entries

**Features:**
- Filter entries by confidence threshold
- Filter by spellcheck status (auto-corrected, flagged, clean)
- Show low-confidence entries first
- Show diff view comparing original vs corrected text for auto-corrected entries
- Highlight flagged issues with suggested corrections
- Edit speaker and dialogue fields
- Keyboard shortcuts (approve, skip, next)
- Auto-save on edit
- Track review statistics

**Changes from v1:**
1. `init_reviewed()` reads from `spellchecked/` instead of `raw/`
2. Entry UI displays `original_speaker`/`original_dialogue` for comparison when `auto_corrected=True`
3. Entry UI displays `flagged_issues` with suggestions
4. New filter options: "auto-corrected", "flagged"
5. Dashboard shows spellcheck stats (auto-corrected count, flagged count)

**Reviewed entry schema:**
```json
{
  "video_id": "string",
  "entries": [
    {
      "timestamp": 5,
      "speaker": "string or null",
      "dialogue": "string",
      "confidence": 0.95,
      "frame": "frame_00005.png",
      "reviewed": true,
      "corrected": false
    }
  ]
}
```

**Routes:**
- `GET /` - Dashboard
- `GET /video/{video_id}` - Review page for video
- `GET /api/video/{video_id}/entries` - Paginated entries with filters
- `POST /video/{video_id}/flush` - Batch update entries
- `GET /api/progress` - All videos progress JSON

### Pseudocode

```python
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

SPELLCHECKED_DIR = Path("spellchecked")

def init_reviewed(video_id):
    reviewed_path = REVIEWED_DIR / f"{video_id}.json"
    spellchecked_path = SPELLCHECKED_DIR / f"{video_id}.json"
    
    if reviewed_path.exists():
        reviewed = load_json(reviewed_path)
        if reviewed.get("entries"):
            return reviewed
    
    if not spellchecked_path.exists():
        return None
    
    spellchecked = load_json(spellchecked_path)
    for entry in spellchecked["entries"]:
        entry["reviewed"] = False
        entry["corrected"] = False
    
    save_json(reviewed_path, spellchecked)
    return spellchecked

@app.route("/")
def dashboard():
    videos = []
    for progress_file in glob("progress/*.json"):
        progress = load_json(progress_file)
        videos.append({
            "video_id": progress["video_id"],
            "status": progress["status"],
            "review_progress": progress["stages"]["review"],
            "spellcheck_stats": progress["stages"]["spellcheck"]
        })
    return render_template("dashboard.html", videos=videos)

@app.route("/video/<video_id>")
def review_video(video_id):
    reviewed = init_reviewed(video_id)
    if not reviewed:
        return "Video not found or not ready for review", 404
    return render_template("review.html", video_id=video_id, entries=reviewed["entries"])

@app.route("/api/video/<video_id>/entries")
def get_entries(video_id):
    reviewed = init_reviewed(video_id)
    filter_type = request.args.get("filter", "all")
    
    entries = reviewed["entries"]
    indexed_entries = [{"index": i, **e} for i, e in enumerate(entries)]
    
    if filter_type == "auto_corrected":
        indexed_entries = [e for e in indexed_entries if e.get("auto_corrected", False)]
    elif filter_type == "flagged":
        indexed_entries = [e for e in indexed_entries if e.get("flagged_issues")]
    
    return jsonify({"entries": indexed_entries})

@app.route("/frame/<video_id>/<filename>")
def serve_frame(video_id, filename):
    return send_file(f"frames/{video_id}/{filename}")
```

### Review UI Diff View

When `auto_corrected=True` or `flagged_issues` exists, display comparison:

```html
<!-- Diff view for auto-corrected entries -->
<div class="diff-view" v-if="entry.auto_corrected">
    <div class="original">
        <label>Original (OCR)</label>
        <div class="speaker-diff">{{ entry.original_speaker }}</div>
        <div class="dialogue-diff">{{ entry.original_dialogue }}</div>
    </div>
    <div class="corrected">
        <label>Auto-corrected</label>
        <div class="speaker-diff">{{ entry.speaker }}</div>
        <div class="dialogue-diff">{{ entry.dialogue }}</div>
    </div>
    <div class="corrections-list">
        <span v-for="c in entry.corrections_applied" class="correction-badge">
            {{ c.original }} → {{ c.corrected }} ({{ c.type }})
        </span>
    </div>
</div>

<!-- Flagged issues -->
<div class="flagged-issues" v-if="entry.flagged_issues.length">
    <label>Flagged Issues (review needed)</label>
    <div v-for="issue in entry.flagged_issues" class="flagged-item">
        <span class="issue-text">"{{ issue.text }}"</span>
        <span class="suggestion">Suggestion: {{ issue.suggestion }}</span>
        <span class="issue-type">({{ issue.type }})</span>
    </div>
</div>
```

---

## Stage 5: Output

### Tools
- Python

### Input
- `reviewed/{video_id}.json`
- `metadata/{video_id}.json`

### Output
- `archive/{chapter}.json`

### Technical Solution

Read all reviewed files. Group entries by chapter using metadata. Merge dialogues from multiple videos of same chapter, ordered by video upload date then timestamp. Generate final JSON archive files.

**Archive schema:**
```json
{
  "chapter_name": "string",
  "source_videos": [
    {
      "video_id": "string",
      "title": "string",
      "url": "string",
      "upload_date": "string"
    }
  ],
  "dialogues": [
    {
      "speaker": "string or null",
      "text": "string",
      "timestamp": 5,
      "source_video_id": "string"
    }
  ]
}
```

### Pseudocode

```python
chapters = {}

reviewed_files = glob("reviewed/*.json")

for reviewed_file in reviewed_files:
    reviewed = load_json(reviewed_file)
    video_id = reviewed["video_id"]
    metadata = load_json(f"metadata/{video_id}.json")
    chapter = metadata["chapter"]
    
    if chapter not in chapters:
        chapters[chapter] = {
            "chapter_name": chapter,
            "source_videos": [],
            "dialogues": []
        }
    
    chapters[chapter]["source_videos"].append({
        "video_id": video_id,
        "title": metadata["title"],
        "url": metadata["url"],
        "upload_date": metadata["upload_date"]
    })
    
    for entry in reviewed["entries"]:
        chapters[chapter]["dialogues"].append({
            "speaker": entry["speaker"],
            "text": entry["dialogue"],
            "timestamp": entry["timestamp"],
            "source_video_id": video_id
        })

for chapter_name, data in chapters.items():
    # Sort source videos by upload date
    data["source_videos"].sort(key=lambda v: v["upload_date"])
    
    # Build video order map
    video_order = {v["video_id"]: i for i, v in enumerate(data["source_videos"])}
    
    # Sort dialogues by video order, then timestamp
    data["dialogues"].sort(key=lambda d: (video_order[d["source_video_id"]], d["timestamp"]))
    
    filename = sanitize_filename(chapter_name)
    save_json(f"archive/{filename}.json", data)
```

---

## Progress Tracking

### Schema

`progress/{video_id}.json`:

```json
{
  "video_id": "string",
  "url": "string",
  "status": "input | acquire | extract | spellcheck | review | complete",
  "stages": {
    "input": {
      "status": "pending | complete | error",
      "timestamp": "ISO datetime"
    },
    "acquire": {
      "status": "pending | in_progress | complete | error",
      "frames_total": 0,
      "last_frame": 0,
      "errors": []
    },
    "extract": {
      "status": "pending | complete | error",
      "frames_processed": 0,
      "frames_skipped": 0,
      "entries_extracted": 0,
      "low_confidence_count": 0,
      "errors": []
    },
    "spellcheck": {
      "status": "pending | complete | error",
      "entries_processed": 0,
      "auto_corrected_count": 0,
      "flagged_count": 0,
      "errors": []
    },
    "review": {
      "status": "pending | in_progress | complete",
      "total_entries": 0,
      "reviewed": 0,
      "corrected": 0,
      "pending_low_confidence": 0
    },
    "output": {
      "status": "pending | complete"
    }
  }
}
```

### Query Interface

CLI tool to query video progress:

```python
# progress.py
# Usage: python progress.py <video_id>
# Output: formatted status of video across all stages

import sys

video_id = sys.argv[1]
progress = load_json(f"progress/{video_id}.json")

print(f"Video: {video_id}")
print(f"Current Stage: {progress['status']}")
print()

for stage, data in progress["stages"].items():
    print(f"{stage}: {data['status']}")
    if stage == "acquire" and data.get("errors"):
        print(f"  Errors: {len(data['errors'])}")
    if stage == "extract":
        print(f"  Low confidence: {data.get('low_confidence_count', 0)}")
    if stage == "spellcheck":
        print(f"  Auto-corrected: {data.get('auto_corrected_count', 0)}")
        print(f"  Flagged: {data.get('flagged_count', 0)}")
    if stage == "review":
        print(f"  Reviewed: {data.get('reviewed', 0)}/{data.get('total_entries', 0)}")
```

---

## Configuration

`config.json`:

```json
{
  "subtitle_crop": {
    "width": 800,
    "height": 100,
    "x": 240,
    "y": 620
  },
  "video_quality": 720,
  "frame_rate": 1,
  "similarity_threshold": 0.90,
  "confidence_threshold": 0.80,
  "spellcheck_confidence_threshold": 0.85
}
```

---

## CLI Commands

```bash
# Stage commands
python main.py stage1 --urls urls.txt
python main.py stage2
python main.py stage3
python main.py spellcheck
python main.py review
python main.py stage5

# Full pipeline
python main.py run-all --urls urls.txt
python main.py run-all --urls urls.txt --auto-approve

# Utilities
python main.py calibrate
python main.py status
python main.py status --video-id VIDEO_ID
python main.py build-dictionary
```

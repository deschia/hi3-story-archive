# HI3 Story Dialogue Archive Pipeline Design

## Task Summary

Archive Honkai Impact 3rd story dialogues from YouTube gameplay videos. The dialogues appear as in-game subtitles and need to be extracted via OCR. The archive captures both speaker names and dialogue text in structured format (JSON/YAML), organized by game chapter.

**Scale:** 200+ videos, ongoing updates  
**Source:** YouTube videos (provided via URL list file)  
**Output:** Structured data files (JSON/YAML) stored locally  
**Quality Control:** Semi-automated with manual review for low-confidence results

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         HI3 DIALOGUE ARCHIVE PIPELINE                            │
└──────────────────────────────────────────────────────────────────────────────────┘

     ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐
     │  INPUT  │─────>│ ACQUIRE │─────>│ EXTRACT │─────>│ REVIEW  │─────>│ OUTPUT  │
     │         │      │         │      │         │      │         │      │         │
     │URL List │      │ Video/  │      │  OCR    │      │ Manual  │      │ JSON/   │
     │  File   │      │ Frames  │      │ + Parse │      │ Correct │      │  YAML   │
     └─────────┘      └─────────┘      └─────────┘      └─────────┘      └─────────┘
          │                │                │                │                │
          v                v                v                v                v
     [urls.txt]       [frames/]        [raw.json]      [reviewed/]      [archive/]
```

---

## Stage 1: Input

### Goal
Parse and validate video URLs, associate with chapter metadata.

### Requirements
- Read video URLs from a text file (one URL per line)
- Extract video ID and title from YouTube
- Derive chapter organization from video title/metadata
- Support incremental processing (skip already-processed videos)

### Pitfalls
- Video titles may not follow consistent naming convention
- Some videos may be private, deleted, or region-locked
- Duplicate videos covering same story content

---

## Stage 2: Acquire

### Goal
Download video frames containing subtitles for OCR processing.

### Requirements
- Download video or extract frames at regular intervals (e.g., 1 frame per second)
- Focus on subtitle region only to reduce storage/processing
- Handle various video qualities/resolutions
- Store frames in organized directory structure by video ID

### Pitfalls
- Large storage requirements for frame extraction
- Rate limiting from YouTube
- Video quality affects OCR accuracy

### Alternatives
- **Full video download:** More storage, but allows re-extraction with different settings
- **Frame-only extraction:** Less storage, faster processing, but no re-extraction without re-download
- **Stream processing:** Process frames in memory without storage, lowest storage but no recovery on failure

---

## Stage 3: Extract

### Goal
Perform OCR on subtitle region, parse speaker and dialogue, deduplicate consecutive frames.

### Requirements
- OCR the defined subtitle region (configurable coordinates)
- Parse extracted text into speaker name and dialogue
- Deduplicate consecutive identical text across frames
- Track confidence scores for each extraction
- Support manual override for subtitle region variants
- Output raw extraction results with timestamps and confidence

### Pitfalls
- OCR errors on stylized game fonts
- Speaker name may not always be present (narration, system text)
- Subtitle timing across frames may cause partial text capture
- Special characters, punctuation, or non-English words in English subtitles

### Alternatives
- **Tesseract:** Free, widely supported, may need training for game fonts
- **Cloud OCR (Google Vision, Azure):** Higher accuracy, but costs money and requires internet
- **EasyOCR:** Good multilingual support, runs locally

---

## Stage 4: Review

### Goal
Quality control step to flag and correct low-confidence OCR results.

### Requirements
- Flag extractions below confidence threshold for manual review
- Provide interface to view frame image alongside extracted text
- Allow correction of speaker name, dialogue, or both
- Mark entries as reviewed/approved
- Track correction statistics to improve OCR settings

### Pitfalls
- Large volume of low-confidence results could overwhelm manual review
- Reviewer fatigue leading to missed errors
- Need to preserve original frame reference for context

---

## Stage 5: Output

### Goal
Generate final structured archive files organized by chapter.

### Requirements
- Output JSON or YAML format (configurable)
- Organize files by game chapter (derived from video metadata)
- Include metadata: video source, timestamps, extraction date
- Schema structure:
  ```
  chapter/
    chapter-name.json
      - chapter_name
      - source_videos[]
      - dialogues[]
          - speaker
          - text
          - timestamp (optional)
          - source_video_id
  ```
- Support regeneration from reviewed data

### Pitfalls
- Chapter organization may need manual curation if video titles are inconsistent
- Merging dialogues from multiple videos covering same chapter

---

## Open Questions

1. **Frame extraction rate:** What interval captures all subtitle changes without excessive redundancy? (1 fps suggested as starting point)

> 1 fps

2. **Confidence threshold:** What OCR confidence score triggers manual review? (needs calibration after initial runs)

> TBD

3. **Chapter naming:** Is there a canonical chapter list to map video titles against, or derive from video titles?

> derive from video titles

4. **Incremental updates:** How to handle corrections when source videos are reprocessed?

> TBD

---

## Data Flow Summary

| Stage | Input | Output | Storage |
|-------|-------|--------|---------|
| Input | `urls.txt` | Video metadata list | `metadata/` |
| Acquire | Video URLs | Extracted frames | `frames/{video_id}/` |
| Extract | Frames | Raw OCR results | `raw/{video_id}.json` |
| Review | Raw results + frames | Corrected results | `reviewed/{video_id}.json` |
| Output | Reviewed results | Final archive | `archive/{chapter}.json` |

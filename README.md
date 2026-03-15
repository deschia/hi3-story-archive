# HI3 Story Archive Pipeline - Implementation Report

## Overview

Implemented a 5-stage pipeline to archive Honkai Impact 3rd story dialogues from YouTube videos via OCR extraction.

## Setup Requirements

### Prerequisites

1. **Python 3.14** (as specified)
2. **ffmpeg** - Must be installed and added to PATH
   - Windows: Download from https://ffmpeg.org/download.html
   - Extract to a folder (e.g., `C:\ffmpeg`)
   - Add `C:\ffmpeg\bin` to system PATH
3. **yt-dlp** - Installed via pip

### Installation

```bash
# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

## Directory Structure

```
hi3-story-archive/
├── main.py               # Main orchestrator CLI
├── utils.py              # Shared utilities
├── stage1_input.py       # Metadata extraction
├── stage2_acquire.py     # Frame extraction
├── stage3_extract.py     # OCR processing
├── stage4_review.py      # Flask review UI
├── stage5_output.py      # Archive generation
├── calibrate.py          # Subtitle region calibration tool
├── progress.py           # Progress query tool
├── config.json           # Pipeline configuration
├── requirements.txt      # Python dependencies
├── urls.txt              # Input URLs (user provides)
├── templates/            # Flask templates
│   ├── dashboard.html
│   └── review.html
├── metadata/             # Stage 1 output
├── frames/               # Stage 2 output
├── raw/                  # Stage 3 output
├── reviewed/             # Stage 4 output
├── archive/              # Stage 5 output
└── progress/             # Progress tracking
```

## Usage

### 1. Calibration (First Time Setup)

Run the calibration tool to set subtitle crop coordinates:

```bash
python main.py calibrate
```

- Load a sample frame or extract from YouTube URL
- Draw rectangle over the subtitle region
- Save to config.json

### 2. Prepare URLs

Create `urls.txt` with one YouTube URL per line:

```
https://www.youtube.com/watch?v=VIDEO_ID_1
https://www.youtube.com/watch?v=VIDEO_ID_2
```

### 3. Run Pipeline

**Option A: Run stages individually**

```bash
# Stage 1: Fetch metadata
python main.py stage1 --urls urls.txt

# Stage 2: Extract frames (can take hours)
python main.py stage2

# Stage 3: Run OCR (requires GPU for best performance)
python main.py stage3

# Stage 4: Manual review
python main.py review

# Stage 5: Generate archive
python main.py stage5
```

**Option B: Run full pipeline**

```bash
python main.py run-all --urls urls.txt

# Or with auto-approve (skip manual review)
python main.py run-all --urls urls.txt --auto-approve
```

### 4. Check Status

```bash
# Overall status
python main.py status

# Specific video
python main.py status --video-id VIDEO_ID
```

## Stage Details

### Stage 1: Input
- Reads URLs from `urls.txt`
- Fetches video metadata via yt-dlp
- Extracts chapter name from title (split on `|`)
- Outputs: `metadata/{video_id}.json`

### Stage 2: Acquire
- Gets stream URL at 720p quality
- Extracts frames at 1 fps using ffmpeg
- Crops to subtitle region
- Supports resume if interrupted
- Outputs: `frames/{video_id}/frame_XXXXX.png`

### Stage 3: Extract
- Processes frames with EasyOCR
- Deduplicates similar consecutive text (90% threshold)
- Parses speaker name (line 1) and dialogue (line 2+)
- Records confidence scores
- Outputs: `raw/{video_id}.json`

### Stage 4: Review
- Flask web application at http://127.0.0.1:5000
- Dashboard shows all videos with progress
- Review page displays frame alongside OCR text
- Edit speaker/dialogue fields inline
- Filter by confidence, reviewed status
- Keyboard shortcuts: Enter to save
- Outputs: `reviewed/{video_id}.json`

### Stage 5: Output
- Groups dialogues by chapter
- Merges multiple videos of same chapter
- Sorts by upload date then timestamp
- Outputs: `archive/{chapter}.json`

## Configuration

`config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| subtitle_crop.x | 240 | Crop X offset |
| subtitle_crop.y | 620 | Crop Y offset |
| subtitle_crop.width | 800 | Crop width |
| subtitle_crop.height | 100 | Crop height |
| video_quality | 720 | Max video height |
| frame_rate | 1 | Frames per second |
| similarity_threshold | 0.90 | Deduplication threshold |
| confidence_threshold | 0.80 | Low confidence marker |

## Error Handling

- Errors logged to `errors.log`
- Progress tracked per-video for resume capability
- Individual frame/video failures don't stop pipeline
- Stage 2 can resume from last extracted frame

## Performance Notes

- Stage 2 (Acquire): ~1 hour per 2-hour video (depends on connection)
- Stage 3 (Extract): ~5 minutes per 1000 frames with GPU, much slower on CPU
- EasyOCR uses CUDA if available, falls back to CPU

## Files Created

| File | Count | Description |
|------|-------|-------------|
| main.py | 1 | CLI orchestrator |
| utils.py | 1 | Shared utilities |
| stage1_input.py | 1 | Stage 1 implementation |
| stage2_acquire.py | 1 | Stage 2 implementation |
| stage3_extract.py | 1 | Stage 3 implementation |
| stage4_review.py | 1 | Stage 4 Flask app |
| stage5_output.py | 1 | Stage 5 implementation |
| calibrate.py | 1 | Calibration tool |
| progress.py | 1 | Progress query tool |
| config.json | 1 | Configuration |
| requirements.txt | 1 | Dependencies |
| templates/dashboard.html | 1 | Dashboard template |
| templates/review.html | 1 | Review template |

**Total: 13 files**

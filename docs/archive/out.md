# HI3 Story Dialogue Archive - Technical Implementation Plan

## Workspace Preparation Phase

### Task 1.1: Create Directory Structure

```bash
mkdir -p metadata frames raw reviewed archive progress templates
```

### Task 1.2: Create requirements.txt

```python
# requirements.txt
yt-dlp>=2024.7.30
easyocr>=1.7.1
flask>=3.0.0
opencv-python>=4.9.0
numpy>=1.24.0
```

### Task 1.3: Create config.json

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
  "confidence_threshold": 0.80
}
```

### Task 1.4: Create utils.py

```python
# utils.py - Shared utility functions
import json
import os
import sys
from datetime import datetime

def load_json(filepath):
    """Load JSON file, return empty dict if file doesn't exist."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(filepath, data):
    """Save data as JSON with proper formatting."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def log_error(video_id, error_message, stage=None):
    """Log error to errors.log."""
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] {video_id} | {stage or 'unknown'}: {error_message}\
"
    with open("errors.log", "a", encoding='utf-8') as f:
        f.write(log_entry)

def extract_video_id(url):
    """Extract YouTube video ID from URL."""
    import re
    patterns = [
        r'youtube\\.com/watch\\?v=([^&]+)',
        r'youtu\\.be/([^?]+)',
        r'youtube\\.com/embed/([^?]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def init_progress(video_id, url):
    """Initialize progress tracking for a video."""
    progress = {
        "video_id": video_id,
        "url": url,
        "status": "input",
        "stages": {
            "input": {"status": "pending", "timestamp": None},
            "acquire": {"status": "pending", "frames_total": 0, "last_frame": 0, "errors": []},
            "extract": {"status": "pending", "frames_processed": 0, "frames_skipped": 0, 
                       "entries_extracted": 0, "low_confidence_count": 0, "errors": []},
            "review": {"status": "pending", "total_entries": 0, "reviewed": 0, 
                      "corrected": 0, "pending_low_confidence": 0},
            "output": {"status": "pending"}
        }
    }
    save_json(f"progress/{video_id}.json", progress)

def update_progress(video_id, stage, updates):
    """Update progress for a specific stage."""
    progress = load_json(f"progress/{video_id}.json")
    if not progress:
        return
    
    if stage in progress["stages"]:
        progress["stages"][stage].update(updates)
        if "status" in updates:
            progress["stages"][stage]["timestamp"] = datetime.now().isoformat()
    
    # Update overall status
    stages = progress["stages"]
    if stages["output"]["status"] == "complete":
        progress["status"] = "complete"
    elif stages["review"]["status"] == "complete":
        progress["status"] = "review"
    elif stages["extract"]["status"] == "complete":
        progress["status"] = "extract"
    elif stages["acquire"]["status"] == "complete":
        progress["status"] = "acquire"
    elif stages["input"]["status"] == "complete":
        progress["status"] = "input"
    
    save_json(f"progress/{video_id}.json", progress)

def sanitize_filename(name):
    """Sanitize string for use as filename."""
    import re
    name = re.sub(r'[<>:"/\\\\|?*]', '_', name)
    name = re.sub(r'\\s+', '_', name)
    return name[:100]
```

---

## Stage 1 Implementation Phase

### Task 2.1: Create stage1_input.py

```python
# stage1_input.py - Stage 1: Input processing
import sys
import subprocess
import json
from utils import load_json, save_json, log_error, extract_video_id, init_progress

def process_url(url):
    """Process single YouTube URL."""
    video_id = extract_video_id(url)
    if not video_id:
        log_error("unknown", f"Invalid URL format: {url}", "input")
        return False
    
    # Skip if already processed
    if os.path.exists(f"metadata/{video_id}.json"):
        print(f"  Skipping {video_id} (already processed)")
        return True
    
    # Fetch metadata with yt-dlp
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", url],
            capture_output=True,
            text=True,
            check=True
        )
        metadata = json.loads(result.stdout)
        
        # Extract chapter from title
        title = metadata.get("title", "")
        chapter = title.split("|")[0].strip() if "|" in title else title
        
        # Save metadata
        save_json(f"metadata/{video_id}.json", {
            "video_id": video_id,
            "url": url,
            "title": title,
            "chapter": chapter,
            "upload_date": metadata.get("upload_date", "")
        })
        
        # Initialize progress tracking
        init_progress(video_id, url)
        update_progress(video_id, "input", {"status": "complete"})
        
        print(f"  Processed {video_id}: {chapter}")
        return True
        
    except subprocess.CalledProcessError as e:
        log_error(video_id, f"yt-dlp failed: {e.stderr}", "input")
        return False
    except Exception as e:
        log_error(video_id, f"Unexpected error: {str(e)}", "input")
        return False

def main():
    """Main entry point."""
    if not os.path.exists("urls.txt"):
        print("Error: urls.txt not found")
        sys.exit(1)
    
    with open("urls.txt", "r", encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    
    print(f"Processing {len(urls)} URLs...")
    success = 0
    failed = 0
    
    for url in urls:
        if process_url(url):
            success += 1
        else:
            failed += 1
    
    print(f"\
Summary: {success} succeeded, {failed} failed")

if __name__ == "__main__":
    main()
```

---

## Stage 2 Implementation Phase

### Task 3.1: Create calibrate.py

```python
# calibrate.py - Calibration tool for subtitle crop coordinates
import cv2
import subprocess
import json
import tempfile
import os
from utils import load_json, save_json

def extract_sample_frame(video_url, output_path):
    """Extract single frame from video at midpoint."""
    # Get video duration
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_url],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("Error: Could not get video duration")
        return False
    
    duration = float(result.stdout.strip())
    midpoint = duration / 2
    
    # Extract frame at midpoint
    cmd = [
        "ffmpeg", "-ss", str(midpoint), "-i", video_url,
        "-vframes", "1", "-q:v", "2", output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0

def main():
    """Main calibration routine."""
    print("Subtitle Region Calibration Tool")
    print("=" * 40)
    
    video_url = input("Enter YouTube URL for calibration: ").strip()
    if not video_url:
        print("No URL provided")
        return
    
    # Get stream URL
    print("Fetching stream URL...")
    result = subprocess.run(
        ["yt-dlp", "-g", "-f", "best[height<=720]", video_url],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("Error: Could not get stream URL")
        return
    
    stream_url = result.stdout.strip()
    
    # Extract sample frame
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    
    print("Extracting sample frame...")
    if not extract_sample_frame(stream_url, tmp_path):
        print("Error: Could not extract frame")
        os.unlink(tmp_path)
        return
    
    # Load image and select ROI
    image = cv2.imread(tmp_path)
    if image is None:
        print("Error: Could not load frame")
        os.unlink(tmp_path)
        return
    
    print("\
Draw rectangle around subtitle region and press ENTER")
    print("Press 'r' to reset, 'c' to cancel")
    
    roi = cv2.selectROI("Select Subtitle Region (Press ENTER when done)", image)
    cv2.destroyAllWindows()
    
    if roi == (0, 0, 0, 0):
        print("Calibration cancelled")
    else:
        x, y, width, height = roi
        print(f"\
Selected region: x={x}, y={y}, width={width}, height={height}")
        
        # Update config.json
        config = load_json("config.json") or {}
        config["subtitle_crop"] = {
            "width": width,
            "height": height,
            "x": x,
            "y": y
        }
        save_json("config.json", config)
        print("Configuration saved to config.json")
    
    # Cleanup
    os.unlink(tmp_path)

if __name__ == "__main__":
    main()
```

### Task 3.2: Create stage2_acquire.py

```python
# stage2_acquire.py - Stage 2: Frame acquisition
import os
import subprocess
import glob
from utils import load_json, save_json, log_error, update_progress

def get_stream_url(url, quality=720):
    """Get direct stream URL for video."""
    cmd = ["yt-dlp", "-g", "-f", f"best[height<={quality}]", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        return None, result.stderr
    
    return result.stdout.strip(), None

def extract_frames(video_id, metadata, config):
    """Extract frames from video stream."""
    progress = load_json(f"progress/{video_id}.json")
    if progress["stages"]["acquire"]["status"] == "complete":
        print(f"  {video_id}: Already acquired")
        return True
    
    # Get stream URL
    stream_url, error = get_stream_url(metadata["url"], config["video_quality"])
    if error:
        log_error(video_id, f"Stream URL failed: {error}", "acquire")
        update_progress(video_id, "acquire", {"status": "error", "errors": [error]})
        return False
    
    # Prepare crop filter
    crop = config["subtitle_crop"]
    crop_filter = f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}"
    
    # Create output directory
    frames_dir = f"frames/{video_id}"
    os.makedirs(frames_dir, exist_ok=True)
    
    # Resume support
    start_time = progress["stages"]["acquire"].get("last_frame", 0)
    start_number = start_time + 1
    
    # Build ffmpeg command
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", stream_url,
        "-vf", f"fps={config['frame_rate']},{crop_filter}",
        "-start_number", str(start_number),
        f"{frames_dir}/frame_%05d.png"
    ]
    
    print(f"  {video_id}: Extracting frames from {start_time}s...")
    
    # Run ffmpeg with progress tracking
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Simple progress tracking (could be enhanced with frame counting)
        process.wait()
        
        if process.returncode != 0:
            error = process.stderr.read()
            log_error(video_id, f"ffmpeg failed: {error}", "acquire")
            return False
        
        # Count extracted frames
        frames = glob.glob(f"{frames_dir}/frame_*.png")
        
        update_progress(video_id, "acquire", {
            "status": "complete",
            "frames_total": len(frames),
            "last_frame": len(frames)
        })
        
        print(f"  {video_id}: Extracted {len(frames)} frames")
        return True
        
    except Exception as e:
        log_error(video_id, f"Extraction failed: {str(e)}", "acquire")
        return False

def main():
    """Main entry point."""
    config = load_json("config.json")
    if not config:
        print("Error: config.json not found")
        return
    
    metadata_files = glob.glob("metadata/*.json")
    if not metadata_files:
        print("No metadata files found. Run stage1_input.py first.")
        return
    
    print(f"Processing {len(metadata_files)} videos...")
    
    success = 0
    failed = 0
    
    for metadata_file in metadata_files:
        metadata = load_json(metadata_file)
        video_id = metadata["video_id"]
        
        if extract_frames(video_id, metadata, config):
            success += 1
        else:
            failed += 1
    
    print(f"\
Summary: {success} succeeded, {failed} failed")

if __name__ == "__main__":
    main()
```

---

## Stage 3 Implementation Phase

### Task 4.1: Create stage3_extract.py

```python
# stage3_extract.py - Stage 3: OCR extraction
import os
import glob
from difflib import SequenceMatcher
import easyocr
from utils import load_json, save_json, log_error, update_progress

def is_similar(text1, text2, threshold=0.90):
    """Check if two texts are similar above threshold."""
    if not text1 or not text2:
        return False
    return SequenceMatcher(None, text1, text2).ratio() >= threshold

def extract_text_from_frame(frame_path, reader):
    """Extract text from single frame using EasyOCR."""
    try:
        result = reader.readtext(frame_path)
        if not result:
            return None, None
        
        # Combine all detected text
        text = "\
".join([r[1] for r in result])
        confidence = min([r[2] for r in result])
        
        return text, confidence
        
    except Exception as e:
        log_error("unknown", f"OCR failed for {frame_path}: {str(e)}", "extract")
        return None, None

def parse_subtitle_text(text):
    """Parse subtitle text into speaker and dialogue."""
    if not text:
        return None, None
    
    lines = text.strip().split("\
")
    if len(lines) >= 2:
        speaker = lines[0].strip()
        dialogue = "\
".join(lines[1:]).strip()
    else:
        speaker = None
        dialogue = text.strip()
    
    return speaker, dialogue

def process_video(video_id, config):
    """Process all frames for a video."""
    progress = load_json(f"progress/{video_id}.json")
    if progress["stages"]["extract"]["status"] == "complete":
        print(f"  {video_id}: Already extracted")
        return True
    
    frames_dir = f"frames/{video_id}"
    frames = sorted(glob.glob(f"{frames_dir}/frame_*.png"))
    
    if not frames:
        print(f"  {video_id}: No frames found")
        return False
    
    print(f"  {video_id}: Processing {len(frames)} frames...")
    
    # Initialize EasyOCR reader (auto-detect GPU)
    reader = easyocr.Reader(['en'], gpu=True)
    
    entries = []
    previous_text = None
    skipped = 0
    errors = []
    low_confidence_count = 0
    
    for frame_path in frames:
        # Extract frame number from filename
        frame_name = os.path.basename(frame_path)
        frame_num = int(frame_name.replace("frame_", "").replace(".png", ""))
        timestamp = frame_num  # 1 fps = seconds
        
        # Extract text
        text, confidence = extract_text_from_frame(frame_path, reader)
        
        if text is None:
            skipped += 1
            continue
        
        # Deduplicate similar text
        if is_similar(text, previous_text, config["similarity_threshold"]):
            continue
        
        # Parse speaker and dialogue
        speaker, dialogue = parse_subtitle_text(text)
        
        # Check confidence threshold
        if confidence < config["confidence_threshold"]:
            low_confidence_count += 1
        
        entries.append({
            "timestamp": timestamp,
            "speaker": speaker,
            "dialogue": dialogue,
            "confidence": float(confidence),
            "frame": frame_name
        })
        
        previous_text = text
    
    # Save raw extraction
    save_json(f"raw/{video_id}.json", {
        "video_id": video_id,
        "entries": entries
    })
    
    # Update progress
    update_progress(video_id, "extract", {
        "status": "complete",
        "frames_processed": len(frames),
        "frames_skipped": skipped,
        "entries_extracted": len(entries),
        "low_confidence_count": low_confidence_count,
        "errors": errors
    })
    
    print(f"  {video_id}: Extracted {len(entries)} entries ({low_confidence_count} low confidence)")
    return True

def main():
    """Main entry point."""
    config = load_json("config.json")
    if not config:
        print("Error: config.json not found")
        return
    
    # Get videos that have frames extracted
    frame_dirs = glob.glob("frames/*")
    video_ids = [os.path.basename(d) for d in frame_dirs if os.path.isdir(d)]
    
    if not video_ids:
        print("No videos with extracted frames found. Run stage2_acquire.py first.")
        return
    
    print(f"Processing {len(video_ids)} videos...")
    
    success = 0
    failed = 0
    
    for video_id in video_ids:
        if process_video(video_id, config):
            success += 1
        else:
            failed += 1
    
    print(f"\
Summary: {success} succeeded, {failed} failed")

if __name__ == "__main__":
    main()
```

---

## Stage 4 Implementation Phase - Review Web UI

### Task 5.1: Create stage4_review.py

```python
# stage4_review.py - Stage 4: Review web UI
from flask import Flask, render_template, request, jsonify, send_file
import os
import glob
from utils import load_json, save_json, update_progress

app = Flask(__name__)

@app.route("/")
def dashboard():
    """Dashboard showing all videos and their status."""
    videos = []
    
    for progress_file in glob.glob("progress/*.json"):
        progress = load_json(progress_file)
        if not progress:
            continue
        
        video_id = progress["video_id"]
        
        # Load metadata for display
        metadata = load_json(f"metadata/{video_id}.json") or {}
        
        videos.append({
            "video_id": video_id,
            "title": metadata.get("title", "Unknown"),
            "chapter": metadata.get("chapter", "Unknown"),
            "status": progress["status"],
            "stages": progress["stages"],
            "has_raw": os.path.exists(f"raw/{video_id}.json"),
            "has_reviewed": os.path.exists(f"reviewed/{video_id}.json")
        })
    
    return render_template("dashboard.html", videos=videos)

@app.route("/video/<video_id>")
def review_video(video_id):
    """Review page for specific video."""
    raw_path = f"raw/{video_id}.json"
    reviewed_path = f"reviewed/{video_id}.json"
    
    if not os.path.exists(raw_path):
        return f"Raw data not found for {video_id}", 404
    
    # Load data
    raw_data = load_json(raw_path)
    if os.path.exists(reviewed_path):
        reviewed_data = load_json(reviewed_path)
    else:
        # Initialize reviewed data from raw
        reviewed_data = {
            "video_id": video_id,
            "entries": []
        }
        for entry in raw_data["entries"]:
            reviewed_data["entries"].append({
                **entry,
                "reviewed": False,
                "corrected": False
            })
        save_json(reviewed_path, reviewed_data)
    
    # Update progress stats
    total_entries = len(reviewed_data["entries"])
    reviewed_count = sum(1 for e in reviewed_data["entries"] if e.get("reviewed", False))
    corrected_count = sum(1 for e in reviewed_data["entries"] if e.get("corrected", False))
    pending_low = sum(1 for e in reviewed_data["entries"] 
                     if not e.get("reviewed", False) and e.get("confidence", 1) < 0.8)
    
    update_progress(video_id, "review", {
        "status": "in_progress",
        "total_entries": total_entries,
        "reviewed": reviewed_count,
        "corrected": corrected_count,
        "pending_low_confidence": pending_low
    })
    
    return render_template("review.html", 
                         video_id=video_id, 
                         entries=reviewed_data["entries"],
                         metadata=load_json(f"metadata/{video_id}.json") or {})

@app.route("/video/<video_id>/entry/<int:index>", methods=["POST"])
def update_entry(video_id, index):
    """Update a specific entry."""
    reviewed_path = f"reviewed/{video_id}.json"
    if not os.path.exists(reviewed_path):
        return jsonify({"error": "Review data not found"}), 404
    
    reviewed_data = load_json(reviewed_path)
    if index >= len(reviewed_data["entries"]):
        return jsonify({"error": "Invalid index"}), 400
    
    data = request.json
    entry = reviewed_data["entries"][index]
    
    # Check if corrected
    corrected = (entry.get("speaker") != data.get("speaker") or 
                 entry.get("dialogue") != data.get("dialogue"))
    
    # Update entry
    entry["speaker"] = data.get("speaker")
    entry["dialogue"] = data.get("dialogue")
    entry["reviewed"] = True
    entry["corrected"] = corrected
    
    save_json(reviewed_path, reviewed_data)
    
    # Update progress
    total_entries = len(reviewed_data["entries"])
    reviewed_count = sum(1 for e in reviewed_data["entries"] if e.get("reviewed", False))
    corrected_count = sum(1 for e in reviewed_data["entries"] if e.get("corrected", False))
    
    if reviewed_count == total_entries:
        status = "complete"
    else:
        status = "in_progress"
    
    update_progress(video_id, "review", {
        "status": status,
        "reviewed": reviewed_count,
        "corrected": corrected_count
    })
    
    return jsonify({"success": True})

@app.route("/frame/<video_id>/<filename>")
def serve_frame(video_id, filename):
    """Serve frame image."""
    frame_path = f"frames/{video_id}/{filename}"
    if os.path.exists(frame_path):
        return send_file(frame_path)
    return "Frame not found", 404

@app.route("/api/progress")
def api_progress():
    """API endpoint for progress data."""
    all_progress = {}
    for progress_file in glob.glob("progress/*.json"):
        progress = load_json(progress_file)
        if progress:
            all_progress[progress["video_id"]] = progress
    return jsonify(all_progress)

def main():
    """Start Flask development server."""
    print("Starting review web UI...")
    print("Dashboard: http://127.0.0.1:5000/")
    app.run(debug=True, host='0.0.0.0', port=5000)

if __name__ == "__main__":
    main()
```

### Task 5.2: Create templates/dashboard.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HI3 Story Archive - Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-800">HI3 Story Dialogue Archive</h1>
            <p class="text-gray-600">Review and manage video processing pipeline</p>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {% for video in videos %}
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex justify-between items-start mb-4">
                    <div>
                        <h3 class="font-semibold text-lg text-gray-800">{{ video.title[:50] }}{% if video.title|length > 50 %}...{% endif %}</h3>
                        <p class="text-sm text-gray-600">{{ video.chapter }}</p>
                        <p class="text-xs text-gray-500 mt-1">ID: {{ video.video_id }}</p>
                    </div>
                    <span class="px-3 py-1 text-xs font-semibold rounded-full 
                        {% if video.status == 'complete' %}bg-green-100 text-green-800
                        {% elif video.status == 'review' %}bg-blue-100 text-blue-800
                        {% elif video.status == 'extract' %}bg-yellow-100 text-yellow-800
                        {% elif video.status == 'acquire' %}bg-orange-100 text-orange-800
                        {% else %}bg-gray-100 text-gray-800{% endif %}">
                        {{ video.status|title }}
                    </span>
                </div>

                <div class="space-y-2 mb-4">
                    {% for stage_name, stage_data in video.stages.items() %}
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-700">{{ stage_name|title }}</span>
                        <span class="text-sm font-medium 
                            {% if stage_data.status == 'complete' %}text-green-600
                            {% elif stage_data.status == 'error' %}text-red-600
                            {% elif stage_data.status == 'in_progress' %}text-blue-600
                            {% else %}text-gray-500{% endif %}">
                            {{ stage_data.status|replace('_', ' ')|title }}
                        </span>
                    </div>
                    {% endfor %}
                </div>

                <div class="flex space-x-2">
                    {% if video.has_raw %}
                    <a href="/video/{{ video.video_id }}" 
                       class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-center py-2 px-4 rounded-md text-sm font-medium transition">
                        Review
                    </a>
                    {% else %}
                    <button disabled class="flex-1 bg-gray-300 text-gray-500 text-center py-2 px-4 rounded-md text-sm font-medium cursor-not-allowed">
                        No Data
                    </button>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        {% if not videos %}
        <div class="text-center py-12">
            <div class="text-gray-400 mb-4">
                <svg class="w-16 h-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
            </div>
            <h3 class="text-xl font-medium text-gray-700 mb-2">No videos processed yet</h3>
            <p class="text-gray-500">Run stage1_input.py to start processing videos</p>
        </div>
        {% endif %}
    </div>
</body>
</html>
```

### Task 5.3: Create templates/review.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Review - {{ video_id }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="mb-8">
            <div class="flex justify-between items-start">
                <div>
                    <h1 class="text-2xl font-bold text-gray-800">Review: {{ metadata.title }}</h1>
                    <p class="text-gray-600">{{ metadata.chapter }}</p>
                    <p class="text-sm text-gray-500 mt-1">Video ID: {{ video_id }}</p>
                </div>
                <a href="/" class="text-blue-600 hover:text-blue-800 font-medium">
                    ← Back to Dashboard
                </a>
            </div>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <!-- Left column: Frame display -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">Current Frame</h2>
                <div id="frame-container" class="mb-4">
                    <img id="frame-image" src="" alt="Frame" class="w-full rounded border border-gray-300">
                </div>
                <div class="text-center">
                    <p id="frame-info" class="text-sm text-gray-600">Select an entry to view frame</p>
                </div>
            </div>

            <!-- Right column: Entry list -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex justify-between items-center mb-6">
                    <h2 class="text-lg font-semibold text-gray-800">Entries ({{ entries|length }})</h2>
                    <div class="flex space-x-2">
                        <button id="filter-low" class="px-3 py-1 text-sm bg-yellow-100 text-yellow-800 rounded hover:bg-yellow-200">
                            Low Confidence
                        </button>
                        <button id="filter-unreviewed" class="px-3 py-1 text-sm bg-blue-100 text-blue-800 rounded hover:bg-blue-200">
                            Unreviewed
                        </button>
                        <button id="filter-all" class="px-3 py-1 text-sm bg-gray-100 text-gray-800 rounded hover:bg-gray-200">
                            All
                        </button>
                    </div>
                </div>

                <div id="entries-list" class="space-y-4 max-h-[600px] overflow-y-auto">
                    {% for entry in entries %}
                    <div class="entry-item border border-gray-200 rounded-lg p-4 hover:bg-gray-50 
                        {% if not entry.reviewed %}bg-blue-50 border-blue-200{% endif %}
                        {% if entry.confidence < 0.8 %}bg-yellow-50 border-yellow-200{% endif %}"
                        data-index="{{ loop.index0 }}"
                        data-frame="{{ entry.frame }}"
                        data-reviewed="{{ entry.reviewed|lower }}"
                        data-confidence="{{ entry.confidence }}">
                        
                        <div class="flex justify-between items-start mb-2">
                            <div>
                                <span class="text-sm font-medium text-gray-700">
                                    {{ entry.timestamp }}s
                                </span>
                                {% if entry.speaker %}
                                <span class="ml-2 px-2 py-1 text-xs bg-purple-100 text-purple-800 rounded">
                                    {{ entry.speaker }}
                                </span>
                                {% endif %}
                            </div>
                            <div class="flex space-x-2">
                                {% if entry.confidence < 0.8 %}
                                <span class="px-2 py-1 text-xs bg-yellow-100 text-yellow-800 rounded">
                                    Low Confidence
                                </span>
                                {% endif %}
                                {% if entry.reviewed %}
                                <span class="px-2 py-1 text-xs bg-green-100 text-green-800 rounded">
                                    Reviewed
                                </span>
                                {% if entry.corrected %}
                                <span class="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                                    Corrected
                                </span>
                                {% endif %}
                                {% endif %}
                            </div>
                        </div>
                        
                        <div class="entry-content">
                            <p class="text-gray-800 whitespace-pre-wrap">{{ entry.dialogue }}</p>
                        </div>
                        
                        <div class="entry-edit mt-3 hidden">
                            <div class="mb-3">
                                <label class="block text-sm font-medium text-gray-700 mb-1">Speaker</label>
                                <input type="text" class="edit-speaker w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" 
                                       value="{{ entry.speaker or '' }}">
                            </div>
                            <div class="mb-3">
                                <label class="block text-sm font-medium text-gray-700 mb-1">Dialogue</label>
                                <textarea class="edit-dialogue w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500" 
                                          rows="3">{{ entry.dialogue }}</textarea>
                            </div>
                            <div class="flex justify-end space-x-2">
                                <button class="edit-cancel px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                                    Cancel
                                </button>
                                <button class="edit-save px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">
                                    Save
                                </button>
                            </div>
                        </div>
                        
                        <div class="entry-actions mt-3 flex justify-end space-x-2">
                            <button class="edit-btn px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200">
                                Edit
                            </button>
                            <button class="approve-btn px-3 py-1 text-sm bg-green-100 text-green-700 rounded hover:bg-green-200">
                                Approve
                            </button>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            let currentEntryIndex = null;
            
            // Filter buttons
            document.getElementById('filter-low').addEventListener('click', () => {
                filterEntries('low');
            });
            
            document.getElementById('filter-unreviewed').addEventListener('click', () => {
                filterEntries('unreviewed');
            });
            
            document.getElementById('filter-all').addEventListener('click', () => {
                filterEntries('all');
            });
            
            // Entry click handler
            document.querySelectorAll('.entry-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('.edit-btn') || 
                        e.target.closest('.approve-btn') || 
                        e.target.closest('.edit-cancel') || 
                        e.target.closest('.edit-save')) {
                        return; // Let button handlers deal with these
                    }
                    
                    // Show frame for this entry
                    const frame = item.dataset.frame;
                    const videoId = '{{ video_id }}';
                    
                    document.getElementById('frame-image').src = `/frame/${videoId}/${frame}`;
                    document.getElementById('frame-info').textContent = `Frame: ${frame}`;
                    
                    // Highlight selected entry
                    document.querySelectorAll('.entry-item').forEach(el => {
                        el.classList.remove('ring-2', 'ring-blue-500');
                    });
                    item.classList.add('ring-2', 'ring-blue-500');
                    
                    currentEntryIndex = parseInt(item.dataset.index);
                });
            });
            
            // Edit button handlers
            document.querySelectorAll('.edit-btn').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const entryItem = this.closest('.entry-item');
                    const index = parseInt(entryItem.dataset.index);
                    
                    // Show edit form
                    entryItem.querySelector('.entry-content').classList.add('hidden');
                    entryItem.querySelector('.entry-actions').classList.add('hidden');
                    entryItem.querySelector('.entry-edit').classList.remove('hidden');
                });
            });
            
            // Cancel edit
            document.querySelectorAll('.edit-cancel').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const entryItem = this.closest('.entry-item');
                    
                    // Hide edit form
                    entryItem.querySelector('.entry-content').classList.remove('hidden');
                    entryItem.querySelector('.entry-actions').classList.remove('hidden');
                    entryItem.querySelector('.entry-edit').classList.add('hidden');
                });
            });
            
            // Save edit
            document.querySelectorAll('.edit-save').forEach(btn => {
                btn.addEventListener('click', async function(e) {
                    e.stopPropagation();
                    const entryItem = this.closest('.entry-item');
                    const index = parseInt(entryItem.dataset.index);
                    
                    const speaker = entryItem.querySelector('.edit-speaker').value;
                    const dialogue = entryItem.querySelector('.edit-dialogue').value;
                    
                    // Send update to server
                    try {
                        const response = await fetch(`/video/{{ video_id }}/entry/${index}`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ speaker, dialogue })
                        });
                        
                        if (response.ok) {
                            // Update display
                            entryItem.querySelector('.entry-content p').textContent = dialogue;
                            if (speaker) {
                                const speakerSpan = entryItem.querySelector('.bg-purple-100');
                                if (speakerSpan) {
                                    speakerSpan.textContent = speaker;
                                } else {
                                    // Add speaker badge if it doesn't exist
                                    const timestampDiv = entryItem.querySelector('.flex.justify-between > div:first-child');
                                    const newSpeakerSpan = document.createElement('span');
                                    newSpeakerSpan.className = 'ml-2 px-2 py-1 text-xs bg-purple-100 text-purple-800 rounded';
                                    newSpeakerSpan.textContent = speaker;
                                    timestampDiv.appendChild(newSpeakerSpan);
                                }
                            }
                            
                            // Mark as reviewed and corrected
                            entryItem.dataset.reviewed = 'true';
                            entryItem.classList.remove('bg-blue-50', 'border-blue-200');
                            entryItem.classList.add('bg-green-50', 'border-green-200');
                            
                            // Update badges
                            const badgesDiv = entryItem.querySelector('.flex.space-x-2');
                            if (!badgesDiv.querySelector('.bg-green-100')) {
                                const reviewedBadge = document.createElement('span');
                                reviewedBadge.className = 'px-2 py-1 text-xs bg-green-100 text-green-800 rounded';
                                reviewedBadge.textContent = 'Reviewed';
                                badgesDiv.appendChild(reviewedBadge);
                            }
                            
                            if (!badgesDiv.querySelector('.bg-blue-100')) {
                                const correctedBadge = document.createElement('span');
                                correctedBadge.className = 'px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded';
                                correctedBadge.textContent = 'Corrected';
                                badgesDiv.appendChild(correctedBadge);
                            }
                            
                            // Hide edit form
                            entryItem.querySelector('.entry-content').classList.remove('hidden');
                            entryItem.querySelector('.entry-actions').classList.remove('hidden');
                            entryItem.querySelector('.entry-edit').classList.add('hidden');
                            
                            alert('Entry saved successfully!');
                        } else {
                            alert('Error saving entry');
                        }
                    } catch (error) {
                        console.error('Error:', error);
                        alert('Error saving entry');
                    }
                });
            });
            
            // Approve button (mark as reviewed without changes)
            document.querySelectorAll('.approve-btn').forEach(btn => {
                btn.addEventListener('click', async function(e) {
                    e.stopPropagation();
                    const entryItem = this.closest('.entry-item');
                    const index = parseInt(entryItem.dataset.index);
                    
                    const speaker = entryItem.dataset.speaker || '';
                    const dialogue = entryItem.querySelector('.entry-content p').textContent;
                    
                    try {
                        const response = await fetch(`/video/{{ video_id }}/entry/${index}`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ speaker, dialogue })
                        });
                        
                        if (response.ok) {
                            // Mark as reviewed
                            entryItem.dataset.reviewed = 'true';
                            entryItem.classList.remove('bg-blue-50', 'border-blue-200');
                            entryItem.classList.add('bg-green-50', 'border-green-200');
                            
                            // Add reviewed badge
                            const badgesDiv = entryItem.querySelector('.flex.space-x-2');
                            if (!badgesDiv.querySelector('.bg-green-100')) {
                                const reviewedBadge = document.createElement('span');
                                reviewedBadge.className = 'px-2 py-1 text-xs bg-green-100 text-green-800 rounded';
                                reviewedBadge.textContent = 'Reviewed';
                                badgesDiv.appendChild(reviewedBadge);
                            }
                            
                            // Hide approve button
                            this.style.display = 'none';
                            
                            alert('Entry approved!');
                        }
                    } catch (error) {
                        console.error('Error:', error);
                        alert('Error approving entry');
                    }
                });
            });
            
            // Keyboard shortcuts
            document.addEventListener('keydown', function(e) {
                if (currentEntryIndex === null) return;
                
                switch(e.key) {
                    case 'e':
                        // Edit current entry
                        const entryItem = document.querySelector(`.entry-item[data-index="${currentEntryIndex}"]`);
                        if (entryItem) {
                            entryItem.querySelector('.edit-btn').click();
                        }
                        break;
                    case 'a':
                        // Approve current entry
                        const approveBtn = document.querySelector(`.entry-item[data-index="${currentEntryIndex}"] .approve-btn`);
                        if (approveBtn) {
                            approveBtn.click();
                        }
                        break;
                    case 'ArrowDown':
                        // Next entry
                        e.preventDefault();
                        navigateEntry(1);
                        break;
                    case 'ArrowUp':
                        // Previous entry
                        e.preventDefault();
                        navigateEntry(-1);
                        break;
                }
            });
            
            function filterEntries(filterType) {
                document.querySelectorAll('.entry-item').forEach(item => {
                    const isLowConfidence = parseFloat(item.dataset.confidence) < 0.8;
                    const isReviewed = item.dataset.reviewed === 'true';
                    
                    let show = true;
                    
                    if (filterType === 'low') {
                        show = isLowConfidence && !isReviewed;
                    } else if (filterType === 'unreviewed') {
                        show = !isReviewed;
                    }
                    // 'all' filter shows everything
                    
                    item.style.display = show ? 'block' : 'none';
                });
            }
            
            function navigateEntry(direction) {
                const entries = Array.from(document.querySelectorAll('.entry-item'))
                    .filter(item => item.style.display !== 'none');
                
                if (entries.length === 0) return;
                
                let currentIndex = entries.findIndex(item => 
                    parseInt(item.dataset.index) === currentEntryIndex);
                
                if (currentIndex === -1) currentIndex = 0;
                
                let newIndex = currentIndex + direction;
                if (newIndex < 0) newIndex = entries.length - 1;
                if (newIndex >= entries.length) newIndex = 0;
                
                entries[newIndex].click();
            }
        });
    </script>
</body>
</html>
```

### Implementation Notes for Stage 4

#### Dependencies Required
```txt
flask>=3.0.0
```

#### Directory Structure
```
project/
├── templates/
│   ├── dashboard.html
│   └── review.html
└── stage4_review.py
```

#### Key Features Implemented
1. **Dashboard**: Shows all videos with status indicators and progress tracking
2. **Review Interface**: Side-by-side frame display and text editing
3. **Filtering**: By low confidence (<0.8) and unreviewed entries
4. **Keyboard Shortcuts**:
    - `e` to edit current entry
    - `a` to approve current entry
    - Arrow keys to navigate
5. **Auto-save**: Updates are saved immediately to `reviewed/{video_id}.json`
6. **Progress Tracking**: Updates `progress/{video_id}.json` with review statistics

#### Running the Review UI
```bash
python stage4_review.py
```
Access at: http://127.0.0.1:5000/

#### Prerequisites
- Stage 1-3 must be completed to have `raw/{video_id}.json` files
- `utils.py` must be available with helper functions
- `metadata/{video_id}.json` files must exist for video information
- `frames/{video_id}/` directories must exist for frame images

## Stage 5 Implementation Phase - Output Generation

### Task 6.1: Create stage5_output.py

```python
# stage5_output.py - Stage 5: Archive output generation
import os
import glob
from utils import load_json, save_json, update_progress, sanitize_filename

def group_by_chapter():
    """Group reviewed videos by chapter."""
    chapters = {}
    
    reviewed_files = glob.glob("reviewed/*.json")
    
    for reviewed_file in reviewed_files:
        reviewed = load_json(reviewed_file)
        if not reviewed or "video_id" not in reviewed:
            continue
        
        video_id = reviewed["video_id"]
        
        # Load metadata
        metadata = load_json(f"metadata/{video_id}.json")
        if not metadata:
            print(f"  Warning: No metadata for {video_id}, skipping")
            continue
        
        chapter = metadata.get("chapter", "Unknown")
        
        # Initialize chapter data if not exists
        if chapter not in chapters:
            chapters[chapter] = {
                "chapter_name": chapter,
                "source_videos": [],
                "dialogues": []
            }
        
        # Add source video info
        chapters[chapter]["source_videos"].append({
            "video_id": video_id,
            "title": metadata.get("title", ""),
            "url": metadata.get("url", ""),
            "upload_date": metadata.get("upload_date", "")
        })
        
        # Add dialogues
        for entry in reviewed.get("entries", []):
            # Only include reviewed entries
            if not entry.get("reviewed", False):
                continue
            
            chapters[chapter]["dialogues"].append({
                "speaker": entry.get("speaker"),
                "text": entry.get("dialogue", ""),
                "timestamp": entry.get("timestamp", 0),
                "source_video_id": video_id
            })
        
        # Mark video as processed in output stage
        update_progress(video_id, "output", {"status": "complete"})
    
    return chapters

def sort_chapter_data(chapters):
    """Sort dialogues within each chapter."""
    for chapter_name, data in chapters.items():
        # Sort source videos by upload date
        data["source_videos"].sort(key=lambda v: v.get("upload_date", ""))
        
        # Build video order map for sorting dialogues
        video_order = {v["video_id"]: i for i, v in enumerate(data["source_videos"])}
        
        # Sort dialogues by video order, then timestamp
        data["dialogues"].sort(key=lambda d: (
            video_order.get(d["source_video_id"], 999),
            d.get("timestamp", 0)
        ))
    
    return chapters

def save_archive_files(chapters):
    """Save each chapter to archive file."""
    os.makedirs("archive", exist_ok=True)
    
    saved_count = 0
    for chapter_name, data in chapters.items():
        if not data["dialogues"]:
            print(f"  Skipping {chapter_name}: No reviewed dialogues")
            continue
        
        filename = sanitize_filename(chapter_name)
        filepath = f"archive/{filename}.json"
        
        save_json(filepath, data)
        print(f"  Saved {chapter_name}: {len(data['dialogues'])} dialogues from {len(data['source_videos'])} videos")
        saved_count += 1
    
    return saved_count

def main():
    """Main entry point."""
    print("Generating archive files...")
    
    # Check for reviewed files
    reviewed_files = glob.glob("reviewed/*.json")
    if not reviewed_files:
        print("No reviewed files found. Run stage4_review.py and review some videos first.")
        return
    
    print(f"Found {len(reviewed_files)} reviewed files")
    
    # Group by chapter
    chapters = group_by_chapter()
    if not chapters:
        print("No chapters found with reviewed data")
        return
    
    print(f"Grouped into {len(chapters)} chapters")
    
    # Sort data
    chapters = sort_chapter_data(chapters)
    
    # Save archive files
    saved = save_archive_files(chapters)
    
    print(f"\nSummary: Saved {saved} archive files to archive/ directory")

if __name__ == "__main__":
    main()
```

---

### Utilities Phase

#### Task 7.1: Create progress.py query tool

```python
# progress.py - Progress query tool
import sys
import json
import glob
from utils import load_json

def format_duration(seconds):
    """Format seconds into HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

def show_video_progress(video_id):
    """Show detailed progress for a single video."""
    progress = load_json(f"progress/{video_id}.json")
    if not progress:
        print(f"Video {video_id} not found in progress tracking")
        return False
    
    metadata = load_json(f"metadata/{video_id}.json") or {}
    
    print(f"\n{'='*60}")
    print(f"Video: {video_id}")
    print(f"Title: {metadata.get('title', 'Unknown')}")
    print(f"Chapter: {metadata.get('chapter', 'Unknown')}")
    print(f"Current Stage: {progress['status'].upper()}")
    print(f"{'='*60}")
    
    for stage_name, stage_data in progress["stages"].items():
        status = stage_data.get("status", "pending").upper()
        print(f"\n{stage_name.upper():12} : {status}")
        
        if stage_name == "input" and stage_data.get("timestamp"):
            print(f"  Completed: {stage_data['timestamp']}")
        
        elif stage_name == "acquire":
            frames_total = stage_data.get("frames_total", 0)
            last_frame = stage_data.get("last_frame", 0)
            if frames_total > 0:
                percent = (last_frame / frames_total) * 100 if frames_total > 0 else 0
                print(f"  Frames: {last_frame}/{frames_total} ({percent:.1f}%)")
                print(f"  Duration: {format_duration(last_frame)}")
            if stage_data.get("errors"):
                print(f"  Errors: {len(stage_data['errors'])}")
        
        elif stage_name == "extract":
            processed = stage_data.get("frames_processed", 0)
            extracted = stage_data.get("entries_extracted", 0)
            low_conf = stage_data.get("low_confidence_count", 0)
            skipped = stage_data.get("frames_skipped", 0)
            
            if processed > 0:
                print(f"  Processed: {processed} frames")
                print(f"  Extracted: {extracted} entries")
                print(f"  Skipped: {skipped} frames")
                print(f"  Low confidence: {low_conf} entries")
        
        elif stage_name == "review":
            total = stage_data.get("total_entries", 0)
            reviewed = stage_data.get("reviewed", 0)
            corrected = stage_data.get("corrected", 0)
            pending_low = stage_data.get("pending_low_confidence", 0)
            
            if total > 0:
                percent = (reviewed / total) * 100 if total > 0 else 0
                print(f"  Reviewed: {reviewed}/{total} ({percent:.1f}%)")
                print(f"  Corrected: {corrected}")
                if pending_low > 0:
                    print(f"  Pending low confidence: {pending_low}")
    
    return True

def show_all_progress():
    """Show summary progress for all videos."""
    progress_files = glob.glob("progress/*.json")
    if not progress_files:
        print("No progress files found")
        return
    
    print(f"\n{'='*80}")
    print(f"{'VIDEO ID':15} {'CHAPTER':25} {'STAGE':12} {'PROGRESS':25}")
    print(f"{'='*80}")
    
    stats = {
        "input": 0,
        "acquire": 0,
        "extract": 0,
        "review": 0,
        "complete": 0,
        "error": 0
    }
    
    for progress_file in progress_files:
        progress = load_json(progress_file)
        if not progress:
            continue
        
        video_id = progress["video_id"]
        metadata = load_json(f"metadata/{video_id}.json") or {}
        chapter = metadata.get("chapter", "Unknown")[:24]
        stage = progress["status"]
        
        # Update stats
        if stage in stats:
            stats[stage] += 1
        
        # Format progress info
        progress_info = ""
        if stage == "acquire":
            frames = progress["stages"]["acquire"].get("frames_total", 0)
            last = progress["stages"]["acquire"].get("last_frame", 0)
            if frames > 0:
                percent = (last / frames) * 100
                progress_info = f"{last}/{frames} frames ({percent:.1f}%)"
        
        elif stage == "extract":
            extracted = progress["stages"]["extract"].get("entries_extracted", 0)
            low_conf = progress["stages"]["extract"].get("low_confidence_count", 0)
            if extracted > 0:
                progress_info = f"{extracted} entries ({low_conf} low conf)"
        
        elif stage == "review":
            total = progress["stages"]["review"].get("total_entries", 0)
            reviewed = progress["stages"]["review"].get("reviewed", 0)
            if total > 0:
                percent = (reviewed / total) * 100
                progress_info = f"{reviewed}/{total} ({percent:.1f}%)"
        
        print(f"{video_id:15} {chapter:25} {stage:12} {progress_info:25}")
    
    print(f"{'='*80}")
    print(f"\nSummary:")
    print(f"  Input:       {stats['input']}")
    print(f"  Acquire:     {stats['acquire']}")
    print(f"  Extract:     {stats['extract']}")
    print(f"  Review:      {stats['review']}")
    print(f"  Complete:    {stats['complete']}")
    print(f"  Error:       {stats['error']}")
    print(f"  Total:       {len(progress_files)}")

def main():
    """Main entry point."""
    if len(sys.argv) == 1:
        # Show all videos summary
        show_all_progress()
    elif sys.argv[1].lower() == "all":
        # Show all videos summary (explicit)
        show_all_progress()
    else:
        # Show single video details
        video_id = sys.argv[1]
        show_video_progress(video_id)

if __name__ == "__main__":
    main()
```

---

## Complete Technical Implementation Plan Summary

### Workspace Preparation Phase ✓
1. **Directory structure** - metadata/, frames/, raw/, reviewed/, archive/, progress/, templates/
2. **requirements.txt** - yt-dlp, easyocr, flask, opencv-python, numpy
3. **config.json** - Default configuration with subtitle crop coordinates
4. **utils.py** - Shared helper functions (load_json, save_json, log_error, etc.)

### Stage 1 Implementation Phase ✓
- **stage1_input.py** - Process URLs from urls.txt, fetch metadata with yt-dlp, initialize progress tracking

### Stage 2 Implementation Phase ✓
- **calibrate.py** - OpenCV GUI for selecting subtitle crop coordinates
- **stage2_acquire.py** - Extract frames from videos using ffmpeg with resume support

### Stage 3 Implementation Phase ✓
- **stage3_extract.py** - OCR extraction with EasyOCR, deduplication, confidence tracking

### Stage 4 Implementation Phase ✓
- **stage4_review.py** - Flask web UI with dashboard and review interfaces
- **templates/dashboard.html** - Video status dashboard with Tailwind CSS
- **templates/review.html** - Interactive review interface with frame display

### Stage 5 Implementation Phase ✓
- **stage5_output.py** - Group reviewed dialogues by chapter, generate archive JSON files

### Utilities Phase ✓
- **progress.py** - CLI tool for querying video progress (single or all videos)

---

## Execution Workflow

### 1. Initial Setup
```bash
# Create directories
mkdir -p metadata frames raw reviewed archive progress templates

# Install dependencies
pip install -r requirements.txt

# Create config.json (or use calibrate.py to generate)
python calibrate.py
```

### 2. Process Videos
```bash
# Stage 1: Input processing
python stage1_input.py

# Stage 2: Frame acquisition
python stage2_acquire.py

# Stage 3: OCR extraction
python stage3_extract.py
```

### 3. Review and Correct
```bash
# Stage 4: Start review web UI
python stage4_review.py
# Access at http://127.0.0.1:5000/
```

### 4. Generate Archive
```bash
# Stage 5: Create final archive files
python stage5_output.py
```

### 5. Monitor Progress
```bash
# Check all videos
python progress.py

# Check specific video
python progress.py <video_id>
```

---

## Configuration Notes

### config.json Defaults
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
  "confidence_threshold": 0.80
}
```

### Directory Structure
```
project/
├── urls.txt                    # Input URLs (one per line)
├── config.json                 # Pipeline configuration
├── requirements.txt            # Python dependencies
├── utils.py                    # Shared utility functions
├── stage1_input.py            # Stage 1: Input processing
├── stage2_acquire.py          # Stage 2: Frame acquisition
├── calibrate.py               # Subtitle region calibration
├── stage3_extract.py          # Stage 3: OCR extraction
├── stage4_review.py           # Stage 4: Review web UI
├── stage5_output.py           # Stage 5: Archive generation
├── progress.py                # Progress query tool
├── errors.log                 # Error log file
├── metadata/                  # Stage 1 output
│   └── {video_id}.json
├── frames/                    # Stage 2 output
│   └── {video_id}/
│       ├── frame_00001.png
│       └── ...
├── raw/                       # Stage 3 output
│   └── {video_id}.json
├── reviewed/                  # Stage 4 output
│   └── {video_id}.json
├── archive/                   # Stage 5 output
│   └── {chapter}.json
├── progress/                  # Progress tracking
│   └── {video_id}.json
└── templates/                 # Flask templates
    ├── dashboard.html
    └── review.html
```

---

## Error Handling and Recovery

### Resume Capabilities
1. **Stage 2**: Tracks last extracted frame, resumes from that point
2. **Stage 3**: Processes only unprocessed frames
3. **Stage 4**: Maintains reviewed state, can resume partial reviews
4. **Stage 5**: Only processes videos with completed review stage

### Error Logging
- All errors logged to `errors.log` with timestamp and stage
- Failed videos can be retried individually
- Progress tracking preserves state for resume

### Quality Control
1. **Confidence Threshold**: Flags entries with <0.8 confidence for review
2. **Deduplication**: Removes consecutive similar text (90% similarity)
3. **Review Interface**: Highlights low-confidence entries for priority review

---

## Performance Considerations

### GPU Acceleration
- EasyOCR auto-detects and uses GPU if available
- Falls back to CPU if GPU not available
- Configure via `easyocr.Reader(['en'], gpu=True)`

### Memory Management
- Processes videos sequentially, not in parallel
- Frames extracted at 1 fps to reduce data volume
- OCR processes frames one at a time

### Storage Requirements
- Frames: ~100KB each at 800x100 resolution
- 1-hour video at 1 fps = 3,600 frames = ~360MB
- JSON metadata: Minimal storage
- Archive files: Text-only, minimal storage

---

## Testing Recommendations

### Sample Test Workflow
1. Create `urls.txt` with 2-3 test YouTube URLs
2. Run through all stages with test data
3. Verify output files are created correctly
4. Test review interface functionality
5. Validate final archive JSON structure

### Validation Checks
- Metadata files contain correct video information
- Frames are properly cropped to subtitle region
- OCR extracts text with reasonable confidence
- Review interface saves corrections correctly
- Archive files group dialogues by chapter correctly

---

## Maintenance and Extensions

### Potential Enhancements
1. **Batch Processing**: Add parallel processing for multiple videos
2. **Advanced OCR**: Add language detection or custom OCR models
3. **Export Formats**: Add CSV, TXT, or other export formats
4. **API Integration**: Add REST API for programmatic access
5. **Cloud Storage**: Add support for S3 or cloud storage backends

### Monitoring
- Use `progress.py` for pipeline status monitoring
- Check `errors.log` for troubleshooting
- Monitor disk usage for frame storage

This implementation plan provides a complete, traceable task list for building the HI3 Story Dialogue Archive pipeline from scratch. Each component is modular and follows the specifications in the pipeline techspec document.
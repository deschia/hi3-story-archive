import json
import os
import re
import logging
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
METADATA_DIR = BASE_DIR / "metadata"
FRAMES_DIR = BASE_DIR / "frames"
RAW_DIR = BASE_DIR / "raw"
REVIEWED_DIR = BASE_DIR / "reviewed"
ARCHIVE_DIR = BASE_DIR / "archive"
PROGRESS_DIR = BASE_DIR / "progress"
CONFIG_FILE = BASE_DIR / "config.json"
ERRORS_LOG = BASE_DIR / "errors.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_video_id(url):
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def init_progress(video_id, url):
    progress = {
        "video_id": video_id,
        "url": url,
        "status": "input",
        "stages": {
            "input": {
                "status": "complete",
                "timestamp": datetime.now().isoformat()
            },
            "acquire": {
                "status": "pending",
                "frames_total": 0,
                "last_frame": 0,
                "errors": []
            },
            "extract": {
                "status": "pending",
                "frames_processed": 0,
                "frames_skipped": 0,
                "entries_extracted": 0,
                "low_confidence_count": 0,
                "errors": []
            },
            "review": {
                "status": "pending",
                "total_entries": 0,
                "reviewed": 0,
                "corrected": 0,
                "pending_low_confidence": 0
            },
            "output": {
                "status": "pending"
            }
        }
    }
    save_json(PROGRESS_DIR / f"{video_id}.json", progress)
    return progress


def load_progress(video_id):
    path = PROGRESS_DIR / f"{video_id}.json"
    if path.exists():
        return load_json(path)
    return None


def update_progress(video_id, stage, data):
    progress = load_progress(video_id)
    if progress:
        progress["stages"][stage].update(data)
        if "status" in data:
            stage_order = ["input", "acquire", "extract", "review", "output"]
            if data["status"] == "complete":
                current_idx = stage_order.index(stage)
                if current_idx < len(stage_order) - 1:
                    progress["status"] = stage_order[current_idx + 1]
                else:
                    progress["status"] = "complete"
            elif data["status"] in ["in_progress", "error"]:
                progress["status"] = stage
        save_json(PROGRESS_DIR / f"{video_id}.json", progress)
    return progress


def log_error(video_id, error_msg):
    timestamp = datetime.now().isoformat()
    with open(ERRORS_LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {video_id}: {error_msg}\n")
    logger.error(f"{video_id}: {error_msg}")


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:100]


def get_videos_at_stage(stage, status=None):
    videos = []
    for progress_file in PROGRESS_DIR.glob("*.json"):
        progress = load_json(progress_file)
        if status:
            if progress["stages"].get(stage, {}).get("status") == status:
                videos.append(progress["video_id"])
        else:
            if progress["status"] == stage:
                videos.append(progress["video_id"])
    return videos

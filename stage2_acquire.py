import subprocess
import os
import signal
import sys
import threading
import time
from pathlib import Path
from utils import (
    load_config, load_json, load_progress, update_progress,
    log_error, logger, METADATA_DIR, FRAMES_DIR
)

_current_video_id = None
_ffmpeg_process = None
_stop_monitor = False


def get_stream_url(video_url, quality=720):
    try:
        result = subprocess.run(
            ["yt-dlp", "-g", "-f", f"bv[height<={quality}]", video_url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            return None, result.stderr
        return result.stdout.strip().split('\n')[0], None
    except Exception as e:
        return None, str(e)


def count_frames(video_id):
    frames_dir = FRAMES_DIR / video_id
    if not frames_dir.exists():
        return 0
    return len(list(frames_dir.glob("frame_*.png")))


def get_video_duration(video_url):
    try:
        result = subprocess.run(
            ["yt-dlp", "--get-duration", video_url],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            duration_str = result.stdout.strip()
            parts = duration_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return int(parts[0])
    except:
        pass
    return None


def _monitor_progress(video_id, total_frames, fps):
    global _stop_monitor
    last_count = 0
    while not _stop_monitor:
        current = count_frames(video_id)
        if current != last_count:
            if total_frames:
                print(f"\r  Frames: {current}/{total_frames} ({current*100//total_frames}%)", end="", flush=True)
            else:
                print(f"\r  Frames: {current}", end="", flush=True)
            last_count = current
        time.sleep(1)


def _handle_interrupt(signum, frame):
    global _current_video_id, _ffmpeg_process, _stop_monitor
    _stop_monitor = True
    print()
    logger.info("Interrupted by user, saving progress...")
    if _ffmpeg_process:
        _ffmpeg_process.terminate()
        try:
            _ffmpeg_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ffmpeg_process.kill()
    if _current_video_id:
        frames_count = count_frames(_current_video_id)
        update_progress(_current_video_id, "acquire", {
            "status": "interrupted",
            "last_frame": frames_count
        })
        logger.info(f"Saved progress: {frames_count} frames for {_current_video_id}")
    sys.exit(0)


def get_video_order():
    """Get video IDs in urls.txt order."""
    urls_path = Path(__file__).parent / "urls.txt"
    if not urls_path.exists():
        return None
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    from utils import extract_video_id
    return [extract_video_id(url) for url in urls if extract_video_id(url)]


def run_stage2(video_id=None):
    global _current_video_id, _ffmpeg_process, _stop_monitor
    
    signal.signal(signal.SIGINT, _handle_interrupt)
    signal.signal(signal.SIGTERM, _handle_interrupt)
    
    config = load_config()
    crop = config["subtitle_crop"]
    quality = config.get("video_quality", 720)
    fps = config.get("frame_rate", 1)
    
    crop_filter = f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}"
    
    stats = {"processed": 0, "skipped": 0, "errors": 0}
    
    video_order = get_video_order()
    
    if video_id:
        metadata_files = [METADATA_DIR / f"{video_id}.json"]
    elif video_order:
        metadata_files = [METADATA_DIR / f"{vid}.json" for vid in video_order]
        metadata_files = [f for f in metadata_files if f.exists()]
    else:
        metadata_files = list(METADATA_DIR.glob("*.json"))
    
    for metadata_file in metadata_files:
        if not metadata_file.exists():
            logger.warning(f"Metadata file not found: {metadata_file}")
            continue
            
        metadata = load_json(metadata_file)
        vid = metadata["video_id"]
        
        progress = load_progress(vid)
        if not progress:
            logger.warning(f"No progress file for {vid}")
            continue
        
        acquire_status = progress["stages"]["acquire"]["status"]
        if acquire_status == "complete":
            logger.info(f"Skipping {vid} - already acquired")
            stats["skipped"] += 1
            continue
        
        if acquire_status == "interrupted":
            last_frame = progress["stages"]["acquire"].get("last_frame", 0)
            logger.info(f"Resuming {vid} from frame {last_frame}")
        
        logger.info(f"Acquiring frames for {vid}")
        _current_video_id = vid
        update_progress(vid, "acquire", {"status": "in_progress"})
        
        stream_url, error = get_stream_url(metadata["url"], quality)
        if error:
            log_error(vid, f"Failed to get stream URL: {error}")
            update_progress(vid, "acquire", {"status": "error", "errors": [error]})
            stats["errors"] += 1
            continue
        
        duration = get_video_duration(metadata["url"])
        total_frames = duration * fps if duration else None
        
        frames_dir = FRAMES_DIR / vid
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        start_frame = progress["stages"]["acquire"].get("last_frame", 0)
        start_time = start_frame
        
        ffmpeg_cmd = [
            "ffmpeg",
            "-hwaccel", "auto",
            "-ss", str(start_time),
            "-i", stream_url,
            "-vf", f"fps={fps},{crop_filter}",
            "-start_number", str(start_frame + 1),
            "-q:v", "2",
            str(frames_dir / "frame_%05d.png")
        ]
        
        logger.info(f"Running ffmpeg for {vid} (starting at frame {start_frame})")
        
        try:
            _ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            _stop_monitor = False
            monitor_thread = threading.Thread(
                target=_monitor_progress,
                args=(vid, total_frames, fps),
                daemon=True
            )
            monitor_thread.start()
            
            stdout, stderr = _ffmpeg_process.communicate(timeout=3600)
            _stop_monitor = True
            print()
            result = subprocess.CompletedProcess(ffmpeg_cmd, _ffmpeg_process.returncode, stdout, stderr)
            _ffmpeg_process = None
            
            if result.returncode != 0 and "Output file is empty" not in result.stderr:
                log_error(vid, f"ffmpeg failed: {result.stderr[-500:]}")
                update_progress(vid, "acquire", {
                    "status": "error",
                    "last_frame": count_frames(vid),
                    "errors": [result.stderr[-200:]]
                })
                stats["errors"] += 1
                continue
            
            total_frames = count_frames(vid)
            update_progress(vid, "acquire", {
                "status": "complete",
                "frames_total": total_frames,
                "last_frame": total_frames
            })
            
            logger.info(f"Extracted {total_frames} frames for {vid}")
            stats["processed"] += 1
            _current_video_id = None
            
        except subprocess.TimeoutExpired:
            _ffmpeg_process = None
            log_error(vid, "ffmpeg timed out after 1 hour")
            update_progress(vid, "acquire", {
                "status": "error",
                "last_frame": count_frames(vid),
                "errors": ["Timeout after 1 hour"]
            })
            stats["errors"] += 1
        except Exception as e:
            _ffmpeg_process = None
            log_error(vid, f"Unexpected error: {e}")
            update_progress(vid, "acquire", {
                "status": "error",
                "last_frame": count_frames(vid),
                "errors": [str(e)]
            })
            stats["errors"] += 1
    
    logger.info(f"Stage 2 complete: {stats}")
    return stats


if __name__ == "__main__":
    import sys
    video_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_stage2(video_id)

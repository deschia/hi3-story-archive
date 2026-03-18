import os
import re
from pathlib import Path
from difflib import SequenceMatcher
import easyocr
from utils import (
    load_config, save_json, load_progress, update_progress,
    log_error, logger, FRAMES_DIR, RAW_DIR, PROGRESS_DIR
)

reader = None


def get_reader():
    global reader
    if reader is None:
        logger.info("Initializing EasyOCR reader...")
        reader = easyocr.Reader(['en'], gpu=True)
    return reader


def is_similar(text1, text2, threshold):
    if not text1 or not text2:
        return False
    return SequenceMatcher(None, text1, text2).ratio() >= threshold


def extract_frame_number(frame_path):
    match = re.search(r'frame_(\d+)\.png$', str(frame_path))
    if match:
        return int(match.group(1))
    return 0


def get_video_order():
    """Get video IDs in urls.txt order."""
    urls_path = Path(__file__).parent / "urls.txt"
    if not urls_path.exists():
        return None
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    from utils import extract_video_id
    return [extract_video_id(url) for url in urls if extract_video_id(url)]


def run_stage3(video_id=None):
    config = load_config()
    similarity_threshold = config.get("similarity_threshold", 0.90)
    confidence_threshold = config.get("confidence_threshold", 0.80)
    
    stats = {"processed": 0, "skipped": 0, "errors": 0}
    
    video_order = get_video_order()
    
    if video_id:
        video_ids = [video_id]
    elif video_order:
        video_ids = []
        for vid in video_order:
            progress = load_progress(vid)
            if progress and progress["stages"]["acquire"]["status"] == "complete":
                if progress["stages"]["extract"]["status"] != "complete":
                    video_ids.append(vid)
    else:
        video_ids = []
        for progress_file in PROGRESS_DIR.glob("*.json"):
            progress = load_progress(progress_file.stem)
            if progress and progress["stages"]["acquire"]["status"] == "complete":
                if progress["stages"]["extract"]["status"] != "complete":
                    video_ids.append(progress_file.stem)
    
    ocr = get_reader()
    
    for vid in video_ids:
        progress = load_progress(vid)
        if not progress:
            logger.warning(f"No progress file for {vid}")
            continue
        
        if progress["stages"]["extract"]["status"] == "complete":
            logger.info(f"Skipping {vid} - already extracted")
            stats["skipped"] += 1
            continue
        
        frames_dir = FRAMES_DIR / vid
        if not frames_dir.exists():
            logger.warning(f"Frames directory not found for {vid}")
            stats["errors"] += 1
            continue
        
        logger.info(f"Extracting text from {vid}")
        update_progress(vid, "extract", {"status": "in_progress"})
        
        frames = sorted(frames_dir.glob("frame_*.png"), key=lambda p: extract_frame_number(p))
        entries = []
        previous_text = None
        errors = []
        skipped = 0
        
        for i, frame_path in enumerate(frames):
            frame_num = extract_frame_number(frame_path)
            timestamp = frame_num
            
            if i % 100 == 0:
                logger.info(f"  Processing frame {i+1}/{len(frames)}")
            
            try:
                result = ocr.readtext(str(frame_path))
            except Exception as e:
                errors.append(f"{frame_path.name}: {str(e)}")
                continue
            
            if not result:
                skipped += 1
                continue
            
            text = "\n".join([r[1] for r in result])
            confidence = min([r[2] for r in result]) if result else 0
            
            if is_similar(text, previous_text, similarity_threshold):
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
                "confidence": round(confidence, 3),
                "frame": frame_path.name
            })
            
            previous_text = text
        
        save_json(RAW_DIR / f"{vid}.json", {"video_id": vid, "entries": entries})
        
        low_confidence = sum(1 for e in entries if e["confidence"] < confidence_threshold)
        
        update_progress(vid, "extract", {
            "status": "complete",
            "frames_processed": len(frames),
            "frames_skipped": skipped,
            "entries_extracted": len(entries),
            "low_confidence_count": low_confidence,
            "errors": errors[:10]
        })
        
        logger.info(f"Extracted {len(entries)} entries from {vid} ({low_confidence} low confidence)")
        stats["processed"] += 1
    
    logger.info(f"Stage 3 complete: {stats}")
    return stats


if __name__ == "__main__":
    import sys
    video_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_stage3(video_id)

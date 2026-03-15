from pathlib import Path
from utils import (
    load_json, save_json, load_progress, update_progress,
    sanitize_filename, logger, REVIEWED_DIR, METADATA_DIR, ARCHIVE_DIR, PROGRESS_DIR
)


def run_stage5():
    chapters = {}
    stats = {"processed": 0, "chapters": 0}
    
    reviewed_files = list(REVIEWED_DIR.glob("*.json"))
    
    if not reviewed_files:
        logger.warning("No reviewed files found")
        return stats
    
    for reviewed_file in reviewed_files:
        reviewed = load_json(reviewed_file)
        video_id = reviewed["video_id"]
        
        progress = load_progress(video_id)
        if not progress:
            logger.warning(f"No progress file for {video_id}")
            continue
        
        if progress["stages"]["review"]["status"] != "complete":
            logger.info(f"Skipping {video_id} - review not complete")
            continue
        
        metadata_file = METADATA_DIR / f"{video_id}.json"
        if not metadata_file.exists():
            logger.warning(f"No metadata for {video_id}")
            continue
        
        metadata = load_json(metadata_file)
        chapter = metadata["chapter"]
        
        if chapter not in chapters:
            chapters[chapter] = {
                "chapter_name": chapter,
                "source_videos": [],
                "dialogues": []
            }
        
        video_exists = any(v["video_id"] == video_id for v in chapters[chapter]["source_videos"])
        if not video_exists:
            chapters[chapter]["source_videos"].append({
                "video_id": video_id,
                "title": metadata["title"],
                "url": metadata["url"],
                "upload_date": metadata["upload_date"]
            })
        
        for entry in reviewed["entries"]:
            chapters[chapter]["dialogues"].append({
                "speaker": entry.get("speaker"),
                "text": entry.get("dialogue", ""),
                "timestamp": entry.get("timestamp", 0),
                "source_video_id": video_id
            })
        
        update_progress(video_id, "output", {"status": "complete"})
        stats["processed"] += 1
    
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    
    for chapter_name, data in chapters.items():
        data["source_videos"].sort(key=lambda v: v["upload_date"])
        
        video_order = {v["video_id"]: i for i, v in enumerate(data["source_videos"])}
        
        data["dialogues"].sort(key=lambda d: (video_order.get(d["source_video_id"], 0), d["timestamp"]))
        
        filename = sanitize_filename(chapter_name)
        save_json(ARCHIVE_DIR / f"{filename}.json", data)
        
        logger.info(f"Generated archive: {filename}.json ({len(data['dialogues'])} dialogues)")
        stats["chapters"] += 1
    
    logger.info(f"Stage 5 complete: {stats}")
    return stats


if __name__ == "__main__":
    run_stage5()

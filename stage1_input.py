import subprocess
import json
from pathlib import Path
from utils import (
    extract_video_id, save_json, load_json, init_progress,
    log_error, logger, METADATA_DIR, BASE_DIR
)


def run_stage1(urls_file=None):
    urls_path = Path(urls_file) if urls_file else BASE_DIR / "urls.txt"
    
    if not urls_path.exists():
        logger.error(f"URLs file not found: {urls_path}")
        return {"processed": 0, "skipped": 0, "errors": 0}
    
    stats = {"processed": 0, "skipped": 0, "errors": 0}
    
    with open(urls_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    logger.info(f"Found {len(urls)} URLs to process")
    
    for url in urls:
        video_id = extract_video_id(url)
        
        if not video_id:
            log_error("unknown", f"Could not extract video ID from URL: {url}")
            stats["errors"] += 1
            continue
        
        metadata_path = METADATA_DIR / f"{video_id}.json"
        if metadata_path.exists():
            logger.info(f"Skipping {video_id} - already processed")
            stats["skipped"] += 1
            continue
        
        logger.info(f"Fetching metadata for {video_id}")
        
        try:
            result = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-download", url],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                log_error(video_id, f"yt-dlp failed: {result.stderr}")
                stats["errors"] += 1
                continue
            
            yt_metadata = json.loads(result.stdout)
            
            title = yt_metadata.get("title", "")
            chapter = title.split("|")[0].strip() if "|" in title else title
            
            metadata = {
                "video_id": video_id,
                "url": url,
                "title": title,
                "chapter": chapter,
                "upload_date": yt_metadata.get("upload_date", "")
            }
            
            save_json(metadata_path, metadata)
            init_progress(video_id, url)
            
            logger.info(f"Saved metadata for {video_id}: {chapter}")
            stats["processed"] += 1
            
        except subprocess.TimeoutExpired:
            log_error(video_id, "yt-dlp timed out")
            stats["errors"] += 1
        except json.JSONDecodeError as e:
            log_error(video_id, f"Failed to parse yt-dlp output: {e}")
            stats["errors"] += 1
        except Exception as e:
            log_error(video_id, f"Unexpected error: {e}")
            stats["errors"] += 1
    
    logger.info(f"Stage 1 complete: {stats}")
    return stats


if __name__ == "__main__":
    import sys
    urls_file = sys.argv[1] if len(sys.argv) > 1 else None
    run_stage1(urls_file)

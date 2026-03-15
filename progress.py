import sys
from utils import load_json, PROGRESS_DIR


def show_progress(video_id):
    progress_file = PROGRESS_DIR / f"{video_id}.json"
    
    if not progress_file.exists():
        print(f"No progress file found for video: {video_id}")
        return
    
    progress = load_json(progress_file)
    
    print(f"Video: {video_id}")
    print(f"Current Stage: {progress['status']}")
    print()
    
    for stage, data in progress["stages"].items():
        print(f"{stage}: {data.get('status', 'unknown')}")
        
        if stage == "acquire":
            if data.get("frames_total"):
                print(f"  Frames: {data['frames_total']}")
            if data.get("errors"):
                print(f"  Errors: {len(data['errors'])}")
        
        if stage == "extract":
            if data.get("entries_extracted"):
                print(f"  Entries: {data['entries_extracted']}")
            if data.get("low_confidence_count"):
                print(f"  Low confidence: {data['low_confidence_count']}")
        
        if stage == "review":
            if data.get("total_entries"):
                print(f"  Reviewed: {data.get('reviewed', 0)}/{data['total_entries']}")
            if data.get("corrected"):
                print(f"  Corrected: {data['corrected']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python progress.py <video_id>")
        sys.exit(1)
    
    show_progress(sys.argv[1])

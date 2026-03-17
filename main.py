import argparse
import sys
from pathlib import Path
from utils import logger, load_progress, PROGRESS_DIR, load_json


def cmd_stage1(args):
    from stage1_input import run_stage1
    return run_stage1(args.urls)


def cmd_stage2(args):
    from stage2_acquire import run_stage2
    return run_stage2(args.video_id)


def cmd_stage3(args):
    from stage3_extract import run_stage3
    return run_stage3(args.video_id)


def cmd_spellcheck(args):
    from stage3_5_spellcheck import run_spellcheck
    return run_spellcheck(args.video_id)


def cmd_build_dictionary(args):
    from stage3_5_spellcheck import build_dictionary
    return build_dictionary()


def cmd_stage4(args):
    from stage4_review import run_review_server
    run_review_server(host=args.host, port=args.port, debug=args.debug)


def cmd_stage5(args):
    from stage5_output import run_stage5
    return run_stage5()


def cmd_calibrate(args):
    from calibrate import main as run_calibrate
    run_calibrate()


def cmd_status(args):
    if args.video_id:
        progress = load_progress(args.video_id)
        if not progress:
            print(f"Video {args.video_id} not found")
            return
        
        print(f"\nVideo: {progress['video_id']}")
        print(f"URL: {progress['url']}")
        print(f"Current Stage: {progress['status']}")
        print()
        
        for stage, data in progress["stages"].items():
            status = data.get("status", "unknown")
            print(f"  {stage}: {status}")
            
            if stage == "acquire" and data.get("frames_total"):
                print(f"    Frames: {data['frames_total']}")
            if stage == "extract" and data.get("entries_extracted"):
                print(f"    Entries: {data['entries_extracted']}, Low confidence: {data.get('low_confidence_count', 0)}")
            if stage == "spellcheck":
                print(f"    Auto-corrected: {data.get('auto_corrected_count', 0)}")
                print(f"    Flagged: {data.get('flagged_count', 0)}")
            if stage == "review" and data.get("total_entries"):
                print(f"    Reviewed: {data['reviewed']}/{data['total_entries']}")
            if data.get("errors"):
                print(f"    Errors: {len(data['errors'])}")
    else:
        progress_files = list(PROGRESS_DIR.glob("*.json"))
        if not progress_files:
            print("No videos in progress")
            return
        
        stages = {"input": 0, "acquire": 0, "extract": 0, "spellcheck": 0, "review": 0, "complete": 0}
        errors = 0
        
        for pf in progress_files:
            progress = load_json(pf)
            status = progress.get("status", "input")
            if status in stages:
                stages[status] += 1
            for stage_data in progress["stages"].values():
                if stage_data.get("status") == "error":
                    errors += 1
                    break
        
        print(f"\nTotal videos: {len(progress_files)}")
        print(f"  Stage 1 (Input):      {stages['input']}")
        print(f"  Stage 2 (Acquire):    {stages['acquire']}")
        print(f"  Stage 3 (Extract):    {stages['extract']}")
        print(f"  Stage 3.5 (Spellcheck): {stages['spellcheck']}")
        print(f"  Stage 4 (Review):     {stages['review']}")
        print(f"  Complete:             {stages['complete']}")
        print(f"  With errors:          {errors}")


def cmd_run_all(args):
    from stage1_input import run_stage1
    from stage2_acquire import run_stage2
    from stage3_extract import run_stage3
    from stage3_5_spellcheck import run_spellcheck
    from stage5_output import run_stage5
    
    logger.info("Running full pipeline...")
    
    logger.info("\n=== Stage 1: Input ===")
    stats1 = run_stage1(args.urls)
    print(f"Stage 1: {stats1}")
    
    if not args.skip_acquire:
        logger.info("\n=== Stage 2: Acquire ===")
        stats2 = run_stage2()
        print(f"Stage 2: {stats2}")
    
    logger.info("\n=== Stage 3: Extract ===")
    stats3 = run_stage3()
    print(f"Stage 3: {stats3}")
    
    logger.info("\n=== Stage 3.5: Spellcheck ===")
    stats35 = run_spellcheck()
    print(f"Stage 3.5: {stats35}")
    
    logger.info("\n=== Stage 4: Review ===")
    print("Review stage requires manual intervention.")
    print("Run: python main.py review")
    
    if args.auto_approve:
        logger.info("Auto-approving all entries (skipping manual review)")
        from utils import SPELLCHECKED_DIR, REVIEWED_DIR, save_json, update_progress
        
        for spellchecked_file in SPELLCHECKED_DIR.glob("*.json"):
            video_id = spellchecked_file.stem
            reviewed_path = REVIEWED_DIR / f"{video_id}.json"
            
            spellchecked = load_json(spellchecked_file)
            for entry in spellchecked["entries"]:
                entry["reviewed"] = True
                entry["corrected"] = False
            
            save_json(reviewed_path, spellchecked)
            update_progress(video_id, "review", {
                "status": "complete",
                "total_entries": len(spellchecked["entries"]),
                "reviewed": len(spellchecked["entries"]),
                "corrected": 0,
                "pending_low_confidence": 0
            })
        
        logger.info("\n=== Stage 5: Output ===")
        stats5 = run_stage5()
        print(f"Stage 5: {stats5}")


def main():
    parser = argparse.ArgumentParser(
        description="HI3 Story Archive Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py stage1 --urls urls.txt    Fetch video metadata
  python main.py stage2                    Extract frames from all videos
  python main.py stage2 --video-id ABC123  Extract frames for specific video
  python main.py stage3                    Run OCR on all acquired videos
  python main.py spellcheck                Run spellcheck on all extracted videos
  python main.py build-dictionary          Build custom dictionary from reviewed entries
  python main.py review                    Start review web UI
  python main.py stage5                    Generate archive files
  python main.py calibrate                 Run calibration tool
  python main.py status                    Show pipeline status
  python main.py status --video-id ABC123  Show status for specific video
  python main.py run-all --urls urls.txt   Run full pipeline
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    p1 = subparsers.add_parser("stage1", help="Stage 1: Fetch video metadata")
    p1.add_argument("--urls", "-u", help="Path to urls.txt file")
    p1.set_defaults(func=cmd_stage1)
    
    p2 = subparsers.add_parser("stage2", help="Stage 2: Extract video frames")
    p2.add_argument("--video-id", "-v", help="Process specific video only")
    p2.set_defaults(func=cmd_stage2)
    
    p3 = subparsers.add_parser("stage3", help="Stage 3: OCR extraction")
    p3.add_argument("--video-id", "-v", help="Process specific video only")
    p3.set_defaults(func=cmd_stage3)
    
    p35 = subparsers.add_parser("spellcheck", help="Stage 3.5: Spellcheck OCR output")
    p35.add_argument("--video-id", "-v", help="Process specific video only")
    p35.set_defaults(func=cmd_spellcheck)
    
    pbd = subparsers.add_parser("build-dictionary", help="Build custom dictionary from reviewed entries")
    pbd.set_defaults(func=cmd_build_dictionary)
    
    p4 = subparsers.add_parser("review", help="Stage 4: Start review web UI")
    p4.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    p4.add_argument("--port", "-p", type=int, default=5000, help="Port to bind to")
    p4.add_argument("--debug", "-d", action="store_true", help="Enable debug mode")
    p4.set_defaults(func=cmd_stage4)
    
    p5 = subparsers.add_parser("stage5", help="Stage 5: Generate archive")
    p5.set_defaults(func=cmd_stage5)
    
    pc = subparsers.add_parser("calibrate", help="Run subtitle region calibration tool")
    pc.set_defaults(func=cmd_calibrate)
    
    ps = subparsers.add_parser("status", help="Show pipeline status")
    ps.add_argument("--video-id", "-v", help="Show status for specific video")
    ps.set_defaults(func=cmd_status)
    
    pa = subparsers.add_parser("run-all", help="Run full pipeline")
    pa.add_argument("--urls", "-u", help="Path to urls.txt file")
    pa.add_argument("--skip-acquire", action="store_true", help="Skip frame acquisition")
    pa.add_argument("--auto-approve", action="store_true", help="Auto-approve all entries (skip manual review)")
    pa.set_defaults(func=cmd_run_all)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()

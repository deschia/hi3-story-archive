import os
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from utils import (
    load_json, save_json, load_progress, update_progress,
    logger, RAW_DIR, REVIEWED_DIR, FRAMES_DIR, PROGRESS_DIR, METADATA_DIR, BASE_DIR
)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


def get_all_videos():
    videos = []
    for progress_file in PROGRESS_DIR.glob("*.json"):
        progress = load_json(progress_file)
        metadata_file = METADATA_DIR / f"{progress['video_id']}.json"
        metadata = load_json(metadata_file) if metadata_file.exists() else {}
        videos.append({
            "video_id": progress["video_id"],
            "title": metadata.get("title", "Unknown"),
            "chapter": metadata.get("chapter", "Unknown"),
            "status": progress["status"],
            "stages": progress["stages"]
        })
    return videos


def init_reviewed(video_id):
    reviewed_path = REVIEWED_DIR / f"{video_id}.json"
    raw_path = RAW_DIR / f"{video_id}.json"
    
    if reviewed_path.exists():
        reviewed = load_json(reviewed_path)
        if reviewed.get("entries"):
            return reviewed
    
    if not raw_path.exists():
        return None
    
    raw = load_json(raw_path)
    for entry in raw["entries"]:
        entry["reviewed"] = False
        entry["corrected"] = False
    
    save_json(reviewed_path, raw)
    return raw


def update_review_progress(video_id):
    reviewed_path = REVIEWED_DIR / f"{video_id}.json"
    if not reviewed_path.exists():
        return
    
    reviewed = load_json(reviewed_path)
    entries = reviewed["entries"]
    
    total = len(entries)
    reviewed_count = sum(1 for e in entries if e.get("reviewed", False))
    corrected_count = sum(1 for e in entries if e.get("corrected", False))
    
    config = load_json(BASE_DIR / "config.json")
    threshold = config.get("confidence_threshold", 0.80)
    pending_low = sum(1 for e in entries if e["confidence"] < threshold and not e.get("reviewed", False))
    
    status = "complete" if reviewed_count == total else "in_progress"
    
    update_progress(video_id, "review", {
        "status": status,
        "total_entries": total,
        "reviewed": reviewed_count,
        "corrected": corrected_count,
        "pending_low_confidence": pending_low
    })


@app.route("/")
def dashboard():
    videos = get_all_videos()
    return render_template("dashboard.html", videos=videos)


@app.route("/video/<video_id>")
def review_video(video_id):
    reviewed = init_reviewed(video_id)
    if not reviewed:
        return "Video not found or not ready for review", 404
    
    metadata_file = METADATA_DIR / f"{video_id}.json"
    metadata = load_json(metadata_file) if metadata_file.exists() else {}
    
    filter_type = request.args.get("filter", "all")
    
    return render_template(
        "review.html",
        video_id=video_id,
        metadata=metadata,
        total_entries=len(reviewed["entries"]),
        filter_type=filter_type
    )


@app.route("/api/video/<video_id>/entries")
def get_entries(video_id):
    reviewed = init_reviewed(video_id)
    if not reviewed:
        return jsonify({"error": "Video not found"}), 404
    
    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 20, type=int)
    filter_type = request.args.get("filter", "all")
    min_confidence = request.args.get("min_confidence", 0, type=float)
    
    config = load_json(BASE_DIR / "config.json")
    threshold = config.get("confidence_threshold", 0.80)
    
    entries = reviewed["entries"]
    indexed_entries = [{"index": i, **e} for i, e in enumerate(entries)]
    
    indexed_entries = [e for e in indexed_entries if e["confidence"] >= min_confidence]
    
    if filter_type == "pending":
        indexed_entries = [e for e in indexed_entries if not e.get("reviewed", False) and not e.get("deleted", False)]
    elif filter_type == "low":
        indexed_entries = [e for e in indexed_entries if e["confidence"] < threshold and not e.get("deleted", False)]
    elif filter_type == "reviewed":
        indexed_entries = [e for e in indexed_entries if e.get("reviewed", False) and not e.get("deleted", False)]
    elif filter_type == "deleted":
        indexed_entries = [e for e in indexed_entries if e.get("deleted", False)]
    elif filter_type == "all":
        indexed_entries = [e for e in indexed_entries if not e.get("deleted", False)]
    
    total_filtered = len(indexed_entries)
    paginated = indexed_entries[offset:offset + limit]
    
    return jsonify({
        "entries": paginated,
        "total": total_filtered,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total_filtered
    })


@app.route("/video/<video_id>/flush", methods=["POST"])
def flush_actions(video_id):
    data = request.json
    actions = data.get("actions", [])
    
    if not actions:
        return jsonify({"success": True, "applied": 0})
    
    reviewed_path = REVIEWED_DIR / f"{video_id}.json"
    
    if not reviewed_path.exists():
        return jsonify({"success": False, "error": "File not found"}), 404
    
    reviewed = load_json(reviewed_path)
    applied = 0
    
    for action in actions:
        action_type = action.get("type")
        index = action.get("index")
        
        if index < 0 or index >= len(reviewed["entries"]):
            continue
        
        entry = reviewed["entries"][index]
        
        if action_type == "approve":
            entry["reviewed"] = True
            applied += 1
        elif action_type == "save":
            original_speaker = entry.get("speaker")
            original_dialogue = entry.get("dialogue")
            new_speaker = action.get("speaker")
            new_dialogue = action.get("dialogue")
            corrected = (original_speaker != new_speaker) or (original_dialogue != new_dialogue)
            entry["speaker"] = new_speaker
            entry["dialogue"] = new_dialogue
            entry["reviewed"] = True
            entry["corrected"] = corrected or entry.get("corrected", False)
            applied += 1
        elif action_type == "delete":
            entry["deleted"] = True
            entry["reviewed"] = True
            applied += 1
        elif action_type == "restore":
            entry["deleted"] = False
            applied += 1
    
    save_json(reviewed_path, reviewed)
    update_review_progress(video_id)
    
    return jsonify({"success": True, "applied": applied})


@app.route("/frame/<video_id>/<filename>")
def serve_frame(video_id, filename):
    frame_path = FRAMES_DIR / video_id / filename
    if not frame_path.exists():
        return "Frame not found", 404
    return send_file(frame_path)


@app.route("/api/progress")
def api_progress():
    videos = get_all_videos()
    return jsonify(videos)


def run_review_server(host="127.0.0.1", port=5000, debug=False):
    logger.info(f"Starting review server at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    run_review_server(port=port, debug=True)

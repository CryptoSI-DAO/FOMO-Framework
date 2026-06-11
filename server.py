"""
FOMO Radio Server — Flask API
Handles show creation requests from the frontend, triggers the pipeline,
and sends webhooks back when complete.
"""
import os
import json
import uuid
import subprocess
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
PROJECT_DIR = Path("/workspace/fomo-radio/FOMO-Framework")
MEDIA_DIR = PROJECT_DIR / "media"
DATA_JSON_PATH = Path("/workspace/app-archive-repo/data.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "fomo-radio-secret")

# In-memory job store (use Redis in production)
jobs = {}


def load_data_json():
    """Load the app-archive data.json."""
    if DATA_JSON_PATH.exists():
        with open(DATA_JSON_PATH) as f:
            return json.load(f)
    return {"ideas": [], "media": []}


def save_data_json(data):
    """Save the app-archive data.json."""
    with open(DATA_JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)


def git_push_data_json():
    """Push data.json to the app-archive repo."""
    try:
        os.chdir("/workspace/app-archive-repo")
        subprocess.run(["git", "add", "data.json"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Add media entry — {datetime.now(timezone.utc).isoformat()}"],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            check=True, capture_output=True,
            env={**os.environ, "GITHUB_TOKEN": GITHUB_TOKEN}
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Git push failed: {e}")
        return False


def run_pipeline(job_id: str, show_type: str, scope: str, slug: str, date: str):
    """Run the FOMO Radio pipeline in a background thread."""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        # Build command
        cmd = [
            "python3", str(PROJECT_DIR / "run.py"),
            "--scope", scope,
            "--hosts", "data,spock",
            "--no-telegram",  # We handle delivery via webhook
        ]

        if scope == "idea" and slug:
            idea_path = f"/workspace/app-ideas-repo/ideas/{date}/{slug}/idea.md"
            cmd.extend(["--idea", idea_path])
        elif date:
            report_path = f"/workspace/app-ideas-repo/ideas/{date}/daily-summary.md"
            cmd.extend(["--report", report_path])

        # Run the pipeline
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute timeout
            env={**os.environ}
        )

        if result.returncode == 0:
            # Find the generated MP3
            mp3_files = sorted(MEDIA_DIR.glob("*.mp3"), key=os.path.getmtime, reverse=True)
            latest_mp3 = str(mp3_files[0]) if mp3_files else None

            jobs[job_id]["status"] = "completed"
            jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            jobs[job_id]["mp3_path"] = latest_mp3
            jobs[job_id]["stdout"] = result.stdout

            # TODO: Upload to Arweave (by other dev)
            # For now, store local path
            arweave_tx = None  # Will be set by Arweave webhook

            # Update data.json
            data = load_data_json()
            media_entry = {
                "id": f"{show_type}-{date}-{slug or 'daily'}",
                "type": show_type,
                "scope": scope,
                "date": date,
                "slug": slug,
                "arweave_tx": arweave_tx,
                "gateway_url": f"https://arweave.net/{arweave_tx}" if arweave_tx else None,
                "duration": None,
                "hosts": ["Data", "Spock"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending_arweave" if not arweave_tx else "ready"
            }
            data.setdefault("media", []).append(media_entry)
            save_data_json(data)
            git_push_data_json()

            # Send webhook to Vercel
            send_webhook(job_id, "completed", media_entry)

        else:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = result.stderr
            send_webhook(job_id, "failed", {"error": result.stderr})

    except subprocess.TimeoutExpired:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = "Pipeline timed out (5 min limit)"
        send_webhook(job_id, "failed", {"error": "timeout"})
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        send_webhook(job_id, "failed", {"error": str(e)})


def send_webhook(job_id: str, status: str, data: dict):
    """Send webhook to Vercel frontend."""
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if not webhook_url:
        print("No WEBHOOK_URL configured, skipping webhook")
        return

    try:
        requests.post(webhook_url, json={
            "job_id": job_id,
            "status": status,
            "data": data,
            "secret": WEBHOOK_SECRET,
        }, timeout=10)
    except Exception as e:
        print(f"Webhook failed: {e}")


@app.route("/api/create-show", methods=["POST"])
def create_show():
    """Create a new radio show or video."""
    body = request.get_json()
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    show_type = body.get("type", "radio")  # radio or video
    scope = body.get("scope", "daily")     # idea or daily
    slug = body.get("slug", "")            # idea slug (for scope=idea)
    date = body.get("date", "")            # YYYY-MM-DD

    if not date:
        return jsonify({"error": "date is required"}), 400

    if scope == "idea" and not slug:
        return jsonify({"error": "slug is required for idea scope"}), 400

    # Generate job ID
    job_id = f"{show_type}-{date}-{slug or 'daily'}-{uuid.uuid4().hex[:8]}"

    # Store job
    jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "type": show_type,
        "scope": scope,
        "slug": slug,
        "date": date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Start pipeline in background thread
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, show_type, scope, slug, date),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "message": f"{show_type.title()} show creation started for {scope} ({date})",
    }), 202


@app.route("/api/status/<job_id>", methods=["GET"])
def get_status(job_id):
    """Check the status of a show creation job."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/media", methods=["GET"])
def get_media():
    """Get the media registry from data.json."""
    data = load_data_json()
    return jsonify(data.get("media", []))


@app.route("/api/webhook/arweave", methods=["POST"])
def arweave_webhook():
    """Receive webhook from Arweave upload (called by other dev)."""
    body = request.get_json()
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    # Verify secret
    if body.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Invalid secret"}), 403

    job_id = body.get("job_id")
    arweave_tx = body.get("arweave_tx")

    if job_id and arweave_tx:
        # Update job
        if job_id in jobs:
            jobs[job_id]["arweave_tx"] = arweave_tx
            jobs[job_id]["status"] = "ready"

        # Update data.json
        data = load_data_json()
        for entry in data.get("media", []):
            if entry.get("id", "").startswith(job_id.rsplit("-", 1)[0]):
                entry["arweave_tx"] = arweave_tx
                entry["gateway_url"] = f"https://arweave.net/{arweave_tx}"
                entry["status"] = "ready"
        save_data_json()
        git_push_data_json()

        # Notify Vercel
        send_webhook(job_id, "ready", {"arweave_tx": arweave_tx})

    return jsonify({"status": "ok"})


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "fomo-radio"})


if __name__ == "__main__":
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8085, debug=False)

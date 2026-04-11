import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
    after_this_request,
)
from yt_dlp import YoutubeDL

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "replace-this-with-a-secure-random-string"

SUPPORTED_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "vm.tiktok.com",
    "instagram.com",
    "instagr.am",
]
HISTORY_FILE = Path(__file__).parent / "history.json"
MAX_HISTORY_ENTRIES = 80
DOWNLOAD_JOBS = {}


def is_supported_url(url: str) -> bool:
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower().lstrip("www.")
        return any(domain in hostname for domain in SUPPORTED_DOMAINS)
    except Exception:
        return False


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return []


def save_history(history: list) -> None:
    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as handle:
            json.dump(history[:MAX_HISTORY_ENTRIES], handle, indent=2)
    except Exception:
        pass


def add_history_entry(entry: dict) -> None:
    history = load_history()
    history.insert(0, entry)
    save_history(history)


def cleanup_stale_jobs() -> None:
    now = datetime.now(timezone.utc)
    stale_ids = []

    for job_id, job in list(DOWNLOAD_JOBS.items()):
        if job["status"] in ("finished", "error") and job.get("completed_at"):
            completed_at = datetime.fromisoformat(job["completed_at"])
            if (now - completed_at).total_seconds() > 3600:
                shutil.rmtree(job.get("temp_dir", ""), ignore_errors=True)
                stale_ids.append(job_id)

    for job_id in stale_ids:
        DOWNLOAD_JOBS.pop(job_id, None)


def build_job_record(url: str, temp_dir: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "url": url,
        "status": "queued",
        "progress": 0,
        "message": "Waiting to start...",
        "started_at": now,
        "completed_at": None,
        "filename": None,
        "file_path": None,
        "temp_dir": temp_dir,
        "error": None,
    }


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None or shutil.which("ffprobe") is not None


def create_ydl_options(progress_hooks=None):
    base_opts = {
        "outtmpl": None,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "prefer_free_formats": True,
        "nocheckcertificate": True,
    }

    if progress_hooks:
        base_opts["progress_hooks"] = progress_hooks

    if ffmpeg_available():
        base_opts.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )
    else:
        base_opts["format"] = "best[ext=mp4]/best"

    return base_opts


def run_download_job(job_id: str, url: str) -> None:
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        return

    job["status"] = "starting"
    job["message"] = "Preparing the download..."

    def progress_hook(progress_data: dict) -> None:
        if job["status"] == "error":
            return

        if progress_data.get("status") == "downloading":
            total = progress_data.get("total_bytes") or progress_data.get("total_bytes_estimate") or 0
            downloaded = progress_data.get("downloaded_bytes") or 0
            if total > 0:
                percent = round(downloaded / total * 100, 1)
            else:
                percent = None
            job["status"] = "downloading"
            job["progress"] = percent or 0
            job["message"] = progress_data.get("filename") or "Downloading..."
            job["eta"] = progress_data.get("eta")
            job["speed"] = progress_data.get("speed")
        elif progress_data.get("status") == "finished":
            if ffmpeg_available():
                job["message"] = "Finishing and merging streams..."
            else:
                job["message"] = "Finalizing download..."
            job["progress"] = 98

    output_template = os.path.join(job["temp_dir"], "%(title).200s.%(ext)s")
    ydl_opts = create_ydl_options(progress_hooks=[progress_hook])
    ydl_opts["outtmpl"] = output_template

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_files = [f for f in os.listdir(job["temp_dir"]) if f.lower().endswith(".mp4")]
        if not video_files:
            raise FileNotFoundError("No MP4 file was generated for this URL.")

        video_path = os.path.join(job["temp_dir"], video_files[0])
        job["status"] = "finished"
        job["progress"] = 100
        job["message"] = "Ready to download"
        job["file_path"] = video_path
        job["filename"] = os.path.basename(video_path)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()

        add_history_entry(
            {
                "id": job_id,
                "url": url,
                "status": "finished",
                "filename": job["filename"],
                "started_at": job["started_at"],
                "completed_at": job["completed_at"],
            }
        )
    except Exception as exc:
        job["status"] = "error"
        job["message"] = str(exc)
        job["error"] = str(exc)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        add_history_entry(
            {
                "id": job_id,
                "url": url,
                "status": "failed",
                "filename": None,
                "started_at": job["started_at"],
                "completed_at": job["completed_at"],
                "error": job["error"],
            }
        )


def download_video(url: str) -> tuple[str, str]:
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, "%(title).200s.%(ext)s")
    ydl_opts = create_ydl_options()
    ydl_opts["outtmpl"] = output_template

    with YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    video_files = [f for f in os.listdir(temp_dir) if f.lower().endswith(".mp4")]
    if not video_files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise FileNotFoundError("No MP4 file was generated for this URL.")

    video_path = os.path.join(temp_dir, video_files[0])
    return video_path, temp_dir


@app.route("/")
def index():
    cleanup_stale_jobs()
    return render_template("landing.html")


@app.route("/app")
def app_page():
    cleanup_stale_jobs()
    return render_template("app.html")


@app.route("/history")
def history_page():
    cleanup_stale_jobs()
    return render_template("history.html", history=load_history())


@app.route("/api/start-download", methods=["POST"])
def api_start_download():
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or data.get("video_url") or "").strip()
    if not url:
        return jsonify({"error": "Video URL is required."}), 400

    if not is_supported_url(url):
        return jsonify({"error": "Only YouTube, TikTok, and Instagram URLs are supported."}), 400

    temp_dir = tempfile.mkdtemp()
    job = build_job_record(url, temp_dir)
    DOWNLOAD_JOBS[job["id"]] = job
    thread = threading.Thread(target=run_download_job, args=(job["id"], url), daemon=True)
    thread.start()

    return jsonify({"job_id": job["id"]})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    cleanup_stale_jobs()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    return jsonify(
        {
            "id": job["id"],
            "url": job["url"],
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "filename": job.get("filename"),
        }
    )


@app.route("/download-file/<job_id>")
def download_file(job_id: str):
    cleanup_stale_jobs()
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        flash("Download not found.")
        return redirect(url_for("app_page"))

    if job["status"] != "finished" or not job.get("file_path"):
        flash("Download is not ready yet.")
        return redirect(url_for("app_page"))

    filename = os.path.basename(job["file_path"])

    @after_this_request
    def cleanup(response):
        shutil.rmtree(job.get("temp_dir", ""), ignore_errors=True)
        DOWNLOAD_JOBS.pop(job_id, None)
        return response

    return send_file(job["file_path"], as_attachment=True, download_name=filename, mimetype="video/mp4")


@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("video_url", "").strip()
    if not url:
        flash("Paste a YouTube, TikTok or Instagram link.")
        return redirect(url_for("app_page"))

    if not is_supported_url(url):
        flash("Unsupported URL. Please paste a YouTube, TikTok or Instagram link.")
        return redirect(url_for("app_page"))

    temp_dir = None
    try:
        video_path, temp_dir = download_video(url)
        filename = os.path.basename(video_path)
        return send_file(video_path, as_attachment=True, download_name=filename, mimetype="video/mp4")
    except Exception as exc:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        flash(f"Download failed: {exc}")
        return redirect(url_for("app_page"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

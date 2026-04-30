import importlib
import json
import os
import shutil
import subprocess
import sys
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
from werkzeug.utils import secure_filename
from yt_dlp import YoutubeDL

imageio_ffmpeg = None

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "replace-this-with-a-secure-random-string"


@app.after_request
def add_api_cors_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "3600"
    return response

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
COMPRESSION_JOBS = {}


def ensure_imageio_ffmpeg() -> bool:
    global imageio_ffmpeg
    if imageio_ffmpeg is not None:
        return True

    try:
        import imageio_ffmpeg as iio
        imageio_ffmpeg = iio
        return True
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
                capture_output=True,
                text=True,
                check=True,
            )
            importlib.invalidate_caches()
            import imageio_ffmpeg as iio
            imageio_ffmpeg = iio
            return True
        except Exception:
            return False


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

    stale_ids = []
    for job_id, job in list(COMPRESSION_JOBS.items()):
        if job["status"] in ("finished", "error") and job.get("completed_at"):
            completed_at = datetime.fromisoformat(job["completed_at"])
            if (now - completed_at).total_seconds() > 3600:
                shutil.rmtree(job.get("temp_dir", ""), ignore_errors=True)
                stale_ids.append(job_id)

    for job_id in stale_ids:
        COMPRESSION_JOBS.pop(job_id, None)


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


def run_compression_job(job_id: str, input_path: str, output_path: str, options: dict) -> None:
    job = COMPRESSION_JOBS.get(job_id)
    if not job:
        return

    job["status"] = "starting"
    job["message"] = "Preparing compression..."

    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        job["status"] = "error"
        job["message"] = "Compression failed: FFmpeg binary unavailable."
        job["error"] = job["message"]
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        return

    duration = get_video_duration(input_path)
    target_mode = options.get("target_mode", "original")
    pass_log = os.path.join(os.path.dirname(output_path), "ffmpeg_pass")

    try:
        if target_mode in ("percentage", "size"):
            first_pass_cmd = build_compression_command(
                input_path,
                output_path,
                options,
                pass_number=1,
                pass_log=pass_log,
            )
            first_pass_cmd[0] = ffmpeg_exe
            result = subprocess.run(first_pass_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "First pass compression failed.")

            second_pass_cmd = build_compression_command(
                input_path,
                output_path,
                options,
                pass_number=2,
                pass_log=pass_log,
            )
            second_pass_cmd[0] = ffmpeg_exe
            if "-progress" not in second_pass_cmd:
                second_pass_cmd.insert(-1, "-progress")
                second_pass_cmd.insert(-1, "pipe:1")
                second_pass_cmd.insert(-1, "-nostats")

            process_cmd = second_pass_cmd
        else:
            cmd = build_compression_command(input_path, output_path, options)
            cmd[0] = ffmpeg_exe
            if "-progress" not in cmd:
                cmd.insert(-1, "-progress")
                cmd.insert(-1, "pipe:1")
                cmd.insert(-1, "-nostats")
            process_cmd = cmd

        process = subprocess.Popen(
            process_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        job["status"] = "compressing"
        job["message"] = "Compressing video..."

        output_lines = []
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                output_lines.append(line)
                line = line.strip()
                if line.startswith("out_time_ms=") and duration:
                    try:
                        time_ms = int(line.split("=", 1)[1])
                        percent = min(100, round((time_ms / 1000) / duration * 100, 1))
                        job["progress"] = percent
                        job["message"] = f"Compressing video... {percent}%"
                    except ValueError:
                        continue
                elif line.startswith("progress="):
                    status_value = line.split("=", 1)[1]
                    if status_value == "end":
                        job["progress"] = 100
                    elif status_value == "continue" and job["progress"] < 5:
                        job["progress"] = 5
                        job["message"] = "Compressing video..."

        return_code = process.wait()
        stderr = "".join(output_lines).strip()

        if return_code != 0:
            job["status"] = "error"
            job["message"] = stderr or "Compression failed."
            job["error"] = job["message"]
        else:
            job["status"] = "finished"
            job["progress"] = 100
            job["message"] = "Compression complete."
            job["file_path"] = output_path
            job["filename"] = os.path.basename(output_path)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()

        for ext in [".log", "-0.log", "-0.log.mbtree"]:
            try:
                os.remove(pass_log + ext)
            except OSError:
                pass
    except Exception as exc:
        job["status"] = "error"
        job["message"] = str(exc)
        job["error"] = str(exc)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()


def get_ffmpeg_executable() -> str | None:
    ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if ffmpeg_path:
        return ffmpeg_path

    if ensure_imageio_ffmpeg():
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

    bundled = Path(__file__).parent / "static" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)

    return None


def ffmpeg_available() -> bool:
    return bool(get_ffmpeg_executable())


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


ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "mov",
    "mkv",
    "webm",
    "avi",
    "m4v",
    "flv",
    "ogg",
}


def allowed_video_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def parse_positive_int(value: str, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))
    except Exception:
        return default


def get_ffprobe_executable() -> str | None:
    probe_path = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if probe_path:
        return probe_path

    ffmpeg_path = get_ffmpeg_executable()
    if ffmpeg_path:
        probe_candidate = Path(ffmpeg_path).with_name("ffprobe")
        if probe_candidate.exists():
            return str(probe_candidate)
        probe_candidate = Path(ffmpeg_path).with_name("ffprobe.exe")
        if probe_candidate.exists():
            return str(probe_candidate)

    return None


def get_video_bitrate_kbps(file_path: str) -> int | None:
    ffprobe_exe = get_ffprobe_executable()
    if not ffprobe_exe:
        return None

    try:
        result = subprocess.run(
            [ffprobe_exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=bit_rate", "-of", "default=nokey=1:noprint_wrappers=1", file_path],
            capture_output=True,
            text=True,
            check=True,
        )
        bitrate_text = (result.stdout or "").strip()
        if bitrate_text:
            return int(int(bitrate_text) / 1000)
    except Exception:
        pass
    return None


def get_video_duration(file_path: str):
    ffprobe_exe = get_ffprobe_executable()
    if ffprobe_exe:
        try:
            result = subprocess.run(
                [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
                capture_output=True,
                text=True,
                check=True,
            )
            duration_text = (result.stdout or "").strip()
            if duration_text:
                return float(duration_text)
        except Exception:
            pass

    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        return None

    try:
        result = subprocess.run(
            [ffmpeg_exe, "-i", file_path],
            capture_output=True,
            text=True,
        )
        stderr = result.stderr or ""
        for line in stderr.splitlines():
            if "Duration:" in line:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                if len(parts) == 3:
                    hours, minutes, seconds = parts
                    seconds = float(seconds)
                    return int(hours) * 3600 + int(minutes) * 60 + seconds
        return None
    except Exception:
        return None


def build_compression_command(input_path: str, output_path: str, options: dict, pass_number: int = 0, pass_log: str | None = None) -> list[str]:
    cmd = ["ffmpeg", "-y"]

    if options["start_trim"] > 0:
        cmd.extend(["-ss", str(options["start_trim"])])

    cmd.extend(["-i", input_path])

    if options["end_trim"] > 0 and options["end_trim"] > options["start_trim"]:
        cmd.extend(["-to", str(options["end_trim"])])

    filters = []
    resolution_map = {
        "1080p": "1920",
        "720p": "1280",
        "480p": "854",
        "360p": "640",
    }

    if options["resolution"] != "original":
        width = resolution_map.get(options["resolution"])
        if width:
            filters.append(f"scale=w={width}:h=-2")

    if options["aspect_ratio"] != "original":
        filters.append("setsar=1")
        cmd.extend(["-aspect", options["aspect_ratio"]])

    if filters:
        cmd.extend(["-vf", ",".join(filters)])

    target_mode = options.get("target_mode", "original")
    user_bitrate = options.get("target_bitrate_kbps", 0)
    audio_bitrate_kbps = 64
    if target_mode in ("percentage", "size", "bitrate") or user_bitrate > 0:
        duration = get_video_duration(input_path)
        current_size = os.path.getsize(input_path)
        source_bitrate = get_video_bitrate_kbps(input_path)
        target_bitrate = 0
        target_bytes = 0

        if user_bitrate > 0:
            target_bitrate = user_bitrate
        elif target_mode == "percentage":
            reduce_pct = max(1, min(options.get("target_percentage", 0), 95))
            target_bytes = int(current_size * max(0.05, (100 - reduce_pct) / 100))
        elif target_mode == "size":
            requested_bytes = int(options.get("target_size_mb", 0) * 1024 * 1024)
            target_bytes = min(max(requested_bytes, 0), current_size)

        if target_bitrate <= 0 and duration and target_bytes > 0:
            total_bitrate_kbps = max(32.0, (target_bytes * 8) / duration / 1000)
            audio_bitrate_kbps = min(64, max(16, int(round(total_bitrate_kbps * 0.2))))
            target_bitrate = max(32, int(round(total_bitrate_kbps - audio_bitrate_kbps)))
            if target_bitrate < 32:
                target_bitrate = 32
                audio_bitrate_kbps = max(16, int(round(total_bitrate_kbps - target_bitrate)))
                if audio_bitrate_kbps < 16:
                    audio_bitrate_kbps = 16

        if target_bitrate <= 0 and target_bytes > 0:
            target_bitrate = 300
            audio_bitrate_kbps = 64

        if source_bitrate and target_bitrate > source_bitrate and user_bitrate <= 0:
            target_bitrate = source_bitrate

        if target_bitrate > 0:
            cmd.extend([
                "-c:v",
                "libx264",
                "-b:v",
                f"{target_bitrate}k",
                "-preset",
                "medium",
                "-maxrate",
                f"{max(200, int(target_bitrate * 1.5))}k",
                "-bufsize",
                f"{max(400, target_bitrate * 2)}k",
            ])
        elif target_bytes > 0:
            cmd.extend([
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-b:v",
                "300k",
                "-maxrate",
                "450k",
                "-bufsize",
                "900k",
            ])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "35"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "23"])

    if pass_number == 1:
        if pass_log:
            cmd.extend(["-pass", "1", "-passlogfile", pass_log, "-an", "-f", "mp4", os.devnull])
            return cmd
    elif pass_number == 2:
        if pass_log:
            cmd.extend(["-pass", "2", "-passlogfile", pass_log])

    if pass_number == 0:
        cmd.extend(["-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k", "-movflags", "+faststart", output_path])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k", "-movflags", "+faststart", output_path])

    return cmd


def compress_video_file(input_path: str, output_path: str, options: dict) -> None:
    ffmpeg_exe = get_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(
            "FFmpeg is required for compression. The app will try to install the Python "
            "package imageio-ffmpeg automatically, but if that fails you will need internet "
            "access or a local ffmpeg binary."
        )

    target_mode = options.get("target_mode", "original")
    if target_mode in ("percentage", "size"):
        pass_log = os.path.join(os.path.dirname(output_path), "ffmpeg_pass")
        first_pass = build_compression_command(input_path, output_path, options, pass_number=1, pass_log=pass_log)
        second_pass = build_compression_command(input_path, output_path, options, pass_number=2, pass_log=pass_log)

        first_pass[0] = ffmpeg_exe
        second_pass[0] = ffmpeg_exe

        result = subprocess.run(first_pass, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "First pass compression failed.")

        result = subprocess.run(second_pass, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Second pass compression failed.")

        for ext in [".log", "-0.log", "-0.log.mbtree"]:
            try:
                os.remove(pass_log + ext)
            except OSError:
                pass
    else:
        cmd = build_compression_command(input_path, output_path, options)
        cmd[0] = ffmpeg_exe
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Compression failed.")


def get_compression_options(form: dict) -> dict:
    start_trim = parse_positive_int(form.get("start_trim", "0"))
    end_trim = parse_positive_int(form.get("end_trim", "0"))
    if end_trim <= start_trim:
        end_trim = 0

    target_mode = form.get("target_mode", "original")
    target_percentage = parse_positive_int(form.get("target_percentage", "0"))
    target_size_mb = parse_positive_int(form.get("target_size_mb", "0"))
    target_bitrate_kbps = parse_positive_int(form.get("target_bitrate", "0"))

    if target_mode == "original":
        if target_bitrate_kbps > 0:
            target_mode = "bitrate"
        elif target_size_mb > 0:
            target_mode = "size"
        elif target_percentage > 0:
            target_mode = "percentage"

    return {
        "resolution": form.get("resolution", "original"),
        "aspect_ratio": form.get("aspect_ratio", "original"),
        "start_trim": start_trim,
        "end_trim": end_trim,
        "target_mode": target_mode,
        "target_percentage": target_percentage,
        "target_size_mb": target_size_mb,
        "target_bitrate_kbps": target_bitrate_kbps,
    }


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


@app.route("/compress", methods=["GET", "POST"])
def compress_page():
    cleanup_stale_jobs()

    if request.method == "POST":
        video_file = request.files.get("video_file")
        if not video_file or video_file.filename == "":
            flash("Please select a video file to compress.")
            return render_template("compress.html")

        if not allowed_video_file(video_file.filename):
            flash("Unsupported file type. Upload MP4, MOV, MKV, WEBM, AVI, M4V, FLV or OGG.")
            return render_template("compress.html")

        temp_dir = tempfile.mkdtemp()
        filename = secure_filename(video_file.filename)
        input_path = os.path.join(temp_dir, filename)
        video_file.save(input_path)

        output_filename = f"compressed-{Path(filename).stem}.mp4"
        output_path = os.path.join(temp_dir, output_filename)
        options = get_compression_options(request.form)

        try:
            compress_video_file(input_path, output_path, options)

            @after_this_request
            def cleanup(response):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return response

            return send_file(
                output_path,
                as_attachment=True,
                download_name=output_filename,
                mimetype="video/mp4",
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            flash(f"Compression failed: {exc}")

    return render_template("compress.html")


@app.route("/api/start-compression", methods=["POST"])
def api_start_compression():
    video_file = request.files.get("video_file")
    if not video_file or video_file.filename == "":
        return jsonify({"error": "Please select a video file to compress."}), 400

    if not allowed_video_file(video_file.filename):
        return jsonify(
            {"error": "Unsupported file type. Upload MP4, MOV, MKV, WEBM, AVI, M4V, FLV or OGG."},
            400,
        )

    temp_dir = tempfile.mkdtemp()
    filename = secure_filename(video_file.filename)
    input_path = os.path.join(temp_dir, filename)
    video_file.save(input_path)

    output_filename = f"compressed-{Path(filename).stem}.mp4"
    output_path = os.path.join(temp_dir, output_filename)
    options = get_compression_options(request.form)

    job = build_job_record(filename, temp_dir)
    COMPRESSION_JOBS[job["id"]] = job
    thread = threading.Thread(
        target=run_compression_job,
        args=(job["id"], input_path, output_path, options),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job["id"]})


@app.route("/api/compression-status/<job_id>")
def api_compression_status(job_id: str):
    cleanup_stale_jobs()
    job = COMPRESSION_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Compression job not found."}), 404

    return jsonify(
        {
            "id": job["id"],
            "filename": job.get("filename"),
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
        }
    )


@app.route("/download-compressed/<job_id>")
def download_compressed(job_id: str):
    cleanup_stale_jobs()
    job = COMPRESSION_JOBS.get(job_id)
    if not job:
        flash("Compression job not found.")
        return redirect(url_for("compress_page"))

    if job["status"] != "finished" or not job.get("file_path"):
        flash("Compressed file is not ready yet.")
        return redirect(url_for("compress_page"))

    filename = os.path.basename(job["file_path"])

    @after_this_request
    def cleanup(response):
        shutil.rmtree(job.get("temp_dir", ""), ignore_errors=True)
        COMPRESSION_JOBS.pop(job_id, None)
        return response

    return send_file(job["file_path"], as_attachment=True, download_name=filename, mimetype="video/mp4")


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

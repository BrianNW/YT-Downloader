
# YouTube Video Downloader & Compressor (Web & Desktop)

A lightweight Flask web app and desktop tool to download and compress video content from YouTube, TikTok, and Instagram as MP4 files.


## What this app does

- Accepts video URLs from YouTube, TikTok, and Instagram
- Downloads the best available MP4 stream
- Compresses videos to a target size or bitrate
- Provides live progress and status updates while downloading or compressing
- Supports drag-and-drop URL input
- Tracks recent download history on the `/history` page
- Includes a desktop-style launcher and a packaged desktop executable


## Features

- Landing page with tool selection (Downloader, Compressor)
- Dedicated pages for downloading and compressing videos
- Asynchronous download and compression jobs with progress polling
- Download history log stored in `history.json`
- Local desktop launcher script for quick startup
- One-click desktop executable (no Python required for end users)


## Getting Started (Web & Desktop)

### 1. Clone the repository

```powershell
git clone https://github.com/<your-username>/<your-repo>.git
cd yt-downloader
```

### 2. Set up Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
python -m pip install yt_dlp flask pyinstaller
```

### 4. Run the web app

```powershell
python app.py
```
Then open http://127.0.0.1:5000 in your browser.


## Desktop App

### 1. Run as a Python script

```powershell
python desktop.py
```

### 2. Build a standalone Windows executable

Make sure all your latest code and templates are present. Then run:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean --onefile --add-data "templates;templates" --add-data "static;static" --hidden-import flask --hidden-import yt_dlp desktop.py
```

This will create `dist/desktop.exe`. To run it:

```powershell
.\dist\desktop.exe
```

Or use the provided batch file for persistent error viewing:

```powershell
run_desktop.bat
```

### 3. Troubleshooting

- If you see `ModuleNotFoundError` for `yt_dlp` or `flask`, ensure both are installed and add `import yt_dlp` to `desktop.py` if needed.
- All logs and errors are written to `desktop_app.log` in the project folder.
- Always rebuild after updating code or templates.


## Publish to GitHub

1. Initialize a Git repository if you haven't already:

   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. Create a new repository on GitHub.
3. Add your GitHub remote and push:

   ```powershell
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git branch -M main
   git push -u origin main
   ```

## Notes

- If `ffmpeg` is installed, the app can merge separate video/audio streams into a single MP4.
- Without `ffmpeg`, the app falls back to direct MP4 downloads when available.
- Temporary download files are cleaned up after the file is delivered.
- Download history is saved in `history.json`.
- If `ffmpeg` is installed, the app can merge separate video and audio streams into a single MP4. Without `ffmpeg`, it will still download direct MP4 streams when available.

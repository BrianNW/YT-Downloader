# Video Downloader Web App

A lightweight Flask web app that downloads video content from YouTube, TikTok, and Instagram as MP4 files.

## What this app does

- Accepts video URLs from YouTube, TikTok, and Instagram
- Downloads the best available MP4 stream
- Provides live progress and status updates while downloading
- Supports drag-and-drop URL input
- Tracks recent download history on the `/history` page
- Includes a desktop-style launcher via `desktop.py`

## Features

- Landing page with product overview
- Downloader interface with URL input and drag-and-drop support
- Asynchronous download jobs with progress polling
- Download history log stored in `history.json`
- Local desktop launcher script for quick startup

## Deploy locally

1. Open PowerShell in the project folder:

   ```powershell
   cd "f:\MY FILES\Projects\yt-downloader"
   ```

2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install Python dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the Flask app:

   ```powershell
   python app.py
   ```

5. Open the app in a browser:

   ```text
   http://127.0.0.1:5000
   ```

## Optional desktop launch

To start the app and open it automatically in the browser:

```powershell
python desktop.py
```

## Packaging as a desktop executable

Install PyInstaller and create a single-file executable:

```powershell
python -m pip install pyinstaller
python -m pyinstaller --onefile desktop.py
```

Then run:

```powershell
.\dist\desktop.exe
```

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

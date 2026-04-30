const themeToggle = document.getElementById("theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const storedTheme = localStorage.getItem("yt-downloader-theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const initialTheme = storedTheme || (prefersDark ? "dark" : "light");
const homeDownloadForm = document.getElementById("home-download-form");
const homeVideoUrlInput = document.getElementById("home-video-url");
const homeDownloadStatus = document.getElementById("home-download-status");
const homeDownloadMessage = document.getElementById("home-download-message");
const homeDownloadProgress = document.getElementById("home-download-progress");
const configuredApiBase = (window.CLIP_API_BASE || "").trim();
const configuredDownloadMode = (window.CLIP_DOWNLOAD_MODE || "direct").trim().toLowerCase();
const localhostApiBase = "http://127.0.0.1:5000";
const apiBase = configuredApiBase || (window.location.protocol === "file:" ? localhostApiBase : "");
const supportedDomains = [
  "youtube.com",
  "youtu.be",
  "tiktok.com",
  "vm.tiktok.com",
  "instagram.com",
  "instagr.am",
];
let activeDownloadJobId = null;

document.documentElement.setAttribute("data-theme", initialTheme);
themeIcon.textContent = initialTheme === "dark" ? "\u2600" : "\u263D";

themeToggle.addEventListener("click", () => {
  const currentTheme = document.documentElement.getAttribute("data-theme");
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", nextTheme);
  localStorage.setItem("yt-downloader-theme", nextTheme);
  themeIcon.textContent = nextTheme === "dark" ? "\u2600" : "\u263D";
});

function isSupportedUrl(url) {
  try {
    const hostname = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
    return supportedDomains.some((domain) => hostname.includes(domain));
  } catch {
    return false;
  }
}

function updateHomeDownloadStatus(message, percent = 0, isError = false) {
  if (!homeDownloadStatus) {
    return;
  }

  homeDownloadStatus.classList.toggle("is-error", isError);
  homeDownloadMessage.textContent = message;
  homeDownloadProgress.style.width = `${Math.min(100, Math.max(0, percent))}%`;
}

function getApiUrl(path) {
  if (!apiBase) {
    return null;
  }
  return `${apiBase}${path}`;
}

function readFilenameFromDisposition(headerValue) {
  if (!headerValue) {
    return "video.mp4";
  }

  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const simpleMatch = headerValue.match(/filename="?([^";]+)"?/i);
  if (simpleMatch && simpleMatch[1]) {
    return simpleMatch[1];
  }

  return "video.mp4";
}

async function startDirectDownload(url) {
  const directUrl = getApiUrl("/api/download-direct");
  if (!directUrl) {
    updateHomeDownloadStatus(
      "Set window.CLIP_API_BASE in docs/assets/config.js to your hosted backend URL.",
      0,
      true,
    );
    return;
  }

  updateHomeDownloadStatus("Downloading video. This can take up to a minute...", 35, false);

  try {
    const response = await fetch(directUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!response.ok) {
      let errorMessage = "Unable to start the download.";
      try {
        const payload = await response.json();
        errorMessage = payload.error || errorMessage;
      } catch {
        errorMessage = `Download failed (${response.status}).`;
      }
      updateHomeDownloadStatus(errorMessage, 0, true);
      return;
    }

    const blob = await response.blob();
    const filename = readFilenameFromDisposition(response.headers.get("content-disposition"));
    const downloadUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = downloadUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(downloadUrl);

    updateHomeDownloadStatus("Download complete.", 100, false);
  } catch {
    updateHomeDownloadStatus(
      "Unable to reach downloader backend. Verify CLIP_API_BASE or backend uptime.",
      0,
      true,
    );
  }
}

async function pollHomeDownloadStatus() {
  if (!activeDownloadJobId) {
    return;
  }

  const statusUrl = getApiUrl(`/api/status/${activeDownloadJobId}`);
  if (!statusUrl) {
    updateHomeDownloadStatus(
      "Downloader backend is not configured yet. Set window.CLIP_API_BASE in docs/assets/config.js.",
      0,
      true,
    );
    activeDownloadJobId = null;
    return;
  }

  try {
    const response = await fetch(statusUrl);
    const payload = await response.json();

    if (!response.ok) {
      updateHomeDownloadStatus(payload.error || "Status lookup failed.", 0, true);
      activeDownloadJobId = null;
      return;
    }

    updateHomeDownloadStatus(payload.message || "Processing...", payload.progress || 0, payload.status === "error");

    if (payload.status === "finished") {
      updateHomeDownloadStatus("Download complete. Starting file download...", 100, false);
      window.location.href = getApiUrl(`/download-file/${activeDownloadJobId}`);
      activeDownloadJobId = null;
      return;
    }

    if (payload.status === "error") {
      activeDownloadJobId = null;
      return;
    }

    window.setTimeout(pollHomeDownloadStatus, 1200);
  } catch {
    updateHomeDownloadStatus(
      "Downloader service is unreachable. Check your backend URL or start the local app for development.",
      0,
      true,
    );
    activeDownloadJobId = null;
  }
}

if (homeDownloadForm) {
  homeDownloadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const url = homeVideoUrlInput.value.trim();
    if (!url) {
      updateHomeDownloadStatus("Paste a video URL first.", 0, true);
      return;
    }

    if (!isSupportedUrl(url)) {
      updateHomeDownloadStatus("Only YouTube, TikTok, and Instagram links are supported.", 0, true);
      return;
    }

    if (configuredDownloadMode === "direct") {
      await startDirectDownload(url);
      return;
    }

    const startUrl = getApiUrl("/api/start-download");
    if (!startUrl) {
      updateHomeDownloadStatus(
        "Set window.CLIP_API_BASE in docs/assets/config.js to your hosted backend URL.",
        0,
        true,
      );
      return;
    }

    updateHomeDownloadStatus("Contacting downloader backend...", 5, false);

    try {
      const response = await fetch(startUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const payload = await response.json();

      if (!response.ok) {
        updateHomeDownloadStatus(payload.error || "Unable to start the download.", 0, true);
        return;
      }

      activeDownloadJobId = payload.job_id;
      updateHomeDownloadStatus("Download started. Tracking progress...", 10, false);
      pollHomeDownloadStatus();
    } catch {
      updateHomeDownloadStatus(
        "Unable to reach downloader backend. Verify CLIP_API_BASE or backend uptime.",
        0,
        true,
      );
    }
  });
}
const themeToggle = document.getElementById("theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const storedTheme = localStorage.getItem("yt-downloader-theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const initialTheme = storedTheme || (prefersDark ? "dark" : "light");

document.documentElement.setAttribute("data-theme", initialTheme);
themeIcon.textContent = initialTheme === "dark" ? "\u2600" : "\u263D";

themeToggle.addEventListener("click", () => {
  const currentTheme = document.documentElement.getAttribute("data-theme");
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", nextTheme);
  localStorage.setItem("yt-downloader-theme", nextTheme);
  themeIcon.textContent = nextTheme === "dark" ? "\u2600" : "\u263D";
});
(() => {
  const storageKey = "muralium-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  let preference;
  let toggle;

  try {
    preference = localStorage.getItem(storageKey);
  } catch {
    // Follow the system theme if storage is unavailable.
  }

  function applyTheme() {
    const dark = preference === "dark" || (preference !== "light" && systemTheme.matches);
    root.dataset.theme = dark ? "dark" : "light";
    themeColor.content = dark ? "#141813" : "#f6f6ef";
    toggle?.setAttribute("aria-pressed", String(dark));
  }

  applyTheme();
  systemTheme.addEventListener("change", applyTheme);
  window.addEventListener("storage", (event) => {
    if (event.key === storageKey || event.key === null) {
      preference = event.newValue;
      applyTheme();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    toggle = document.querySelector(".theme-toggle");
    applyTheme();
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      preference = root.dataset.theme === "dark" ? "light" : "dark";
      applyTheme();
      try {
        localStorage.setItem(storageKey, preference);
      } catch {
        // The theme can still be switched on the current page.
      }
    });
  });
})();

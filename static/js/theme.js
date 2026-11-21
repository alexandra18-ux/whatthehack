(() => {
  const storageKey = "muralium-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  let preference;
  let picker;

  try {
    preference = localStorage.getItem(storageKey);
  } catch {
    // Follow the system theme if storage is unavailable.
  }

  function applyTheme() {
    const mode = preference === "dark" || preference === "light" ? preference : "system";
    const dark = mode === "dark" || (mode === "system" && systemTheme.matches);
    root.dataset.theme = dark ? "dark" : "light";
    themeColor.content = dark ? "#141813" : "#f6f6ef";

    if (picker) {
      const selected = picker.querySelector(`input[value="${mode}"]`);
      selected.checked = true;
      const toggle = picker.querySelector("summary");
      toggle.querySelector(".theme-icon").className = `theme-icon theme-icon-${mode}`;
      const label = selected.parentElement.textContent.replace("✓", "").trim();
      toggle.setAttribute("aria-label", `Выбрать тему. ${label}`);
    }
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
    picker = document.querySelector(".theme-picker");
    const toggle = picker.querySelector("summary");
    applyTheme();
    picker.hidden = false;

    picker.addEventListener("change", (event) => {
      preference = event.target.value;
      applyTheme();
      try {
        localStorage.setItem(storageKey, preference);
      } catch {
        // The theme can still be switched on the current page.
      }
    });

    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) picker.open = false;
    });

    picker.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && picker.open) {
        picker.open = false;
        toggle.focus();
      }
    });
  });
})();

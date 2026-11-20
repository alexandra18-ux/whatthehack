const restrictionForm = document.querySelector("[data-restriction-form]");

if (restrictionForm) {
  const endDate = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "long", timeStyle: "short", timeZone: restrictionForm.dataset.timeZone,
  });

  for (const row of restrictionForm.querySelectorAll("[data-restriction-row]")) {
    const select = row.querySelector("select");
    const saved = row.querySelector("[data-restriction-saved]");
    const preview = row.querySelector("[data-restriction-preview]");

    function updatePreview() {
      if (saved) saved.hidden = select.value !== "keep";
      const hours = Number(select.value);
      preview.textContent = hours > 0
        ? "До " + endDate.format(Date.now() + hours * 3600000)
        : "";
    }

    select.addEventListener("change", updatePreview);
    updatePreview();
  }
}

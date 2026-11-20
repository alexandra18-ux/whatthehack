document.addEventListener("DOMContentLoaded", () => {
  const status = document.getElementById("id_status");
  if (!status) return;

  const noteFields = [
    ["rejected", document.getElementById("id_rejection_reason")],
    ["revision", document.getElementById("id_revision_notes")],
  ];

  function syncNotes() {
    for (const [decision, field] of noteFields) {
      const row = field?.closest("[data-moderation-note], .form-row");
      if (!row) continue;
      const active = status.value === decision;
      row.hidden = !active;
      field.disabled = !active;
      field.required = active;
    }
  }

  status.addEventListener("change", syncNotes);
  window.addEventListener("pageshow", syncNotes);
  syncNotes();
});

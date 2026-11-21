(() => {
    const panel = document.querySelector("[data-graffiti-photo]");
    const input = panel.querySelector('input[type="file"]');
    const preview = panel.querySelector("[data-photo-preview]");
    const currentPhoto = panel.querySelector("[data-current-photo]");
    const error = panel.querySelector("[data-photo-preview-error]");
    let previewUrl;

    function updatePreview() {
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = null;
        preview.hidden = true;
        preview.removeAttribute("src");
        error.hidden = true;
        if (currentPhoto) currentPhoto.hidden = false;

        const file = input.files[0];
        if (!file) return;

        previewUrl = URL.createObjectURL(file);
        preview.src = previewUrl;
    }

    preview.addEventListener("load", () => {
        if (!previewUrl) return;
        preview.hidden = false;
        if (currentPhoto) currentPhoto.hidden = true;
    });
    preview.addEventListener("error", () => {
        if (previewUrl) error.hidden = false;
    });
    input.addEventListener("change", updatePreview);
    updatePreview();
})();

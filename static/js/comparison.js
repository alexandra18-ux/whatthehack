for (const comparison of document.querySelectorAll("[data-comparison]")) {
    const buttons = [...comparison.querySelectorAll("[data-show]")];
    const images = comparison.querySelectorAll("[data-image]");

    for (const button of buttons) {
        button.addEventListener("click", () => {
            for (const option of buttons) {
                option.setAttribute("aria-pressed", String(option === button));
            }
            for (const image of images) {
                image.hidden = image.dataset.image !== button.dataset.show;
            }
        });
    }
}

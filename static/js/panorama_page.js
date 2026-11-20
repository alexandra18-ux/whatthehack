(() => {
    const viewer = document.querySelector("[data-panorama-frame]");
    if (!viewer) return;

    const image = viewer.querySelector("#public-panorama-image");
    const editor = viewer.querySelector("#panorama-editor-link");
    const status = viewer.querySelector("#panorama-frame-status");
    const initial = JSON.parse(viewer.querySelector("#starting-camera").textContent);
    const span = Number(viewer.dataset.span);
    const frameUrl = new URL(image.src);
    const editorUrl = new URL(editor.href);
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    const directions = new Map([
        ["left", [-15, 0]], ["right", [15, 0]],
        ["up", [0, 8]], ["down", [0, -8]],
        ["in", [0, 0, 1 / 1.2]], ["out", [0, 0, 1.2]],
    ]);
    let displayed = initial;
    let requested = initial;
    let pending = false;
    let drag;

    function failed() {
        status.textContent = "Ракурс не загрузился. Попробуйте ещё раз или откройте прогулку в Яндекс Картах.";
    }

    image.addEventListener("error", failed);
    if (image.complete && !image.naturalWidth) failed();

    async function showLatest() {
        if (pending) return;
        while (requested !== displayed) {
            const camera = requested;
            const query = JSON.stringify(camera);
            frameUrl.searchParams.set("camera", query);
            const next = new Image();
            next.src = frameUrl.href;
            pending = true;
            status.textContent = "Загружаем ракурс…";
            try {
                await next.decode();
                image.src = next.src;
                displayed = camera;
                editorUrl.searchParams.set("camera", query);
                editor.href = editorUrl.href;
                status.textContent = "";
            } catch {
                failed();
                if (requested === camera) requested = displayed;
            } finally {
                pending = false;
            }
        }
    }

    function adjust(turn, tilt, zoom = 1) {
        const [yaw, pitch, previousFov] = requested;
        const fov = clamp(previousFov * zoom, 8, Math.min(80, span * .92));
        const limit = Math.min(85, (span - fov) / 2);
        requested = [
            ((yaw + turn + 180) % 360 + 360) % 360 - 180,
            clamp(pitch + tilt, -limit, limit),
            fov,
        ].map((angle) => Number(angle.toFixed(2)));
        showLatest();
    }

    viewer.querySelectorAll("[data-camera]").forEach((button) => {
        button.addEventListener("click", () => {
            const direction = button.dataset.camera;
            if (direction === "reset") {
                requested = [...initial];
                showLatest();
            } else {
                adjust(...directions.get(direction));
            }
        });
    });
    const keys = new Map([
        ["ArrowLeft", "left"], ["ArrowRight", "right"], ["ArrowUp", "up"], ["ArrowDown", "down"],
        ["+", "in"], ["-", "out"],
    ]);
    image.addEventListener("keydown", (event) => {
        if (event.repeat || !keys.has(event.key)) return;
        event.preventDefault();
        adjust(...directions.get(keys.get(event.key)));
    });
    image.addEventListener("dragstart", (event) => event.preventDefault());
    image.addEventListener("pointerdown", (event) => {
        if (!event.isPrimary || event.button !== 0) return;
        drag = event;
        image.setPointerCapture(event.pointerId);
    });
    image.addEventListener("pointerup", (event) => {
        if (drag?.pointerId !== event.pointerId) return;
        const unit = displayed[2] / image.clientHeight;
        const x = drag.clientX - event.clientX;
        const y = event.clientY - drag.clientY;
        if (Math.hypot(x, y) > 4) adjust(x * unit, y * unit);
    });
    image.addEventListener("lostpointercapture", () => { drag = null; });
})();

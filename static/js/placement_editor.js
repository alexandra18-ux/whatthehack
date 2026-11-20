const form = document.querySelector("#placement-editor");
const stage = document.querySelector("#facade-stage");
const handles = [...stage.querySelectorAll("[data-corner]")];
const canvas = document.querySelector("#editor-canvas");
const ctx = canvas.getContext("2d");
const placeholder = document.querySelector("#canvas-empty");
const previewImage = document.querySelector("#preview-image");
const designImage = document.querySelector("#design-preview");
const message = document.querySelector("#editor-message");
const help = document.querySelector("#editor-help");
const resetButton = document.querySelector("#reset-corners");
const previewButton = document.querySelector("#render-preview");
const submitButton = document.querySelector("#submit-placement");
const beforeButton = document.querySelector("#show-before");
const afterButton = document.querySelector("#show-after");
const inputs = form.elements;

let points = [];
let photo = null;
let photoVersion = 0;
let designVersion = 0;
let renderedUrl = "";
let designUrl = "";
let hasDesign = false;
let drag = null;
let pending = null;
let mode = "before";
let outline = null;

function orderedOutline(corners) {
    if (corners.length !== 4) return null;
    const cx = corners.reduce((sum, p) => sum + p.x, 0) / 4;
    const cy = corners.reduce((sum, p) => sum + p.y, 0) / 4;
    const angle = (p) => Math.atan2(p.y - cy, p.x - cx);
    const ordered = [...corners].sort((a, b) => angle(a) - angle(b));
    const turns = ordered.map((a, i) => {
        const b = ordered[(i + 1) % 4];
        const c = ordered[(i + 2) % 4];
        return (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    });
    if (turns.some((turn) => turn <= 0)) return null;
    return ordered;
}

function setMessage(text, error = false) {
    message.textContent = text;
    message.classList.toggle("is-error", error);
}

function refreshControls() {
    const canPreview = Boolean(photo && hasDesign && outline && !pending);
    previewButton.disabled = !canPreview;
    submitButton.disabled = !canPreview || !renderedUrl;
    afterButton.disabled = !renderedUrl;
    resetButton.disabled = points.length === 0;
    stage.hidden = !photo || mode === "after";
    previewImage.hidden = mode !== "after";
    placeholder.hidden = Boolean(photo);
    beforeButton.setAttribute("aria-pressed", String(mode === "before"));
    afterButton.setAttribute("aria-pressed", String(mode === "after"));

    if (mode === "after") {
        help.textContent = "Нажмите «До», чтобы скорректировать углы.";
    } else if (points.length === 4 && !outline) {
        help.textContent = "Переместите точки на четыре внешних угла стены. Три точки не должны лежать на одной линии.";
    } else if (outline) {
        help.textContent = "Перетащите угол или выберите его клавишей Tab. Стрелки сдвигают точку на пиксель, Shift со стрелкой — на 10.";
    } else {
        help.textContent = photo
            ? "Отметьте угол " + (points.length + 1) + " из 4. Порядок произвольный."
            : "Укажите четыре угла стены в любом порядке.";
    }
}

function draw() {
    if (!photo || stage.hidden) return;
    const width = canvas.clientWidth;
    if (!width) return;
    const ratio = window.devicePixelRatio || 1;
    const height = width * photo.naturalHeight / photo.naturalWidth;
    const pixelWidth = Math.max(1, Math.round(width * ratio));
    const pixelHeight = Math.max(1, Math.round(height * ratio));
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.drawImage(photo, 0, 0, width, height);

    handles.forEach((handle, index) => {
        const point = points[index];
        handle.hidden = !point;
        if (point) {
            handle.style.setProperty("--corner-x", point.x * 100 + "%");
            handle.style.setProperty("--corner-y", point.y * 100 + "%");
        }
    });
    if (points.length === 0) return;
    ctx.beginPath();
    if (points.length === 4 && !outline) return;
    (outline || points).forEach((point, index) => {
        const x = point.x * width;
        const y = point.y * height;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    if (points.length === 4) {
        ctx.closePath();
        ctx.fillStyle = "rgba(211, 245, 105, .23)";
        ctx.fill();
    }
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#ddff79";
    ctx.stroke();
}

function show(next) {
    mode = next;
    refreshControls();
    draw();
}

function invalidatePreview() {
    if (pending) {
        pending.abort();
        pending = null;
    }
    if (renderedUrl) URL.revokeObjectURL(renderedUrl);
    renderedUrl = "";
    previewImage.removeAttribute("src");
    setMessage("");
    show("before");
}

function syncPoints() {
    outline = orderedOutline(points);
    inputs.corners.value = JSON.stringify(outline || points);
    invalidatePreview();
}

function pointerPosition(event) {
    const bounds = canvas.getBoundingClientRect();
    return {
        x: (event.clientX - bounds.left) / bounds.width,
        y: (event.clientY - bounds.top) / bounds.height,
    };
}

function clampPoint({ x, y }) {
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) };
}

function movePoint(index, position) {
    const point = clampPoint(position);
    if (point.x === points[index].x && point.y === points[index].y) return;
    points[index] = point;
    syncPoints();
}

function finishDrag() {
    if (!drag) return;
    handles[drag.index].classList.remove("is-dragged");
    stage.classList.remove("is-dragging");
    const { pointerId } = drag;
    drag = null;
    if (stage.hasPointerCapture(pointerId)) stage.releasePointerCapture(pointerId);
}

stage.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0 || drag) return;
    const origin = pointerPosition(event);
    const handle = event.target.closest("[data-corner]");
    const index = handle ? Number(handle.dataset.corner) : points.length;
    if (!handle) {
        if (index === handles.length) return;
        points.push(clampPoint(origin));
        syncPoints();
    }
    drag = { index, origin, start: points[index], pointerId: event.pointerId };
    handles[index].classList.add("is-dragged");
    stage.classList.add("is-dragging");
    stage.setPointerCapture(event.pointerId);
});
stage.addEventListener("pointermove", (event) => {
    if (event.pointerId !== drag?.pointerId) return;
    const current = pointerPosition(event);
    movePoint(drag.index, {
        x: drag.start.x + current.x - drag.origin.x,
        y: drag.start.y + current.y - drag.origin.y,
    });
});
for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    stage.addEventListener(type, (event) => {
        if (event.pointerId === drag?.pointerId) finishDrag();
    });
}

const arrowDirections = new Map([
    ["ArrowLeft", [-1, 0]], ["ArrowRight", [1, 0]], ["ArrowUp", [0, -1]], ["ArrowDown", [0, 1]],
]);
stage.addEventListener("keydown", (event) => {
    const handle = event.target.closest("[data-corner]");
    const direction = arrowDirections.get(event.key);
    if (!handle || !direction || drag) return;
    event.preventDefault();
    const index = Number(handle.dataset.corner);
    const [horizontal, vertical] = direction;
    const step = event.shiftKey ? 10 : 1;
    movePoint(index, {
        x: points[index].x + horizontal * step / Math.max(1, photo.naturalWidth - 1),
        y: points[index].y + vertical * step / Math.max(1, photo.naturalHeight - 1),
    });
});

window.addEventListener("resize", draw);
resetButton.addEventListener("click", () => {
    finishDrag();
    points = [];
    syncPoints();
});
beforeButton.addEventListener("click", () => show("before"));
afterButton.addEventListener("click", () => show("after"));

async function getCatalog(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Не удалось загрузить каталог.");
    return new Map((await response.json()).items.map((item) => [String(item.id), item.url]));
}

async function editorCatalog(url, currentId, currentUrl) {
    const catalog = await getCatalog(url).catch(() => new Map());
    if (currentId && currentUrl) catalog.set(currentId, currentUrl);
    return catalog;
}

const facadeCatalog = editorCatalog(form.dataset.facades, form.dataset.currentFacade, form.dataset.currentFacadeUrl);
const designCatalog = editorCatalog(form.dataset.designs, form.dataset.currentDesign, form.dataset.currentDesignUrl);

async function choosePhoto(restorePoints = false) {
    finishDrag();
    const version = ++photoVersion;
    const file = inputs.facade_file.files[0];
    const selection = inputs.facade.value;
    photo = null;
    if (!restorePoints) {
        points = [];
        outline = null;
    }
    invalidatePreview();

    const panorama = inputs.panorama.value;
    const panoramaOption = panorama && document.querySelector(`#panorama-source option[value="${CSS.escape(panorama)}"]`);
    let panoramaUrl;
    if (panoramaOption?.dataset.frame && inputs.panorama_camera.value) {
        panoramaUrl = new URL(panoramaOption.dataset.frame, location.href);
        panoramaUrl.searchParams.set("camera", inputs.panorama_camera.value);
    }
    const url = panoramaUrl || (file ? URL.createObjectURL(file) : (await facadeCatalog).get(selection));
    if (!url) {
        if (version === photoVersion && (selection || panorama)) setMessage("Не удалось открыть выбранный фасад.", true);
        return;
    }
    const image = new Image();
    image.src = url;
    try {
        await image.decode();
        if (version !== photoVersion) return;
        photo = image;
        canvas.style.aspectRatio = image.naturalWidth + " / " + image.naturalHeight;
        syncPoints();
    } catch {
        if (version === photoVersion) setMessage("Не удалось открыть фотографию.", true);
    } finally {
        if (file && !panoramaUrl) URL.revokeObjectURL(url);
    }
}

async function chooseDesign() {
    const version = ++designVersion;
    const file = inputs.mural_file.files[0];
    const selection = inputs.design.value;
    hasDesign = false;
    designImage.hidden = true;
    designImage.removeAttribute("src");
    if (designUrl) URL.revokeObjectURL(designUrl);
    designUrl = "";
    invalidatePreview();

    const url = file ? URL.createObjectURL(file) : (await designCatalog).get(selection);
    if (version !== designVersion) {
        if (file) URL.revokeObjectURL(url);
        return;
    }
    if (!url) {
        if (selection) setMessage("Не удалось загрузить эскиз из каталога.", true);
        return;
    }

    if (file) designUrl = url;
    designImage.src = url;
    try {
        await designImage.decode();
        if (version !== designVersion) return;
        designImage.hidden = false;
        hasDesign = true;
        refreshControls();
    } catch {
        if (version === designVersion) setMessage("Не удалось открыть эскиз.", true);
    }
}

const panoramaChosen = document.querySelector("#panorama-chosen");

function clearPanorama() {
    inputs.panorama.value = "";
    inputs.panorama_camera.value = "";
    panoramaChosen.hidden = true;
}

form.addEventListener("panorama:chosen", (event) => {
    clearPanorama();
    inputs.facade.value = "";
    inputs.facade_file.value = "";
    const { id, camera, file, title } = event.detail;
    if (file) {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        inputs.facade_file.files = transfer.files;
    } else {
        inputs.panorama.value = id;
        inputs.panorama_camera.value = JSON.stringify(camera);
    }
    panoramaChosen.textContent = file ? "Кадр из вашей панорамы" : title;
    panoramaChosen.hidden = false;
    choosePhoto().then(() => {
        if (!stage.hidden) {
            stage.scrollIntoView({ block: "nearest" });
            stage.focus({ preventScroll: true });
        }
    });
});

inputs.facade.addEventListener("change", () => {
    clearPanorama();
    inputs.facade_file.value = "";
    choosePhoto();
});
inputs.facade_file.addEventListener("change", () => {
    if (inputs.facade_file.files.length) {
        clearPanorama();
        inputs.facade.value = "";
    }
    choosePhoto();
});
inputs.design.addEventListener("change", () => {
    inputs.mural_file.value = "";
    chooseDesign();
});
inputs.mural_file.addEventListener("change", () => {
    if (inputs.mural_file.files.length) inputs.design.value = "";
    chooseDesign();
});

previewButton.addEventListener("click", async () => {
    invalidatePreview();
    const controller = new AbortController();
    pending = controller;
    refreshControls();
    setMessage("Подгоняем мурал к фасаду…");

    try {
        const data = new FormData(form);
        data.delete("title");
        data.delete("description");
        const response = await fetch(form.dataset.preview, {
            method: "POST",
            body: data,
            signal: controller.signal,
        });
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            const errors = Object.values(body.errors || {}).flat().join(" ");
            throw new Error(body.error || errors || "Не удалось подготовить предпросмотр.");
        }
        const blob = await response.blob();
        if (pending !== controller) return;

        renderedUrl = URL.createObjectURL(blob);
        previewImage.src = renderedUrl;
        show("after");
        setMessage("Предпросмотр готов.");
    } catch (error) {
        if (pending === controller) {
            setMessage(error.message || "Не удалось подготовить предпросмотр.", true);
        }
    } finally {
        if (pending === controller) {
            pending = null;
            refreshControls();
        }
    }
});

form.addEventListener("submit", (event) => {
    if (submitButton.disabled) {
        event.preventDefault();
        return;
    }
    submitButton.disabled = true;
    setMessage("Отправляем заявку…");
});

if (!inputs.facade.value && !inputs.panorama.value && !form.querySelector(".errorlist") && inputs.facade.options.length > 1) {
    inputs.facade.selectedIndex = 1;
}
if (!inputs.design.value && !form.querySelector(".errorlist") && inputs.design.options.length > 1) {
    inputs.design.selectedIndex = 1;
}
try {
    const saved = JSON.parse(inputs.corners.value);
    if (Array.isArray(saved) && saved.length === 4 && saved.every((point) =>
        point && Number.isFinite(point.x) && Number.isFinite(point.y) &&
        point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1)) {
        points = saved;
    }
} catch {
    // An empty field is expected on the first visit.
}
choosePhoto(true);
chooseDesign();

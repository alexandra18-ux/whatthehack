const form = document.querySelector("#placement-editor");
const stage = document.querySelector("#facade-stage");
const handles = [...stage.querySelectorAll("[data-corner]")];
const canvas = document.querySelector("#editor-canvas");
const ctx = canvas.getContext("2d");
const placeholder = document.querySelector("#canvas-empty");
const sketchOverlay = document.querySelector("#editor-sketch-overlay");
const sketchOutline = document.querySelector("#editor-sketch-outline");
const outlineStrokes = sketchOutline.querySelectorAll("polygon");
const designImage = document.querySelector("#design-preview");
const message = document.querySelector("#editor-message");
const submitButton = document.querySelector("#submit-placement");
const opacity = document.querySelector("#mural-opacity");
const opacityValue = document.querySelector("#mural-opacity-value");
const inputs = form.elements;

let points = [];
let photo = null;
let photoVersion = 0;
let designVersion = 0;
let designUrl = "";
let hasDesign = false;
let drag = null;
let outline = null;

function isConvex(corners) {
    return corners.every((a, i) => {
        const b = corners[(i + 1) % 4];
        const c = corners[(i + 2) % 4];
        return (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x) > 0;
    });
}

function orderedOutline(corners) {
    if (corners.length !== 4) return null;
    const cx = corners.reduce((sum, p) => sum + p.x, 0) / 4;
    const cy = corners.reduce((sum, p) => sum + p.y, 0) / 4;
    const angle = (p) => Math.atan2(p.y - cy, p.x - cx);
    const ordered = [...corners].sort((a, b) => angle(a) - angle(b));
    if (!isConvex(ordered)) return null;
    const first = ordered.reduce((best, point, index) => {
        const current = ordered[best];
        const difference = point.x + point.y - (current.x + current.y);
        return difference < 0 || (difference === 0 && point.x < current.x) ? index : best;
    }, 0);
    return [...ordered.slice(first), ...ordered.slice(0, first)];
}

function defaultPoints() {
    return [{ x: .2, y: .2 }, { x: .8, y: .2 }, { x: .8, y: .8 }, { x: .2, y: .8 }];
}

function setMessage(text, error = false) {
    message.textContent = text;
    message.classList.toggle("is-error", error);
}

function refreshControls() {
    const ready = Boolean(photo && hasDesign && outline);
    opacity.disabled = !ready;
    submitButton.disabled = !ready;
    stage.hidden = !photo;
    stage.classList.toggle("is-editable", ready);
    sketchOverlay.hidden = !ready;
    sketchOutline.toggleAttribute("hidden", !ready);
    placeholder.hidden = Boolean(photo);
}

function updateOpacity() {
    sketchOverlay.style.opacity = 1 - Number(opacity.value) / 100;
    opacityValue.value = opacity.value + "%";
    opacity.setAttribute("aria-valuetext", opacityValue.value);
}

opacity.addEventListener("input", updateOpacity);
updateOpacity();

function positionSketch(width, height) {
    const [a, b, c, d] = outline.map(({ x, y }) => [x * width, y * height]);
    const [ax, ay] = a;
    const [bx, by] = b;
    const [cx, cy] = c;
    const [dx, dy] = d;
    const tx = ax - bx + cx - dx;
    const ty = ay - by + cy - dy;
    const determinant = (bx - cx) * (dy - cy) - (dx - cx) * (by - cy);
    const g = (tx * (dy - cy) - (dx - cx) * ty) / determinant;
    const h = ((bx - cx) * ty - tx * (by - cy)) / determinant;
    // Project the overlay onto the same four corners sent to the server.
    sketchOverlay.style.transform = `matrix3d(${[
        ((1 + g) * bx - ax) / width, ((1 + g) * by - ay) / width, 0, g / width,
        ((1 + h) * dx - ax) / height, ((1 + h) * dy - ay) / height, 0, h / height,
        0, 0, 1, 0, ax, ay, 0, 1,
    ].join(",")})`;
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
        handle.hidden = sketchOverlay.hidden || !point;
        if (point) {
            handle.style.setProperty("--corner-x", point.x * 100 + "%");
            handle.style.setProperty("--corner-y", point.y * 100 + "%");
        }
    });
    if (!sketchOverlay.hidden) positionSketch(width, height);
}

function syncPoints() {
    if (photo && hasDesign && !points.length) points = defaultPoints();
    outline = orderedOutline(points);
    inputs.corners.value = JSON.stringify(outline || points);
    const vertices = (outline || []).map(({ x, y }) => `${x * 100},${y * 100}`).join(" ");
    outlineStrokes.forEach((stroke) => stroke.setAttribute("points", vertices));
    refreshControls();
    draw();
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
    const next = [...points];
    next[index] = point;
    // Keep the four handles in their cyclic order and reject folds or overlaps.
    if (!isConvex(next)) return;
    points = next;
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
    const handle = event.target.closest("[data-corner]");
    if (sketchOverlay.hidden || !handle || !event.isPrimary || event.button !== 0 || drag) return;
    const origin = pointerPosition(event);
    const index = Number(handle.dataset.corner);
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
    if (sketchOverlay.hidden || !handle || !direction || drag) return;
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
    setMessage("");
    refreshControls();

    const url = file ? URL.createObjectURL(file) : (await facadeCatalog).get(selection);
    if (!url) {
        if (version === photoVersion && selection) setMessage("Не удалось открыть выбранный фасад.", true);
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
        if (file) URL.revokeObjectURL(url);
    }
}

async function chooseDesign() {
    finishDrag();
    const version = ++designVersion;
    const file = inputs.mural_file.files[0];
    const selection = inputs.design.value;
    hasDesign = false;
    designImage.hidden = true;
    designImage.removeAttribute("src");
    if (designUrl) URL.revokeObjectURL(designUrl);
    designUrl = "";
    sketchOverlay.removeAttribute("src");
    setMessage("");
    refreshControls();
    draw();

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
        sketchOverlay.src = url;
        hasDesign = true;
        syncPoints();
    } catch {
        if (version === designVersion) setMessage("Не удалось открыть эскиз.", true);
    }
}

inputs.facade.addEventListener("change", () => {
    inputs.facade_file.value = "";
    choosePhoto();
});
inputs.facade_file.addEventListener("change", () => {
    if (inputs.facade_file.files.length) inputs.facade.value = "";
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

form.addEventListener("submit", (event) => {
    if (submitButton.disabled) {
        event.preventDefault();
        return;
    }
    submitButton.disabled = true;
    setMessage("Отправляем заявку…");
});

if (!inputs.facade.value && !form.querySelector(".errorlist") && inputs.facade.options.length > 1) {
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
        points = orderedOutline(saved) || [];
    }
} catch {
    // An empty field is expected on the first visit.
}
choosePhoto(true);
chooseDesign();

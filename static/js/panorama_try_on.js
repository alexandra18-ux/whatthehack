function setupPanoramaTryOn(viewer) {
    const stage = viewer.querySelector(".panorama-try-on-stage");
    const photo = viewer.querySelector("#public-panorama-image");
    const guide = viewer.querySelector(".panorama-try-on-guide");
    const outline = guide.querySelector("polygon");
    const handles = [...guide.querySelectorAll("[data-wall-corner]")];
    const artwork = viewer.querySelector(".panorama-try-on-artwork");
    const start = viewer.querySelector("[data-try-on-start]");
    const tools = viewer.querySelector(".panorama-try-on-tools");
    const capture = viewer.querySelector("[data-try-on-capture]");
    const field = viewer.querySelector("[data-try-on-field]");
    const upload = viewer.querySelector("[data-try-on-upload]");
    const catalog = viewer.querySelector("[data-try-on-catalog]");
    const toggle = viewer.querySelector("[data-try-on-toggle]");
    const help = viewer.querySelector("[data-try-on-help]");
    const status = viewer.querySelector("[data-try-on-status]");
    const defaultCorners = [[.22, .26], [.78, .26], [.78, .74], [.22, .74]];
    const instructions = help.textContent;
    const radians = Math.PI / 180;
    const starting = viewer.querySelector("#starting-camera");
    let camera = starting ? JSON.parse(starting.textContent) : null;
    let viewpoint;
    let wall;
    let objectUrl;
    let version = 0;
    let corners = defaultCorners;

    function drawGuide() {
        outline.setAttribute("points", corners.map(([x, y]) => `${100 * x},${100 * y}`).join(" "));
        handles.forEach((handle, index) => {
            handle.style.left = 100 * corners[index][0] + "%";
            handle.style.top = 100 * corners[index][1] + "%";
        });
    }

    function validCorners(points) {
        return points.every(([x, y], index) => {
            const [bx, by] = points[(index + 1) % 4];
            const [cx, cy] = points[(index + 2) % 4];
            return (bx - x) * (cy - y) - (by - y) * (cx - x) > .0005;
        });
    }

    function guideBounds() {
        const style = getComputedStyle(guide.parentElement);
        const padding = (side) => (parseFloat(style.getPropertyValue(`--try-on-inset-${side}`)) || 0) + 12;
        const side = Math.min(.19, padding("side") / stage.clientWidth);
        const top = Math.min(.32, padding("top") / stage.clientHeight);
        const bottom = Math.min(.42, padding("bottom") / stage.clientHeight);
        return [side, top, 1 - side, 1 - bottom];
    }

    function moveCorner(index, x, y) {
        const [minX, minY, maxX, maxY] = guideBounds();
        const next = [...corners];
        next[index] = [Math.max(minX, Math.min(x, maxX)), Math.max(minY, Math.min(y, maxY))];
        if (!validCorners(next)) return;
        corners = next;
        drawGuide();
    }

    handles.forEach((handle, index) => {
        handle.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            handle.setPointerCapture(event.pointerId);
            event.stopPropagation();
        });
        handle.addEventListener("pointermove", (event) => {
            if (!handle.hasPointerCapture(event.pointerId)) return;
            const rect = stage.getBoundingClientRect();
            moveCorner(index, (event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height);
        });
        handle.addEventListener("keydown", (event) => {
            const step = event.shiftKey ? 10 : 2;
            const movement = {
                ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                ArrowUp: [0, -step], ArrowDown: [0, step],
            }[event.key];
            if (!movement) return;
            event.preventDefault();
            event.stopPropagation();
            moveCorner(index, corners[index][0] + movement[0] / stage.clientWidth,
                corners[index][1] + movement[1] / stage.clientHeight);
        });
    });

    function axes([yaw, pitch, fov]) {
        const x = Math.sin(yaw * radians);
        const z = Math.cos(yaw * radians);
        const up = Math.sin(pitch * radians);
        const forward = Math.cos(pitch * radians);
        return {
            right: [z, 0, -x],
            up: [-up * x, forward, -up * z],
            forward: [forward * x, up, forward * z],
            scale: Math.tan(fov * radians / 2),
        };
    }

    function snapshot() {
        const view = axes(camera);
        const aspect = stage.clientWidth / stage.clientHeight;
        const span = view.scale * 2;
        const [[ax, ay], [bx, by], [cx, cy], [dx, dy]] = corners;
        const tx = ax - bx + cx - dx;
        const ty = ay - by + cy - dy;
        const determinant = (bx - cx) * (dy - cy) - (dx - cx) * (by - cy);
        const g = (tx * (dy - cy) - (dx - cx) * ty) / determinant;
        const h = ((bx - cx) * ty - tx * (by - cy)) / determinant;
        const ray = ([x, y]) => view.forward.map((value, i) =>
            value + (x - .5) * span * aspect * view.right[i] + (.5 - y) * span * view.up[i]);
        const [origin, right, , down] = corners.map(ray);
        return {
            origin,
            width: right.map((value, i) => (1 + g) * value - origin[i]),
            height: down.map((value, i) => (1 + h) * value - origin[i]),
        };
    }

    const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);

    function draw() {
        artwork.hidden = true;
        if (!wall || !artwork.hasAttribute("src") || toggle.getAttribute("aria-pressed") !== "true") return;
        const { clientWidth: width, clientHeight: height } = stage;
        if (!width || !height) return;
        const view = axes(camera);
        const focus = height / (2 * view.scale);

        // Project the wall's original camera plane into the current panorama viewport.
        function column(vector, units = 1) {
            const depth = dot(vector, view.forward);
            return [
                (focus * dot(vector, view.right) + width / 2 * depth) / units,
                (-focus * dot(vector, view.up) + height / 2 * depth) / units,
                0, depth / units,
            ];
        }
        const right = column(wall.width, width);
        const down = column(wall.height, height);
        const origin = column(wall.origin);
        const depths = [origin[3], origin[3] + right[3] * width, origin[3] + down[3] * height,
            origin[3] + right[3] * width + down[3] * height];
        if (Math.min(...depths) < .001) return;

        artwork.style.transform = `matrix3d(${[...right, ...down, 0, 0, 1, 0, ...origin].join(",")})`;
        artwork.hidden = false;
    }

    function reset() {
        version++;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = null;
        artwork.removeAttribute("src");
        wall = null;
        corners = defaultCorners;
        upload.value = "";
        if (catalog) catalog.value = "";
        status.textContent = "";
        help.textContent = instructions;
        start.textContent = "Примерить на стене";
        tools.hidden = true;
        guide.hidden = true;
        field.hidden = true;
        toggle.hidden = true;
        draw();
    }

    start.hidden = !camera;
    start.addEventListener("click", () => {
        if (!tools.hidden && !guide.hidden) return;
        if (wall) {
            const view = axes(camera);
            const scale = 2 * view.scale;
            const aspect = stage.clientWidth / stage.clientHeight;
            const [minX, minY, maxX, maxY] = guideBounds();
            const projected = [[0, 0], [1, 0], [1, 1], [0, 1]].map(([x, y]) => {
                const point = wall.origin.map((value, i) => value + x * wall.width[i] + y * wall.height[i]);
                const depth = dot(point, view.forward);
                if (depth <= .001) return [-1, -1];
                return [.5 + dot(point, view.right) / (depth * scale * aspect),
                    .5 - dot(point, view.up) / (depth * scale)];
            });
            corners = projected.every(([x, y]) => x >= minX && y >= minY && x <= maxX && y <= maxY) &&
                validCorners(projected) ? projected : defaultCorners;
        }
        wall = null;
        help.textContent = instructions;
        status.textContent = "";
        start.textContent = "Изменить рамку";
        tools.hidden = false;
        capture.hidden = false;
        field.hidden = true;
        toggle.hidden = true;
        drawGuide();
        guide.hidden = false;
        draw();
        handles[0].focus({ preventScroll: true });
    });

    capture.addEventListener("click", () => {
        if (!camera || !stage.clientHeight || (photo && (!photo.complete || !photo.naturalWidth))) {
            status.textContent = "Дождитесь загрузки кадра и повторите.";
            return;
        }
        wall = snapshot();
        guide.hidden = true;
        capture.hidden = true;
        field.hidden = false;
        status.textContent = "";
        if (artwork.hasAttribute("src")) {
            toggle.setAttribute("aria-pressed", "true");
            toggle.hidden = false;
            help.textContent = "Рамка обновлена. Эскиз подстроился под углы стены.";
            draw();
            start.focus({ preventScroll: true });
        } else {
            help.textContent = "Ракурс зафиксирован. Выберите изображение для примерки.";
            (catalog || upload).focus();
        }
    });

    async function applySketch(url, fromFile = false) {
        const request = ++version;
        const candidate = new Image();
        candidate.src = url;
        try {
            await candidate.decode();
            if (request !== version) return;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = fromFile ? url : null;
            artwork.src = url;
            toggle.setAttribute("aria-pressed", "true");
            toggle.hidden = false;
            help.textContent = "Поворачивайте панораму или меняйте масштаб: эскиз остаётся на выбранной стене.";
            status.textContent = "Эскиз размещён.";
            draw();
        } catch {
            if (request === version) status.textContent = "Не удалось открыть эскиз. Выберите другой файл.";
        } finally {
            if (fromFile && url !== objectUrl) URL.revokeObjectURL(url);
        }
    }

    upload.addEventListener("change", () => {
        const file = upload.files[0];
        if (!file || !wall) return;
        if (!["image/png", "image/jpeg"].includes(file.type) || file.size > 10 * 1024 * 1024) {
            status.textContent = "Выберите PNG или JPEG размером до 10 МБ.";
            return;
        }
        if (catalog) catalog.value = "";
        applySketch(URL.createObjectURL(file), true);
    });
    catalog?.addEventListener("change", () => {
        if (!wall || !catalog.value) return;
        upload.value = "";
        applySketch(catalog.value);
    });

    toggle.addEventListener("click", () => {
        toggle.setAttribute("aria-pressed", String(toggle.getAttribute("aria-pressed") !== "true"));
        draw();
    });
    viewer.addEventListener("panorama:camera", ({ detail }) => {
        if (detail.viewpoint !== viewpoint) reset();
        viewpoint = detail.viewpoint;
        camera = detail.camera;
        start.hidden = !camera;
        draw();
    });
    new ResizeObserver(draw).observe(stage);
}

document.querySelectorAll("[data-panorama-try-on]").forEach(setupPanoramaTryOn);

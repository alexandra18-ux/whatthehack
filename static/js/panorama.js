(() => {
    const form = document.querySelector("#placement-editor");
    const dialog = document.querySelector("#panorama-dialog");
    const openButton = document.querySelector("#open-panorama");
    if (!dialog?.showModal) return;

    const canvas = dialog.querySelector("canvas");
    const source = dialog.querySelector("#panorama-source");
    const upload = dialog.querySelector("#panorama-upload");
    const useButton = dialog.querySelector("#panorama-use");
    const status = dialog.querySelector("#panorama-status");
    const credit = dialog.querySelector("#panorama-credit");
    const radians = Math.PI / 180;
    const degrees = 180 / Math.PI;
    const pointers = new Map();
    let renderer;
    let current;
    let version = 0;
    let yaw = 0;
    let pitch = 0;
    let fov = 45;
    let span = 180;
    let frame;

    function setupRenderer() {
        const gl = canvas.getContext("webgl", { alpha: false, preserveDrawingBuffer: true });
        if (!gl) throw new Error("Браузер не поддерживает просмотр панорам. Можно загрузить обычное фото фасада.");

        function shader(type, code) {
            const compiled = gl.createShader(type);
            gl.shaderSource(compiled, code);
            gl.compileShader(compiled);
            if (!gl.getShaderParameter(compiled, gl.COMPILE_STATUS)) throw new Error();
            return compiled;
        }

        const program = gl.createProgram();
        gl.attachShader(program, shader(gl.VERTEX_SHADER, `
            attribute vec2 point;
            varying vec2 screenPoint;
            void main() {
                screenPoint = point;
                gl_Position = vec4(point, 0.0, 1.0);
            }
        `));
        gl.attachShader(program, shader(gl.FRAGMENT_SHADER, `
            precision highp float;
            varying vec2 screenPoint;
            uniform sampler2D photo;
            uniform vec4 camera;
            void main() {
                vec2 plane = screenPoint * vec2(1.6, 1.0) * camera.z;
                float y = plane.y * cos(camera.y) + sin(camera.y);
                float z = cos(camera.y) - plane.y * sin(camera.y);
                float lon = atan(plane.x, z) + camera.x;
                float lat = atan(y, length(vec2(plane.x, z)));
                float v = 0.5 - lat / camera.w;
                vec2 uv = vec2(fract(lon / 6.28318530718 + 0.5), v);
                gl_FragColor = v < 0.0 || v > 1.0
                    ? vec4(0.102, 0.122, 0.098, 1.0) : texture2D(photo, uv);
            }
        `));
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error();
        gl.useProgram(program);

        const point = gl.getAttribLocation(program, "point");
        const camera = gl.getUniformLocation(program, "camera");
        const mesh = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, mesh);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        gl.vertexAttribPointer(point, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(point);
        gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

        return {
            setImage(image) {
                const scale = Math.min(1, gl.getParameter(gl.MAX_TEXTURE_SIZE) / image.naturalWidth);
                let texture = image;
                if (scale < 1) {
                    texture = document.createElement("canvas");
                    texture.width = Math.floor(image.naturalWidth * scale);
                    texture.height = Math.floor(image.naturalHeight * scale);
                    texture.getContext("2d").drawImage(image, 0, 0, texture.width, texture.height);
                }
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, texture);
            },
            draw() {
                gl.uniform4f(camera, yaw * radians, pitch * radians, Math.tan(fov * radians / 2), span * radians);
                gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
            },
        };
    }

    function draw() {
        if (!current || frame) return;
        frame = requestAnimationFrame(() => {
            frame = null;
            renderer?.draw();
        });
    }

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    function adjust(turn, tilt, zoom = 1) {
        if (!current) return;
        yaw = ((yaw + turn + 180) % 360 + 360) % 360 - 180;
        fov = clamp(fov * zoom, 8, Math.min(80, span * .92));
        const limit = Math.min(85, (span - fov) / 2);
        pitch = clamp(pitch + tilt, -limit, limit);
        draw();
    }

    function reset() {
        yaw = current?.heading || 0;
        pitch = 0;
        fov = Math.min(45, span * .84);
        adjust(0, 0);
    }

    function showCredit(option) {
        credit.replaceChildren();
        credit.hidden = !option?.dataset.credit;
        if (credit.hidden) return;
        const { credit: author, source: original, license, licenseUrl } = option.dataset;
        for (const [label, url] of [[author, original], [license, licenseUrl]]) {
            if (!label) continue;
            if (credit.childNodes.length) credit.append(" · ");
            if (!url) {
                credit.append(label);
                continue;
            }
            const link = document.createElement("a");
            link.textContent = label;
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener";
            credit.append(link);
        }
        if (license) credit.append(". Эта лицензия применяется и к визуализации на основе панорамы.");
    }

    async function load(option, file) {
        const request = ++version;
        current = null;
        canvas.hidden = true;
        useButton.disabled = true;
        showCredit(file ? null : option);
        status.textContent = "";
        status.classList.remove("is-error");
        if (!file && !option?.dataset.image) return;
        status.textContent = "Открываем панораму…";
        let objectUrl;
        try {
            if (file && (!["image/jpeg", "image/png"].includes(file.type) || file.size > 20 * 1024 * 1024)) {
                throw new Error("Выберите панораму JPEG или PNG размером до 20 МБ.");
            }
            const image = new Image();
            if (file) objectUrl = URL.createObjectURL(file);
            image.src = objectUrl || option.dataset.image;
            await image.decode();
            if (request !== version) return;
            const ratio = image.naturalHeight / image.naturalWidth;
            if (image.naturalWidth < 800 || ratio < .05 || ratio > .51 ||
                image.naturalWidth * image.naturalHeight > 36_000_000) {
                throw new Error("Выберите круговую панораму 360°, например JPEG с камеры или телефона в формате 2:1.");
            }

            renderer ??= setupRenderer();
            renderer.setImage(image);
            span = Math.min(360 * ratio, 180);
            current = {
                id: file ? "" : option.value,
                heading: file ? 0 : Number(option.dataset.heading) || 0,
                title: file ? file.name : option.textContent.trim(),
            };
            reset();
            const savedCamera = current.id && current.id === form.elements.panorama.value;
            if (savedCamera) {
                try {
                    [yaw, pitch, fov] = JSON.parse(form.elements.panorama_camera.value);
                    adjust(0, 0);
                } catch {
                    reset();
                }
            }
            canvas.hidden = false;
            useButton.disabled = false;
            status.textContent = "";
        } catch (error) {
            if (request === version) {
                status.classList.add("is-error");
                status.textContent = error.message || "Не удалось открыть панораму. Выберите другой снимок или фото фасада.";
            }
        } finally {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        }
    }

    function open() {
        dialog.showModal();
        if (form.elements.panorama.value) source.value = form.elements.panorama.value;
        load(source.selectedOptions[0], upload.files[0]);
    }

    openButton.hidden = false;
    openButton.addEventListener("click", open);
    source.addEventListener("change", () => {
        upload.value = "";
        load(source.selectedOptions[0]);
    });
    upload.addEventListener("change", () => load(source.selectedOptions[0], upload.files[0]));
    dialog.querySelector("#panorama-reset").addEventListener("click", reset);
    dialog.querySelectorAll("[data-panorama-zoom]").forEach((button) => {
        button.addEventListener("click", () => adjust(0, 0, 1.2 ** Number(button.dataset.panoramaZoom)));
    });

    canvas.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        canvas.setPointerCapture(event.pointerId);
        pointers.set(event.pointerId, event);
    });
    canvas.addEventListener("pointermove", (event) => {
        const previous = pointers.get(event.pointerId);
        if (!previous) return;
        pointers.set(event.pointerId, event);
        const other = [...pointers.values()].find((pointer) => pointer !== event);
        if (other) {
            const oldDistance = Math.hypot(previous.clientX - other.clientX, previous.clientY - other.clientY);
            const distance = Math.hypot(event.clientX - other.clientX, event.clientY - other.clientY);
            if (distance > 0 && oldDistance > 0) adjust(0, 0, oldDistance / distance);
            return;
        }
        const unit = fov / canvas.clientHeight;
        adjust((previous.clientX - event.clientX) * unit, (event.clientY - previous.clientY) * unit);
    });
    canvas.addEventListener("lostpointercapture", (event) => pointers.delete(event.pointerId));
    canvas.addEventListener("wheel", (event) => {
        if (event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        adjust(0, 0, event.deltaY > 0 ? 1.13 : 1 / 1.13);
    }, { passive: false });
    const keys = new Map([
        ["ArrowLeft", [-5, 0]], ["ArrowRight", [5, 0]], ["ArrowUp", [0, 5]], ["ArrowDown", [0, -5]],
        ["+", [0, 0, 1 / 1.2]], ["-", [0, 0, 1.2]],
    ]);
    canvas.addEventListener("keydown", (event) => {
        if (!keys.has(event.key)) return;
        event.preventDefault();
        adjust(...keys.get(event.key));
    });
    useButton.addEventListener("click", () => {
        if (!current) return;
        const selected = current;
        const camera = [yaw, pitch, fov];
        function select(file) {
            if (!dialog.open || current !== selected) return;
            dialog.close();
            form.dispatchEvent(new CustomEvent("panorama:chosen", { detail: { ...selected, camera, file } }));
        }
        if (selected.id) {
            select();
        } else {
            useButton.disabled = true;
            renderer.draw();
            canvas.toBlob((blob) => {
                if (blob) select(new File([blob], "panorama-facade.jpg", { type: "image/jpeg" }));
                else {
                    status.textContent = "Не удалось сохранить кадр. Попробуйте ещё раз.";
                    useButton.disabled = false;
                }
            }, "image/jpeg", .93);
        }
    });
    if (form.hasAttribute("data-open-panorama")) open();
})();

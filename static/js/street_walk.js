(() => {
    const dialog = document.querySelector("#street-walk-dialog");
    const playerElement = dialog?.querySelector(".street-walk-player");
    const status = dialog?.querySelector(".street-walk-status");
    const external = dialog?.querySelector("[data-street-walk-external]");
    const retry = dialog?.querySelector("[data-street-walk-retry]");
    const step = dialog?.querySelector("[data-street-walk-step]");
    const stepStatus = dialog?.querySelector("[data-street-walk-step-status]");
    let sdk;
    let player;
    let current;
    let selectedPoint;

    function loadSDK() {
        if (sdk) return sdk;
        const script = document.createElement("script");
        const url = new URL("https://api-maps.yandex.ru/2.1/");
        url.searchParams.set("lang", "ru_RU");
        url.searchParams.set("apikey", dialog.dataset.apiKey);
        url.searchParams.set("load", "panorama.locate,panorama.Player,panorama.isSupported");
        script.src = url.href;
        script.referrerPolicy = "strict-origin-when-cross-origin";

        sdk = new Promise((resolve, reject) => {
            const finish = (error) => {
                clearTimeout(timer);
                if (error) reject(error);
                else resolve(window.ymaps);
            };
            const timer = setTimeout(() => finish(new Error()), 12000);
            script.addEventListener("load", () => {
                if (!window.ymaps?.ready) {
                    finish(new Error());
                    return;
                }
                window.ymaps.ready(() => finish(), () => finish(new Error()));
            }, { once: true });
            script.addEventListener("error", () => finish(new Error()), { once: true });
            document.head.append(script);
        }).catch((error) => {
            script.remove();
            sdk = null;
            throw error;
        });
        return sdk;
    }

    function showStatus(message, canRetry = false) {
        status.textContent = message;
        status.hidden = !message;
        retry.hidden = !canRetry;
    }

    function publishCamera(camera = null, viewpoint = null) {
        dialog.dispatchEvent(new CustomEvent("panorama:camera", { detail: { camera, viewpoint } }));
    }

    function stop() {
        current?.abort();
        current = null;
        player?.destroy();
        player = null;
        step.hidden = true;
        step.disabled = false;
        stepStatus.hidden = true;
        playerElement.replaceChildren();
        publishCamera();
    }

    async function showPanorama(link, point) {
        stop();
        const request = new AbortController();
        current = request;
        selectedPoint = point;
        external.href = link.href;
        showStatus("Загружаем панораму…");
        if (!dialog.open) dialog.showModal();
        const timer = setTimeout(() => {
            if (request.signal.aborted) return;
            request.abort();
            showStatus("Яндекс долго загружает панораму.", true);
        }, 18000);
        let stage = "sdk";
        try {
            const api = await loadSDK();
            if (request.signal.aborted) return;
            if (!api.panorama.isSupported()) {
                showStatus("В этом браузере панораму можно открыть в Яндекс Картах.");
                return;
            }
            stage = "locate";
            const [nearest] = await api.panorama.locate(point);
            if (request.signal.aborted) return;
            if (!nearest) {
                showStatus("Рядом с этой точкой панорама не найдена. Посмотрите доступные улицы в Яндекс Картах.");
                return;
            }
            stage = "player";
            player = new api.panorama.Player(playerElement, nearest, {
                controls: ["fullscreenControl", "panoramaName", "zoomControl"],
                hotkeysEnabled: true,
            });
            const activePlayer = player;
            let scheduled = false;
            function syncStep() {
                step.hidden = !activePlayer.getPanorama().getConnectionArrows().length;
                stepStatus.hidden = true;
            }
            function syncCamera() {
                if (scheduled) return;
                scheduled = true;
                requestAnimationFrame(() => {
                    scheduled = false;
                    if (request.signal.aborted || player !== activePlayer) return;
                    const [yaw, pitch] = activePlayer.getDirection();
                    const [, fov] = activePlayer.getSpan();
                    if ([yaw, pitch, fov].every(Number.isFinite) && fov > 0 && fov < 180) {
                        publishCamera([yaw, pitch, fov], activePlayer.getPanorama());
                    }
                });
            }
            for (const event of ["directionchange", "spanchange", "panoramachange", "fullscreenexit"]) {
                activePlayer.events.add(event, syncCamera);
            }
            activePlayer.events.add("panoramachange", syncStep);
            player.events.add("error", () => {
                if (request.signal.aborted) return;
                publishCamera();
                step.hidden = true;
                showStatus("Не удалось загрузить ракурс в плеере Яндекса.", true);
            });
            showStatus("");
            syncStep();
            syncCamera();
        } catch {
            if (request.signal.aborted) return;
            const messages = {
                sdk: "Не удалось подключить сервис Яндекс Карт.",
                locate: "Сервис Яндекса не вернул панораму для этой точки.",
                player: "Не удалось запустить плеер Яндекс Панорам.",
            };
            showStatus(messages[stage], true);
        } finally {
            clearTimeout(timer);
        }
    }

    dialog?.addEventListener("close", () => {
        if (!dialog.open) {
            stop();
            selectedPoint = null;
        }
    });
    retry?.addEventListener("click", () => {
        if (selectedPoint) showPanorama(external, selectedPoint);
    });
    step?.addEventListener("click", async () => {
        const activePlayer = player;
        const panorama = activePlayer?.getPanorama();
        const arrows = panorama?.getConnectionArrows();
        if (!arrows?.length) return;

        const [bearing] = activePlayer.getDirection();
        const distance = (arrow) => Math.abs(((arrow.getDirection()[0] - bearing + 540) % 360) - 180);
        const arrow = arrows.reduce((closest, candidate) => distance(candidate) < distance(closest) ? candidate : closest);
        step.disabled = true;
        stepStatus.hidden = false;
        stepStatus.textContent = "Переходим к соседней точке…";
        try {
            const next = await arrow.getConnectedPanorama();
            if (player !== activePlayer || panorama !== activePlayer.getPanorama()) return;
            await activePlayer.setPanorama(next);
            stepStatus.hidden = true;
        } catch {
            if (player === activePlayer) stepStatus.textContent = "Не удалось перейти к соседней точке. Попробуйте ещё раз.";
        } finally {
            if (player === activePlayer) step.disabled = false;
        }
    });

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a.street-walk-link");
        if (!link || event.defaultPrevented || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

        if (dialog?.showModal) {
            const point = new URL(link.href).searchParams.get("panorama[point]")?.split(",").map(Number);
            if (point?.length === 2 && point.every(Number.isFinite)) {
                event.preventDefault();
                showPanorama(link, point.reverse());
                return;
            }
        }
        if (!matchMedia("(min-width: 800px) and (pointer: fine)").matches) return;

        const width = Math.min(1180, Math.round(window.outerWidth * .86));
        const height = Math.min(800, Math.round(window.outerHeight * .86));
        const left = Math.round(window.screenX + (window.outerWidth - width) / 2);
        const top = Math.round(window.screenY + (window.outerHeight - height) / 2);
        const popup = window.open("", "_blank", `popup,width=${width},height=${height},left=${left},top=${top}`);
        if (!popup) return;

        popup.opener = null;
        popup.location.replace(link.href);
        event.preventDefault();
    });
})();

(() => {
    const dialog = document.querySelector("#street-walk-dialog");
    const playerElement = dialog?.querySelector(".street-walk-player");
    const status = dialog?.querySelector(".street-walk-status");
    const external = dialog?.querySelector("[data-street-walk-external]");
    let sdk;
    let player;
    let current;

    function loadSDK() {
        if (sdk) return sdk;
        const script = document.createElement("script");
        const url = new URL("https://api-maps.yandex.ru/2.1/");
        url.searchParams.set("lang", "ru_RU");
        url.searchParams.set("apikey", dialog.dataset.apiKey);
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

    function showStatus(message) {
        status.textContent = message;
        status.hidden = !message;
    }

    function stop() {
        current?.abort();
        current = null;
        player?.destroy();
        player = null;
        playerElement.replaceChildren();
    }

    async function showPanorama(link, point) {
        stop();
        const request = new AbortController();
        current = request;
        external.href = link.href;
        showStatus("Загружаем панораму…");
        dialog.showModal();
        const timer = setTimeout(() => {
            if (request.signal.aborted) return;
            request.abort();
            showStatus("Панорама долго загружается. Откройте её в Яндекс Картах или попробуйте ещё раз.");
        }, 18000);
        try {
            const api = await loadSDK();
            if (request.signal.aborted) return;
            if (!api.panorama.isSupported()) {
                showStatus("В этом браузере панораму можно открыть в Яндекс Картах.");
                return;
            }
            const [nearest] = await api.panorama.locate(point);
            if (request.signal.aborted) return;
            if (!nearest) {
                showStatus("Рядом с этой точкой панорама не найдена. Посмотрите доступные улицы в Яндекс Картах.");
                return;
            }
            player = new api.panorama.Player(playerElement, nearest, {
                controls: ["fullscreenControl", "panoramaName", "zoomControl"],
                hotkeysEnabled: true,
            });
            player.events.add("error", () => {
                if (!request.signal.aborted) showStatus("Не удалось загрузить ракурс. Откройте панораму в Яндекс Картах.");
            });
            showStatus("");
        } catch {
            if (!request.signal.aborted) showStatus("Панорама недоступна. Попробуйте открыть её в Яндекс Картах.");
        } finally {
            clearTimeout(timer);
        }
    }

    dialog?.addEventListener("close", () => {
        if (!dialog.open) stop();
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

(() => {
    const element = document.querySelector("#city-map");
    const hint = document.querySelector("#map-hint");
    const addressButtons = [...document.querySelectorAll("[data-address-point]")];
    const leaflet = window.L;
    if (!leaflet) {
        hint.textContent = "Карта недоступна. Здание можно выбрать по адресу или из списка.";
        return;
    }

    const coordinates = ({ latitude, longitude }) => [latitude, longitude];
    const bounds = leaflet.latLngBounds(JSON.parse(document.querySelector("#region-map-bounds").textContent));
    const addressPoint = (button) => [Number(button.dataset.latitude), Number(button.dataset.longitude)];
    const firstAddress = addressButtons[0];
    const map = leaflet.map(element, {
        scrollWheelZoom: true, touchZoom: true,
        minZoom: 4, maxZoom: 19, zoomSnap: 0.25,
        maxBounds: bounds, maxBoundsViscosity: 1,
        zoomControl: false,
    }).setView(firstAddress ? addressPoint(firstAddress) : [51.517, 46.08], firstAddress ? 17 : 12);
    leaflet.control.zoom({ position: "topright", zoomInTitle: "Приблизить", zoomOutTitle: "Отдалить" }).addTo(map);
    map.attributionControl.setPrefix(false);

    function isOverMap(event) {
        if (Number.isFinite(event.clientX) && Number.isFinite(event.clientY)) {
            return element.contains(document.elementFromPoint(event.clientX, event.clientY));
        }
        return event.composedPath().includes(element);
    }

    function zoomAt(point, zoom) {
        map.setZoomAround(point, zoom, { animate: false });
    }

    const captureGesture = { capture: true, passive: false };
    let pinchDelta = 0;
    let lastPinch = -Infinity;
    let nativePinch;
    // Window capture sees browser zoom events even when their target isn't the map.
    window.addEventListener("wheel", (event) => {
        if ((!event.ctrlKey && !event.metaKey) || !isOverMap(event)) return;
        event.preventDefault();
        event.stopPropagation();
        if (nativePinch) return;
        const now = performance.now();
        if (now - lastPinch > 160) pinchDelta = 0;
        lastPinch = now;

        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? element.clientHeight : 1;
        pinchDelta -= event.deltaY * unit;
        const steps = Math.max(-4, Math.min(4, Math.trunc(pinchDelta / 15)));
        if (!steps) return;
        pinchDelta %= 15;
        zoomAt(map.mouseEventToContainerPoint(event), map.getZoom() + steps * 0.25);
    }, captureGesture);

    // WebKit can send desktop pinches as gesture events instead of wheel events.
    window.addEventListener("gesturestart", (event) => {
        if (!isOverMap(event) || matchMedia("(pointer: coarse)").matches) return;
        event.preventDefault();
        nativePinch = { zoom: map.getZoom(), point: map.mouseEventToContainerPoint(event) };
    }, captureGesture);
    window.addEventListener("gesturechange", (event) => {
        if (!nativePinch) return;
        event.preventDefault();
        if (Number.isFinite(event.scale) && event.scale > 0) {
            zoomAt(nativePinch.point, nativePinch.zoom + Math.log2(event.scale));
        }
    }, captureGesture);
    window.addEventListener("gestureend", (event) => {
        if (!nativePinch) return;
        event.preventDefault();
        nativePinch = null;
    }, captureGesture);

    let tileErrors = false;
    let incompleteData = false;

    function updateHint() {
        const messages = [];
        if (tileErrors) messages.push("Часть подложки не загрузилась. Можно выбрать здание из списка.");
        if (incompleteData) messages.push("Часть меток недоступна.");
        hint.textContent = messages.join(" ");
        hint.hidden = messages.length === 0;
    }

    leaflet.tileLayer(element.dataset.tileUrl, {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).on({
        loading() { tileErrors = false; },
        tileerror() { tileErrors = true; updateHint(); },
        load: updateHint,
    }).addTo(map);
    element.classList.add("is-live");
    updateHint();

    const addressResult = document.querySelector("#map-address-result");
    const streetWalkLink = document.querySelector("#map-street-walk-link");

    function appendStreetWalk(container, url) {
        const link = streetWalkLink.content.querySelector("a").cloneNode(true);
        link.href = url;
        container.append(link);
    }
    let selection;
    let lookup;
    const mapViews = document.querySelector("#map-views");
    mapViews.hidden = false;
    mapViews.querySelector('[data-map-view="engels"]').addEventListener("click", () => {
        map.closePopup();
        map.setView([51.493, 46.124], 13);
    });
    mapViews.querySelector('[data-map-view="region"]').addEventListener("click", () => {
        map.closePopup();
        map.fitBounds(bounds, { padding: [16, 16] });
    });

    function selectPoint(point) {
        if (selection) {
            selection.setLatLng(point);
        } else {
            selection = leaflet.circleMarker(point, {
                radius: 8, color: "#fff", weight: 2, fillColor: "#3e691d",
                fillOpacity: 1, interactive: false,
            }).addTo(map);
        }
    }

    function highlightAddress(button) {
        for (const option of addressButtons) {
            option.setAttribute("aria-pressed", String(option === button));
        }
    }

    function showAddress(button) {
        lookup?.abort();
        map.closePopup();
        const point = addressPoint(button);
        selectPoint(point);
        map.setView(point, 17);
        highlightAddress(button);
    }

    for (const button of addressButtons) {
        button.hidden = false;
        button.addEventListener("click", () => {
            showAddress(button);
            element.scrollIntoView({ block: "nearest" });
        });
    }
    if (firstAddress) showAddress(firstAddress);

    async function findAddress(point) {
        lookup?.abort();
        const controller = new AbortController();
        lookup = controller;
        selectPoint(point);
        highlightAddress(null);

        const popupContent = document.createElement("div");
        popupContent.className = "map-address-result";
        popupContent.append(addressResult.content.cloneNode(true));
        const status = popupContent.querySelector("#map-address-status");
        const action = popupContent.querySelector("#map-address-action");
        status.textContent = "Ищем адрес…";
        const popup = leaflet.popup({ offset: [0, -6] }).setLatLng(point).setContent(popupContent).openOn(map);
        const params = new URLSearchParams({
            lat: point.lat.toFixed(6),
            lon: point.lng.toFixed(6),
        });

        try {
            const response = await fetch(`${element.dataset.address}?${params}`, { signal: controller.signal });
            const result = await response.json();
            if (controller.signal.aborted) return;
            status.textContent = response.ok ? result.address : result.error;
            if (response.ok) {
                const ticket = action.querySelector("[name=address_ticket]");
                if (ticket) {
                    ticket.value = result.ticket;
                } else {
                    const login = new URL(action.href);
                    login.searchParams.set("next", `${location.pathname}?${params}`);
                    action.href = login.href;
                }
                action.hidden = false;
                appendStreetWalk(popupContent, result.street_walk_url);
            }
        } catch (error) {
            if (controller.signal.aborted) return;
            status.textContent = "Поиск адреса временно недоступен. Попробуйте ещё раз.";
        }
        if (popup.isOpen()) popup.update();
    }

    map.on("click", ({ latlng }) => findAddress(latlng));
    const initialParams = new URLSearchParams(location.search);
    if (initialParams.has("lat") && initialParams.has("lon")) {
        const initialPoint = [Number(initialParams.get("lat")), Number(initialParams.get("lon"))];
        if (bounds.contains(initialPoint)) {
            map.setView(initialPoint, 17);
            findAddress(leaflet.latLng(initialPoint));
        }
    }

    async function load(url, key) {
        const response = await fetch(url);
        if (!response.ok) throw new Error("Не удалось загрузить данные карты.");
        return (await response.json())[key];
    }

    function appendLinks(popup, title, entries, label) {
        if (entries.length === 0) return;

        const heading = document.createElement("strong");
        heading.textContent = title;
        const list = document.createElement("ul");
        for (const entry of entries) {
            const item = document.createElement("li");
            const link = document.createElement("a");
            link.href = entry.url;
            link.textContent = entry[label];
            item.append(link);
            if (entry.street_walk_url) appendStreetWalk(item, entry.street_walk_url);
            list.append(item);
        }
        popup.append(heading, list);
    }

    const buildingMarkers = new Map();

    function showBuilding(marker) {
        lookup?.abort();
        selection?.remove();
        selection = undefined;
        highlightAddress(null);
        map.closePopup();
        map.setView(marker.getLatLng(), 17);
        marker.openPopup();
    }

    async function showMarkers() {
        const [buildings, projects] = await Promise.allSettled([
            load(element.dataset.buildings, "buildings"),
            load(element.dataset.projects, "projects"),
        ]);
        incompleteData = buildings.status !== "fulfilled" || projects.status !== "fulfilled";
        updateHint();
        const groups = new Map();

        function addToGroup(item, kind) {
            const point = coordinates(item);
            const key = point.join(",");
            if (!groups.has(key)) groups.set(key, { point, buildings: [], projects: [] });
            groups.get(key)[kind].push(item);
        }

        for (const building of buildings.value || []) addToGroup(building, "buildings");
        for (const project of projects.value || []) addToGroup(project, "projects");

        for (const group of groups.values()) {
            const hasProjects = group.projects.length > 0;
            const popup = document.createElement("div");
            popup.className = "map-popup";
            appendLinks(popup, "Здания", group.buildings, "address");
            appendLinks(popup, "Панорамы 360°", group.buildings.filter((building) => building.panorama_url).map(
                (building) => ({ title: "Открыть панораму 360°", url: building.panorama_url }),
            ), "title");
            appendLinks(popup, "Опубликованные проекты", group.projects, "title");
            const title = hasProjects ? group.projects[0].address : group.buildings[0].address;
            const marker = leaflet.marker(group.point, {
                icon: leaflet.divIcon({
                    className: hasProjects ? "map-marker map-marker-project" : "map-marker",
                    iconSize: hasProjects ? [24, 24] : [20, 20],
                }),
                title,
            }).addTo(map).bindPopup(popup);
            marker.getElement().setAttribute("aria-label", title);
            for (const building of group.buildings) {
                buildingMarkers.set(String(building.id), marker);
            }
        }
        const selectedMarker = buildingMarkers.get(element.dataset.selected);
        if (!firstAddress && selectedMarker) {
            map.setView(selectedMarker.getLatLng(), 16);
            selectedMarker.openPopup();
        }
    }

    const markersReady = showMarkers();
    const catalog = document.querySelector(".address-catalog");
    let requestedBuilding;
    for (const link of catalog.querySelectorAll("[data-map-building]")) {
        link.addEventListener("click", async (event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            requestedBuilding = link;
            await markersReady;
            if (requestedBuilding !== link) return;
            const marker = buildingMarkers.get(link.dataset.mapBuilding);
            if (!marker) {
                location.assign(link.href);
                return;
            }
            catalog.open = false;
            showBuilding(marker);
            marker.getElement().focus({ preventScroll: true });
        });
    }
})();

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
    const bounds = JSON.parse(document.querySelector("#saratov-map-bounds").textContent);
    const addressPoint = (button) => [Number(button.dataset.latitude), Number(button.dataset.longitude)];
    const firstAddress = addressButtons[0];
    const map = leaflet.map(element, {
        scrollWheelZoom: true, touchZoom: true,
        minZoom: 12, maxZoom: 19, zoomSnap: 0.25,
        maxBounds: bounds, maxBoundsViscosity: 1,
        zoomControl: false,
    }).setView(firstAddress ? addressPoint(firstAddress) : [51.5335, 46.0343], firstAddress ? 17 : 13);
    leaflet.control.zoom({ zoomInTitle: "Приблизить", zoomOutTitle: "Отдалить" }).addTo(map);
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
    const cityBoundary = JSON.parse(document.querySelector("#saratov-city-boundary").textContent);
    const outside = [[50, 44], [50, 48], [53, 48], [53, 44]];
    leaflet.polygon([outside, ...cityBoundary], {
        stroke: false, fillColor: "#e6ebe0", fillOpacity: 0.88, interactive: false,
    }).addTo(map);
    leaflet.polyline(cityBoundary, {
        color: "#40542b", opacity: 0.56, weight: 1.5, interactive: false,
    }).addTo(map);
    element.classList.add("is-live");
    updateHint();

    let selection;
    function showAddress(button) {
        const point = addressPoint(button);
        if (selection) {
            selection.setLatLng(point);
        } else {
            selection = leaflet.circleMarker(point, {
                radius: 8, color: "#fff", weight: 2, fillColor: "#3e691d",
                fillOpacity: 1, interactive: false,
            }).addTo(map);
        }
        map.setView(point, 17);
        for (const option of addressButtons) {
            option.setAttribute("aria-pressed", String(option === button));
        }
    }

    for (const button of addressButtons) {
        button.hidden = false;
        button.addEventListener("click", () => {
            showAddress(button);
            element.scrollIntoView({ block: "nearest" });
        });
    }
    if (firstAddress) showAddress(firstAddress);

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
            list.append(item);
        }
        popup.append(heading, list);
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
            if (!firstAddress && group.buildings.some((building) => String(building.id) === element.dataset.selected)) {
                map.setView(group.point, 16);
                marker.openPopup();
            }
        }
    }

    showMarkers();
})();

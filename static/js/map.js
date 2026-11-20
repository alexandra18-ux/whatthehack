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
        scrollWheelZoom: false, minZoom: 12, maxBounds: bounds, maxBoundsViscosity: 1,
        zoomControl: false,
    }).setView(firstAddress ? addressPoint(firstAddress) : [51.5335, 46.0343], firstAddress ? 17 : 13);
    leaflet.control.zoom({ zoomInTitle: "Приблизить", zoomOutTitle: "Отдалить" }).addTo(map);
    map.attributionControl.setPrefix(false);
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

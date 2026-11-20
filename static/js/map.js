(() => {
    const element = document.querySelector("#city-map");
    const hint = document.querySelector("#map-hint");
    const addLink = document.querySelector("#map-add");
    const leaflet = window.L;
    if (!leaflet) {
        hint.textContent = "Карта недоступна. Выберите здание в списке или введите координаты вручную.";
        return;
    }

    const coordinates = ({ latitude, longitude }) => [latitude, longitude];
    const map = leaflet.map(element, { scrollWheelZoom: false }).setView([51.5335, 46.0343], 13);
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

    let selection;
    map.on("click", (event) => {
        const point = map.wrapLatLng(event.latlng);
        if (selection) {
            selection.setLatLng(point);
        } else {
            selection = leaflet.circleMarker(point, {
                radius: 8, color: "#fff", weight: 2, fillColor: "#3e691d",
                fillOpacity: 1, interactive: false,
            }).addTo(map);
        }
        const url = new URL(element.dataset.newBuilding, location.origin);
        url.searchParams.set("latitude", point.lat.toFixed(6));
        url.searchParams.set("longitude", point.lng.toFixed(6));
        addLink.href = url;
        addLink.hidden = false;
    });

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
            if (group.buildings.some((building) => String(building.id) === element.dataset.selected)) {
                map.setView(group.point, 16);
                marker.openPopup();
            }
        }
    }

    showMarkers();
})();

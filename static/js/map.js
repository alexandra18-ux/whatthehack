const element = document.querySelector("#city-map");
const hint = document.querySelector("#map-hint");
const addLink = document.querySelector("#map-add");
const fallback = "Карта недоступна. Выберите здание в списке или укажите координаты вручную.";

async function load(url, key) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Не удалось загрузить данные карты.");
    return (await response.json())[key];
}

function openMarker(map, coordinates, title, description, url, preset) {
    const content = document.createElement("a");
    content.href = url;
    content.textContent = title;
    const body = document.createElement("p");
    body.textContent = description;
    const marker = new ymaps.Placemark(coordinates, {
        balloonContentHeader: content.outerHTML,
        balloonContentBody: body.outerHTML,
    }, { preset });
    map.geoObjects.add(marker);
    return marker;
}

async function initMap() {
    const [buildings, projects] = await Promise.all([
        load(element.dataset.buildings, "buildings"),
        load(element.dataset.projects, "projects"),
    ]);
    const coordinates = (item) => [item.latitude, item.longitude];
    const selected = buildings.find((building) => String(building.id) === element.dataset.selected);
    const map = new ymaps.Map(element, {
        center: selected ? coordinates(selected) : [51.5335, 46.0343],
        zoom: selected ? 16 : 13,
        controls: ["zoomControl"],
    });
    let current = null;

    for (const building of buildings) {
        const marker = openMarker(map, coordinates(building), building.address,
            "Открыть карточку здания", building.url, "islands#blueDotIcon");
        if (building === selected) current = marker;
    }
    const publishedByPoint = new Map();
    for (const project of projects) {
        const key = coordinates(project).join(",");
        if (!publishedByPoint.has(key)) publishedByPoint.set(key, []);
        publishedByPoint.get(key).push(project);
    }
    for (const group of publishedByPoint.values()) {
        const heading = document.createElement("span");
        heading.textContent = group[0].address;
        const list = document.createElement("ul");
        for (const project of group) {
            const item = document.createElement("li");
            const link = document.createElement("a");
            link.textContent = project.title;
            link.href = project.url;
            item.append(link);
            list.append(item);
        }
        const marker = new ymaps.Placemark(coordinates(group[0]), {
            balloonContentHeader: heading.outerHTML,
            balloonContentBody: list.outerHTML,
        }, { preset: "islands#violetIcon", zIndex: 650 });
        map.geoObjects.add(marker);
    }
    if (current) current.balloon.open();

    const selection = new ymaps.Placemark([0, 0], {}, { preset: "islands#greenDotIcon" });
    let selecting = false;
    map.events.add("click", (event) => {
        const point = event.get("coords");
        selection.geometry.setCoordinates(point);
        if (!selecting) {
            map.geoObjects.add(selection);
            selecting = true;
        }
        const url = new URL(element.dataset.newBuilding, location.origin);
        url.searchParams.set("latitude", point[0].toFixed(6));
        url.searchParams.set("longitude", point[1].toFixed(6));
        addLink.href = url;
        addLink.hidden = false;
    });
    hint.textContent = "Синие метки — здания, фиолетовые — опубликованные проекты.";
    element.classList.add("is-live");
}

if (window.ymaps) {
    ymaps.ready(() => initMap().catch(() => { hint.textContent = fallback; }),
        () => { hint.textContent = fallback; });
} else {
    hint.textContent = fallback;
}

(() => {
    const section = document.querySelector("#projects");
    const announcement = document.querySelector("#feed-announcement");
    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    let feed = section.querySelector("[data-feed]");
    let pending;
    let gesture;
    let settling;
    let suppressClick = false;
    let wheelTimer;
    let wheelUsed = false;
    let lastWheelDelta = 0;
    let queuedWheelDistance = 0;
    let queuedDirection;
    const adjacent = new Map();

    const WHEEL_GAP = 140;
    const WHEEL_THRESHOLD = 75;

    function activePost() {
        return feed.querySelector(".feed-post:not(.feed-preview)");
    }

    function navigationLink(direction) {
        return activePost()?.querySelector('[data-feed-direction="' + direction + '"]');
    }

    async function loadFeed(url, signal) {
        const response = await fetch(url, { headers: { "X-Muralium-Feed": "1" }, signal });
        if (!response.ok) throw new Error("Feed navigation failed");
        const template = document.createElement("template");
        template.innerHTML = await response.text();
        const replacement = template.content.querySelector("[data-feed]");
        if (!replacement) throw new Error("Feed was missing from the response");
        return replacement;
    }

    async function prepareCover(fragment) {
        const source = fragment.querySelector(".feed-cover img")?.getAttribute("src");
        if (!source) return;
        const image = new Image();
        image.src = source;
        await image.decode().catch(() => {});
    }

    function preload(url) {
        if (adjacent.has(url)) return adjacent.get(url);
        const controller = new AbortController();
        const entry = { controller };
        entry.request = loadFeed(url, controller.signal).then(async (fragment) => {
            await prepareCover(fragment);
            entry.fragment = fragment;
            return fragment;
        }).catch(() => null);
        adjacent.set(url, entry);
        return entry;
    }

    function warmAdjacentPosts() {
        for (const entry of adjacent.values()) entry.controller.abort();
        adjacent.clear();
        const previous = navigationLink("previous");
        const next = navigationLink("next");
        if (previous) preload(previous.href);
        if (next) preload(next.href);
    }

    function animate(element, property, start, end, duration) {
        return element.animate([{ [property]: start }, { [property]: end }], {
            duration, easing: "cubic-bezier(.22, .75, .24, 1)", fill: "both",
        });
    }

    function y(offset) {
        return "translateY(" + offset + "px)";
    }

    function makePreview(post) {
        post.classList.add("feed-preview");
        post.inert = true;
        post.setAttribute("aria-hidden", "true");
        post.removeAttribute("id");
        post.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    }

    function updateDrag(current) {
        if (reducedMotion.matches) return;
        const limit = current.pointer === undefined ? 110 : Infinity;
        const distance = Math.min(Math.abs(current.distance), limit, (current.travel || 0) * .85);
        current.offset = Math.sign(current.distance) * distance;
        current.post.style.transform = y(current.offset);
        if (current.preview) current.preview.style.transform = y(current.offset + current.previewStart);
    }

    function trackGesture(current, distance) {
        current.distance = distance;
        const direction = distance < 0 ? "next" : "previous";
        const link = navigationLink(direction);
        if (!link) return;

        if (current.direction !== direction) {
            current.preview?.remove();
            current.preview = null;
            current.travel = 0;
            current.direction = direction;
            current.url = link.href;
            const url = current.url;
            const entry = preload(url);
            if (!reducedMotion.matches) {
                const showPreview = (fragment) => {
                    if (!fragment || gesture !== current || current.url !== url || current.preview) return;
                    const preview = fragment.querySelector(".feed-post")?.cloneNode(true);
                    if (!preview) return;

                    makePreview(preview);
                    current.post.before(preview);
                    current.preview = preview;
                    current.travel = current.post.getBoundingClientRect().height;
                    current.previewStart = direction === "next" ? current.travel : -current.travel;
                    updateDrag(current);
                };
                if (entry.fragment) showPreview(entry.fragment);
                else entry.request.then(showPreview);
            }
        }
        updateDrag(current);
    }

    function releaseGesture(current) {
        if (gesture === current) gesture = null;
        current.preview?.remove();
        current.post.style.transform = "";
    }

    function stopSettling() {
        if (!settling) return;
        const { animations, preview } = settling;
        settling = null;
        preview?.remove();
        animations.forEach((animation) => animation.cancel());
    }

    function cancelGesture() {
        const current = gesture;
        if (!current) return;
        gesture = null;
        if (current.offset) {
            const animations = [animate(current.post, "transform", y(current.offset), y(0), 170)];
            const preview = current.preview;
            if (preview) {
                animations.push(animate(
                    preview, "transform", y(current.offset + current.previewStart),
                    y(current.previewStart), 170,
                ));
            }
            current.post.style.transform = "";
            const motion = { animations, preview };
            settling = motion;
            Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
                if (settling === motion) stopSettling();
            });
        } else {
            releaseGesture(current);
        }
    }

    async function slideTo(incoming, outgoing, direction, offset, signal) {
        makePreview(outgoing);
        const travel = incoming.getBoundingClientRect().height * (direction === "next" ? -1 : 1);
        const start = Math.sign(travel) * Math.min(Math.abs(offset), Math.abs(travel));
        const duration = offset ? 285 : 370;
        const animations = [
            animate(outgoing, "transform", y(start), y(travel), duration),
            animate(incoming, "transform", y(start - travel), y(0), duration),
        ];
        const cancel = () => animations.forEach((animation) => animation.cancel());
        signal.addEventListener("abort", cancel, { once: true });
        try {
            await Promise.allSettled(animations.map((animation) => animation.finished));
        } finally {
            signal.removeEventListener("abort", cancel);
            outgoing.remove();
            cancel();
        }
    }

    async function navigate(url, { direction, fromHistory = false, moveFocus = false, drag } = {}) {
        if (pending && !fromHistory) return;
        pending?.abort();
        if (fromHistory) queuedDirection = undefined;
        if (!drag) {
            cancelGesture();
            stopSettling();
        }
        const controller = new AbortController();
        pending = controller;
        feed.setAttribute("aria-busy", "true");

        try {
            const cached = adjacent.get(url);
            adjacent.delete(url);
            let replacement = cached && await cached.request;
            if (!replacement) {
                replacement = await loadFeed(url, controller.signal);
                await prepareCover(replacement);
            }
            if (controller.signal.aborted) return;
            const outgoing = activePost();
            const viewport = outgoing?.parentElement;
            const incoming = replacement.querySelector(".feed-post");
            const shouldSlide = direction && outgoing && incoming && !reducedMotion.matches;
            const offset = drag?.offset || 0;
            if (drag) releaseGesture(drag);
            if (!fromHistory) history.pushState(null, "", url);
            // Keep the wheel viewport mounted. Chromium can latch a wheel gesture to it.
            if (viewport && incoming) {
                if (shouldSlide) outgoing.after(incoming);
                else outgoing.replaceWith(incoming);
                feed.dataset.post = replacement.dataset.post;
            } else {
                replacement.setAttribute("aria-busy", "true");
                feed.replaceWith(replacement);
                feed = replacement;
            }
            if (shouldSlide) {
                await slideTo(incoming, outgoing, direction, offset, controller.signal);
            }
            if (controller.signal.aborted) return;

            const title = feed.querySelector("#feed-title");
            announcement.textContent = title?.textContent.trim() ?? "В ленте пока нет работ";
            if (moveFocus) (navigationLink(direction) || title)?.focus({ preventScroll: true });
            warmAdjacentPosts();
        } catch {
            if (controller.signal.aborted) return;
            queuedDirection = undefined;
            if (fromHistory) location.reload();
            else location.assign(url);
        } finally {
            if (pending === controller) {
                feed.removeAttribute("aria-busy");
                pending = null;
                const link = navigationLink(queuedDirection);
                queuedDirection = undefined;
                if (link) navigate(link.href, { direction: link.dataset.feedDirection });
            }
        }
    }

    function commitGesture(current) {
        if (!current.url || pending) {
            cancelGesture();
            return;
        }
        navigate(current.url, { direction: current.direction, drag: current });
    }

    section.addEventListener("click", (event) => {
        if (suppressClick && event.target.closest("[data-swipe-area]")) {
            event.preventDefault();
            suppressClick = false;
            return;
        }
        const link = event.target.closest("a[data-feed-direction]");
        if (!link || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
        event.preventDefault();
        navigate(link.href, { direction: link.dataset.feedDirection, moveFocus: true });
    });

    section.addEventListener("pointerdown", (event) => {
        suppressClick = false;
        if (
            pending || !event.isPrimary || event.button !== 0 ||
            !event.target.closest("[data-swipe-area]") || event.target.closest("[data-feed-direction]")
        ) return;
        if (gesture) cancelGesture();
        stopSettling();
        gesture = { post: activePost(), pointer: event.pointerId, startY: event.clientY, startTime: performance.now() };
        event.target.setPointerCapture(event.pointerId);
    });

    section.addEventListener("pointermove", (event) => {
        if (event.pointerId !== gesture?.pointer || pending) return;
        const distance = event.clientY - gesture.startY;
        if (Math.abs(distance) > 6 || gesture.direction) trackGesture(gesture, distance);
    });

    section.addEventListener("pointerup", (event) => {
        if (event.pointerId !== gesture?.pointer) return;
        const movement = event.clientY - gesture.startY;
        const distance = Math.abs(movement);
        const speed = distance / Math.max(1, performance.now() - gesture.startTime);
        suppressClick = distance > 10;
        if (distance >= 65 || (distance >= 30 && speed >= .42)) {
            trackGesture(gesture, movement);
            commitGesture(gesture);
        } else {
            cancelGesture();
        }
    });

    section.addEventListener("pointercancel", (event) => {
        if (event.pointerId === gesture?.pointer) cancelGesture();
    });

    // Keep the whole wheel gesture in the feed, even when its original card has moved away.
    document.addEventListener("wheel", (event) => {
        if (event.ctrlKey || event.metaKey) return;
        const hit = document.elementFromPoint(event.clientX, event.clientY);
        const viewport = hit?.closest(".feed-viewport");
        if (!wheelTimer) {
            if (!viewport) return;
            for (let panel = hit; panel !== viewport; panel = panel.parentElement) {
                if (panel.matches(".comment-list, .feed-sidebar, textarea") &&
                    panel.scrollHeight > panel.clientHeight) return;
            }
            if (hit.closest("input, textarea, select, [contenteditable]")) {
                event.preventDefault();
                return;
            }
        }
        event.preventDefault();
        clearTimeout(wheelTimer);
        wheelTimer = setTimeout(() => {
            wheelTimer = null;
            wheelUsed = false;
            lastWheelDelta = 0;
            queuedWheelDistance = 0;
            if (!pending && gesture && gesture.pointer === undefined) cancelGesture();
        }, WHEEL_GAP);
        if (
            !viewport || gesture?.pointer !== undefined ||
            Math.abs(event.deltaY) <= Math.abs(event.deltaX) ||
            !navigationLink(event.deltaY > 0 ? "next" : "previous")
        ) return;

        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerHeight : 1;
        const delta = event.deltaY * unit;
        // A fresh flick can arrive before the previous gesture's momentum has gone idle.
        if (wheelUsed && Math.abs(delta) >= 32 &&
            (Math.abs(lastWheelDelta) <= 12 || Math.sign(delta) !== Math.sign(lastWheelDelta))) {
            wheelUsed = false;
            queuedWheelDistance = 0;
        }
        lastWheelDelta = delta;
        if (wheelUsed) return;
        if (pending) {
            queuedWheelDistance += delta;
            if (Math.abs(queuedWheelDistance) >= WHEEL_THRESHOLD) {
                queuedDirection = queuedWheelDistance > 0 ? "next" : "previous";
                wheelUsed = true;
                queuedWheelDistance = 0;
            }
            return;
        }
        stopSettling();
        gesture ??= { post: activePost(), distance: 0 };
        trackGesture(gesture, gesture.distance - delta);
        if (Math.abs(gesture.distance) >= WHEEL_THRESHOLD) {
            wheelUsed = true;
            commitGesture(gesture);
        }
    }, { passive: false });

    const arrowDirections = new Map([
        ["ArrowUp", "previous"], ["ArrowLeft", "previous"],
        ["ArrowDown", "next"], ["ArrowRight", "next"],
    ]);
    document.addEventListener("keydown", (event) => {
        const direction = arrowDirections.get(event.key);
        if (
            !direction || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
            event.shiftKey || event.target.closest("input, textarea, select, [contenteditable], .comment-list")
        ) return;
        const bounds = feed.getBoundingClientRect();
        if (bounds.top > innerHeight * 0.8 || bounds.bottom < innerHeight * 0.25) return;
        const link = navigationLink(direction);
        if (!link) return;

        event.preventDefault();
        if (!event.repeat) navigate(link.href, { direction, moveFocus: true });
    });

    window.addEventListener("popstate", () => {
        const target = new URL(location.href);
        if (!pending && target.searchParams.get("post") === feed.dataset.post) return;
        navigate(target.href, { fromHistory: true });
    });

    warmAdjacentPosts();
})();

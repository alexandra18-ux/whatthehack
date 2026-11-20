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

    const WHEEL_GAP = 180;
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
        const distance = Math.min(Math.abs(current.distance), limit, current.travel * .85 || 24);
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
            current.loader?.abort();
            current.preview?.remove();
            current.preview = null;
            current.travel = 0;
            current.direction = direction;
            current.url = link.href;
            current.loader = new AbortController();
            const { loader } = current;
            current.fragment = loadFeed(current.url, loader.signal).catch(() => null);
            if (!reducedMotion.matches) {
                current.fragment.then((fragment) => {
                    if (!fragment || gesture !== current || loader.signal.aborted) return;
                    const preview = fragment.querySelector(".feed-post")?.cloneNode(true);
                    if (!preview) return;

                    makePreview(preview);
                    current.post.before(preview);
                    current.preview = preview;
                    current.travel = direction === "next"
                        ? current.post.offsetHeight : preview.offsetHeight;
                    current.previewStart = direction === "next" ? current.travel : -current.travel;
                    updateDrag(current);
                });
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
        current.loader?.abort();
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
        const viewport = incoming.parentElement;
        makePreview(outgoing);
        viewport.prepend(outgoing);
        const fromHeight = outgoing.offsetHeight;
        const toHeight = incoming.offsetHeight;
        const travel = direction === "next" ? -fromHeight : toHeight;
        const start = Math.sign(travel) * Math.min(Math.abs(offset), Math.abs(travel));
        const duration = offset ? 285 : 370;
        const animations = [
            animate(outgoing, "transform", y(start), y(travel), duration),
            animate(incoming, "transform", y(start - travel), y(0), duration),
            animate(viewport, "height", fromHeight + "px", toHeight + "px", duration),
        ];
        for (const animation of animations) {
            animation.pause();
            animation.currentTime = 0;
        }
        const finish = Promise.allSettled(animations.map((animation) => animation.finished));
        const cancel = () => animations.forEach((animation) => animation.cancel());
        signal.addEventListener("abort", cancel, { once: true });
        try {
            const image = incoming.querySelector(".feed-cover img");
            if (image && !image.complete) {
                await Promise.race([
                    image.decode().catch(() => {}),
                    new Promise((resolve) => setTimeout(resolve, 140)),
                ]);
            }
            if (!signal.aborted) {
                animations.forEach((animation) => animation.play());
                await finish;
            }
        } finally {
            signal.removeEventListener("abort", cancel);
            outgoing.remove();
            cancel();
        }
    }

    async function navigate(url, { direction, fromHistory = false, moveFocus = false, drag } = {}) {
        if (pending && !fromHistory) return;
        pending?.abort();
        if (!drag) {
            cancelGesture();
            stopSettling();
        }
        const controller = new AbortController();
        pending = controller;
        feed.setAttribute("aria-busy", "true");

        try {
            const replacement = (drag && await drag.fragment) ?? await loadFeed(url, controller.signal);
            if (controller.signal.aborted) return;
            const outgoing = activePost();
            const offset = drag?.offset || 0;
            if (drag) releaseGesture(drag);
            if (!fromHistory) history.pushState(null, "", url);
            replacement.setAttribute("aria-busy", "true");
            feed.replaceWith(replacement);
            feed = replacement;
            const incoming = activePost();
            if (direction && outgoing && incoming && !reducedMotion.matches) {
                await slideTo(incoming, outgoing, direction, offset, controller.signal);
            }
            if (controller.signal.aborted) return;

            const title = feed.querySelector("#feed-title");
            announcement.textContent = title?.textContent.trim() ?? "В ленте пока нет работ";
            if (moveFocus) (navigationLink(direction) || title)?.focus({ preventScroll: true });
        } catch {
            if (controller.signal.aborted) return;
            if (fromHistory) location.reload();
            else location.assign(url);
        } finally {
            if (pending === controller) {
                feed.removeAttribute("aria-busy");
                pending = null;
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

    // Trackpads emit wheel bursts. A pause separates a new gesture from inertial scrolling.
    section.addEventListener("wheel", (event) => {
        if (
            event.ctrlKey || event.metaKey || !event.target.closest("[data-feed-swipe]") ||
            event.target.closest(".feed-sidebar, input, textarea, select, [contenteditable]") ||
            Math.abs(event.deltaY) <= Math.abs(event.deltaX) || gesture?.pointer !== undefined
        ) return;
        if (!navigationLink(event.deltaY > 0 ? "next" : "previous")) return;
        event.preventDefault();
        clearTimeout(wheelTimer);
        wheelTimer = setTimeout(() => {
            wheelUsed = false;
            if (!pending && gesture) cancelGesture();
        }, WHEEL_GAP);
        if (wheelUsed || pending) return;

        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerHeight : 1;
        stopSettling();
        gesture ??= { post: activePost(), distance: 0 };
        trackGesture(gesture, gesture.distance - event.deltaY * unit);
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
})();

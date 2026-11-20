(() => {
    const section = document.querySelector("#projects");
    const announcement = document.querySelector("#feed-announcement");
    let feed = section.querySelector("[data-feed]");
    let pending;
    let swipe;
    let suppressClick = false;

    function navigationLink(direction) {
        return feed.querySelector(`[data-feed-direction="${direction}"]`);
    }

    async function navigate(url, { direction, fromHistory = false, moveFocus = false } = {}) {
        if (pending && !fromHistory) return;
        pending?.abort();
        const controller = new AbortController();
        pending = controller;
        feed.setAttribute("aria-busy", "true");

        try {
            const response = await fetch(url, {
                headers: { "X-Muralium-Feed": "1" },
                signal: controller.signal,
            });
            if (!response.ok) throw new Error("Feed navigation failed");
            const template = document.createElement("template");
            template.innerHTML = await response.text();
            const replacement = template.content.querySelector("[data-feed]");
            if (!replacement) throw new Error("Feed was missing from the response");
            if (controller.signal.aborted) return;

            if (direction) replacement.dataset.motion = direction;
            if (!fromHistory) history.pushState(null, "", url);
            feed.replaceWith(replacement);
            feed = replacement;

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
        if (!event.target.closest("[data-swipe-area]") || !event.isPrimary || event.button !== 0) return;
        swipe = { id: event.pointerId, x: event.clientX, y: event.clientY };
        event.target.setPointerCapture(event.pointerId);
    });

    section.addEventListener("pointerup", (event) => {
        if (event.pointerId !== swipe?.id) return;
        const x = event.clientX - swipe.x;
        const y = event.clientY - swipe.y;
        swipe = null;
        const movement = Math.abs(y) >= Math.abs(x) ? y : x;
        if (Math.abs(movement) < 55) return;

        suppressClick = true;
        const direction = movement < 0 ? "next" : "previous";
        const link = navigationLink(direction);
        if (link) navigate(link.href, { direction });
    });

    section.addEventListener("pointercancel", () => { swipe = null; });

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

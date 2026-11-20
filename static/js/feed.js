(() => {
    const section = document.querySelector("#projects");
    const announcement = document.querySelector("#feed-announcement");
    let feed = section.querySelector("[data-feed]");
    let pending;
    let swipe;
    let touchStart;
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
            const image = replacement.querySelector(".feed-cover img");
            if (image) {
                const preload = new Image();
                preload.src = new URL(image.getAttribute("src"), url);
                await preload.decode().catch(() => {});
            }
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

    let wheelDelta = 0;
    let lastWheelTime = -Infinity;
    let wheelHandled = false;

    section.addEventListener("wheel", (event) => {
      if (event.ctrlKey || event.metaKey ||
          !event.target.closest("[data-feed-swipe]") ||
          event.target.closest("form, [contenteditable]") ||
          Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;

      const direction = navigationLink(event.deltaY > 0 ? "next" : "previous");
      if (!direction) return;
      if (event.cancelable) event.preventDefault();

      const now = performance.now();
      if (now - lastWheelTime > 180) {
        wheelDelta = 0;
        wheelHandled = false;
      }
      lastWheelTime = now;
      if (wheelHandled || pending) {
        wheelHandled = true;
        return;
      }

      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
      wheelDelta += event.deltaY * unit;
      if (Math.abs(wheelDelta) >= 60) {
        wheelHandled = true;
        navigate(direction.href, { direction: direction.dataset.feedDirection });
      }
    }, { passive: false });

    section.addEventListener("touchstart", (event) => {
      touchStart = event.touches.length === 1 &&
        event.target.closest("[data-feed-swipe]") &&
        !event.target.closest("form, [contenteditable]") &&
        (navigationLink("next") || navigationLink("previous"))
        ? event.touches[0]
        : null;
    }, { passive: true });

    section.addEventListener("touchmove", (event) => {
      if (!touchStart || event.touches.length !== 1 || !event.cancelable) return;
      const touch = event.touches[0];
      if (touch.identifier !== touchStart.identifier) return;

      const dx = touch.clientX - touchStart.clientX;
      const dy = touch.clientY - touchStart.clientY;
      if (Math.abs(dy) > 6 && Math.abs(dy) > Math.abs(dx) * 1.25) {
        event.preventDefault();
      }
    }, { passive: false });

    section.addEventListener("touchcancel", () => {
      touchStart = null;
    });

    section.addEventListener("touchend", (event) => {
      const start = touchStart;
      touchStart = null;
      if (!start || event.touches.length) return;

      const end = [...event.changedTouches].find((touch) => touch.identifier === start.identifier);
      if (!end) return;
      const dx = end.clientX - start.clientX;
      const dy = end.clientY - start.clientY;
      if (Math.abs(dy) < 55 || Math.abs(dy) <= Math.abs(dx) * 1.25) return;

      if (event.cancelable) event.preventDefault();
      const direction = navigationLink(dy < 0 ? "next" : "previous");
      if (direction) navigate(direction.href, { direction: direction.dataset.feedDirection });
    }, { passive: false });

    section.addEventListener("pointerdown", (event) => {
        suppressClick = false;
        if (event.pointerType === "touch" || !event.target.closest("[data-swipe-area]") || !event.isPrimary || event.button !== 0) return;
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

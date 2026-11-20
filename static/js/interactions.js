(() => {
    "use strict";

    const selector = "form.rating-form, form.comment-form, form.comment-like";

    function showError(container, message) {
        let alert = container.querySelector(".interaction-error");
        if (!alert) {
            alert = document.createElement("p");
            alert.className = "interaction-error";
            alert.setAttribute("role", "alert");
            container.append(alert);
        }
        alert.textContent = message;
    }

    document.addEventListener("submit", async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches(selector)) return;

        const isRating = form.matches(".rating-form");
        const isComment = form.matches(".comment-form");
        const container = form.closest(isRating ? ".rating-widget" : ".discussion");
        if (!container) return;
        event.preventDefault();
        if (container.getAttribute("aria-busy") === "true") return;

        const feed = form.closest("[data-feed]");
        const submitter = event.submitter;
        const commentId = form.closest("[data-comment-id]")?.dataset.commentId;
        const body = new FormData(form);
        if (submitter?.name) body.set(submitter.name, submitter.value);
        if (!feed && form.matches(".comment-like")) {
            const page = new URLSearchParams(location.search).get("page");
            if (page) body.set("page", page);
        }

        container.querySelector(".interaction-error")?.remove();
        container.setAttribute("aria-busy", "true");
        const buttons = Array.from(container.querySelectorAll('form button[type="submit"], form button:not([type])'))
            .filter((button) => button.closest(".rating-widget, .discussion") === container);
        buttons.forEach((button) => { button.disabled = true; });

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body,
                headers: { "X-Muralium-Async": "1", Accept: "application/json" },
                credentials: "same-origin",
            });
            if (response.redirected) {
                const url = new URL(response.url);
                if (url.pathname.includes("/accounts/login/")) {
                    url.searchParams.set("next", location.pathname + location.search + location.hash);
                    location.assign(url);
                    return;
                }
            }
            if (!(response.headers.get("Content-Type") || "").includes("application/json")) {
                throw new Error("Сессия могла закончиться. Обновите страницу и войдите снова.");
            }
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Не удалось сохранить изменения.");
            if (!container.isConnected) return;

            const fragment = document.createElement("template");
            fragment.innerHTML = result.html;
            const updated = fragment.content.querySelector(isRating ? ".rating-widget" : ".discussion");
            if (!updated) throw new Error("Сервер вернул неполный ответ. Попробуйте ещё раз.");

            const draft = !isRating && !isComment ? container.querySelector(".comment-form textarea") : null;
            const activeDraft = draft && document.activeElement === draft;
            const updatedDraft = updated.querySelector(".comment-form textarea");
            if (draft && updatedDraft) {
                updatedDraft.value = draft.value;
                updatedDraft.setSelectionRange(draft.selectionStart, draft.selectionEnd);
            }

            const rating = !isRating && container.querySelector(".rating-widget");
            if (rating) updated.querySelector(".rating-widget")?.replaceWith(rating);
            container.replaceWith(updated);
            if (isRating && submitter) {
                const selected = Array.from(updated.querySelectorAll('button[name="score"]'))
                    .find((button) => button.value === submitter.value);
                selected?.focus({ preventScroll: true });
            } else if (isComment) {
                const url = new URL(location.href);
                if (url.searchParams.has("page")) {
                    url.searchParams.delete("page");
                    history.replaceState(history.state, "", url);
                }
                updatedDraft?.focus({ preventScroll: true });
            } else if (activeDraft) {
                updatedDraft?.focus({ preventScroll: true });
            } else if (commentId) {
                const sameComment = Array.from(updated.querySelectorAll("[data-comment-id]"))
                    .find((entry) => entry.dataset.commentId === commentId);
                sameComment?.querySelector(".comment-like button")?.focus({ preventScroll: true });
            }
        } catch (error) {
            if (container.isConnected) {
                showError(container, error.message || "Ошибка сети. Попробуйте ещё раз.");
            }
        } finally {
            buttons.forEach((button) => { button.disabled = false; });
            if (container.isConnected) container.removeAttribute("aria-busy");
        }
    });
})();

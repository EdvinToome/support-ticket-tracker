"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector(".form-help");
  const question = document.querySelector("#form-help-question");
  const button = document.querySelector("#form-help-ask");
  const result = document.querySelector("#form-help-result");

  button.addEventListener("click", async () => {
    if (!question.value.trim()) {
      result.textContent = "Enter a question first.";
      question.focus();
      return;
    }
    button.disabled = true;
    result.textContent = "Reading the form definitions…";
    panel.setAttribute("aria-busy", "true");
    const body = new URLSearchParams({model: panel.dataset.model, question: question.value});
    if (panel.dataset.objectId) body.set("object_id", panel.dataset.objectId);
    try {
      const response = await fetch(panel.dataset.url, {
        method: "POST",
        headers: {"X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value},
        body,
      });
      if (response.redirected || !response.headers.get("content-type").includes("application/json")) {
        result.textContent = "Assistant unavailable. Refresh the page and sign in again if needed.";
        return;
      }
      const payload = await response.json();
      result.textContent = response.ok ? payload.answer : payload.error;
    } catch {
      result.textContent = "Assistant unavailable. Check your connection and try again.";
    } finally {
      button.disabled = false;
      panel.removeAttribute("aria-busy");
    }
  });
});

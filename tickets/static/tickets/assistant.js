"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector(".form-help");
  const question = document.querySelector("#form-help-question");
  const button = document.querySelector("#form-help-ask");
  const result = document.querySelector("#form-help-result");
  const form = document.querySelector("#form-help-form");

  document.querySelector("#form-help-open").addEventListener("click", () => panel.showModal());
  document.querySelector("#form-help-close").addEventListener("click", () => panel.close());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!question.value.trim()) {
      question.setCustomValidity("Enter a question first.");
      question.reportValidity();
      question.focus();
      return;
    }
    button.disabled = true;
    question.readOnly = true;
    document.querySelector("#form-help-exchange").hidden = false;
    document.querySelector("#form-help-sent").textContent = question.value;
    result.textContent = "Reading the form definitions…";
    result.scrollIntoView({block: "nearest"});
    const body = new URLSearchParams({model: panel.dataset.model, question: question.value});
    if (panel.dataset.objectId) body.set("object_id", panel.dataset.objectId);
    try {
      const response = await fetch(panel.dataset.url, {
        method: "POST",
        headers: {"X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value},
        body,
      });
      if (response.redirected || !response.headers.get("content-type").includes("application/json")) {
        result.textContent = "Assistant unavailable. Refresh the page and sign in again if needed.";
        return;
      }
      const payload = await response.json();
      result.textContent = response.ok ? payload.answer : payload.error;
      if (response.ok) question.value = "";
    } catch {
      result.textContent = "Assistant unavailable. Check your connection and try again.";
    } finally {
      button.disabled = false;
      question.readOnly = false;
    }
  });

  question.addEventListener("input", () => question.setCustomValidity(""));
});

"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector("#form-help");
  const toggle = document.querySelector("#form-help-toggle");
  const model = document.querySelector("#form-help-model");
  const context = document.querySelector("#form-help-context");
  const messages = document.querySelector("#form-help-messages");
  const status = document.querySelector("#form-help-status");
  const form = document.querySelector("#form-help-form");
  const question = document.querySelector("#form-help-question");
  const storageKey = `form-help:${panel.dataset.userId}`;
  const saved = sessionStorage.getItem(storageKey);
  const state = saved ? JSON.parse(saved) : {
    model: model.value, objectId: "", messages: [], open: false,
  };

  function save() {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  }

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  function setBusy(busy) {
    panel.querySelectorAll("select, textarea, button").forEach((control) => {
      if (control.id !== "form-help-close") control.disabled = busy;
    });
  }

  function setOpen(open, focus = true) {
    state.open = open;
    panel.hidden = !open;
    if (open) messages.scrollTop = messages.scrollHeight;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close AI form help" : "Open AI form help");
    save();
    if (focus) (open ? question : toggle).focus();
  }

  function addMessage(message) {
    const article = document.createElement("div");
    article.className = `form-help-message form-help-message--${message.role}`;
    const label = document.createElement("strong");
    label.textContent = message.role === "user" ? "You" : "Assistant";
    const text = document.createElement("p");
    text.textContent = message.content;
    article.append(label, text);
    messages.append(article);
    messages.scrollTop = messages.scrollHeight;
  }

  function renderMessages() {
    messages.replaceChildren();
    if (!state.messages.length) {
      const welcome = document.createElement("p");
      welcome.className = "form-help-welcome";
      welcome.textContent = "Ask what a field means, which option to choose, or how to fill out this form. I use its field definitions and help text.";
      messages.append(welcome);
    }
    state.messages.forEach(addMessage);
  }

  function showContext() {
    model.value = state.model;
    context.textContent = state.objectId ? `Current record #${state.objectId} · field definitions only` : "Field definitions only";
  }

  function selectForm(name, objectId) {
    state.model = name;
    state.objectId = objectId;
    state.messages = [];
    question.value = "";
    question.setCustomValidity("");
    setStatus("");
    showContext();
    renderMessages();
    save();
  }

  async function send(text) {
    setBusy(true);
    setStatus("Checking the form definitions…");
    const message = {role: "user", content: text};
    addMessage(message);
    const body = new URLSearchParams({
      model: state.model,
      object_id: state.objectId,
      question: text,
      history: JSON.stringify(state.messages.slice(-6)),
    });
    try {
      const response = await fetch(panel.dataset.url, {
        method: "POST",
        headers: {"X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value},
        body,
      });
      if (response.redirected || !response.headers.get("content-type").includes("application/json")) {
        throw new Error("Request failed. Refresh the page and sign in again if needed.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      const answer = {role: "assistant", content: payload.answer};
      state.messages.push(message, answer);
      addMessage(answer);
      question.value = "";
      setStatus("");
      save();
    } catch (error) {
      renderMessages();
      setStatus(error.message);
    } finally {
      setBusy(false);
    }
  }

  toggle.addEventListener("click", () => setOpen(!state.open));
  document.querySelector("#form-help-close").addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
  panel.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => send(button.dataset.question));
  });
  model.addEventListener("change", () => {
    const objectId = model.value === panel.dataset.model ? panel.dataset.objectId : "";
    selectForm(model.value, objectId);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!question.value.trim()) {
      question.setCustomValidity("Enter a question first.");
      question.reportValidity();
      return;
    }
    send(question.value);
  });
  question.addEventListener("input", () => question.setCustomValidity(""));
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  if (panel.dataset.model && (
    panel.dataset.model !== state.model || panel.dataset.objectId !== state.objectId
  )) {
    selectForm(panel.dataset.model, panel.dataset.objectId);
  } else {
    showContext();
    renderMessages();
  }
  setOpen(state.open, false);
});

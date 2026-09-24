"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const panel = document.querySelector("#ticket-chat");
  const toggle = document.querySelector("#ticket-chat-toggle");
  const picker = document.querySelector("#ticket-chat-picker");
  const selection = document.querySelector("#ticket-chat-selection");
  const messages = document.querySelector("#ticket-chat-messages");
  const status = document.querySelector("#ticket-chat-status");
  const form = document.querySelector("#ticket-chat-form");
  const question = document.querySelector("#ticket-chat-question");
  const searchForm = document.querySelector("#ticket-chat-search-form");
  const search = document.querySelector("#ticket-chat-search");
  const results = document.querySelector("#ticket-chat-results");
  const actions = panel.querySelectorAll("[data-action]");
  const storageKey = `ticket-assistant:${panel.dataset.userId}`;
  const saved = sessionStorage.getItem(storageKey);
  const state = saved ? JSON.parse(saved) : {
    ticket: null, messages: [], action: "summarize", open: false,
  };

  function save() {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  }

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  function setBusy(busy) {
    panel.querySelectorAll("input, textarea, button").forEach((control) => {
      if (control.id !== "ticket-chat-close") control.disabled = busy;
    });
    actions.forEach((button) => {
      button.disabled = busy || !state.ticket;
      button.setAttribute("aria-pressed", String(button.dataset.action === state.action));
    });
    question.disabled = busy || !state.ticket;
    document.querySelector("#ticket-chat-send").disabled = busy || !state.ticket;
  }

  function setOpen(open, focus = true) {
    state.open = open;
    panel.hidden = !open;
    if (open) messages.scrollTop = messages.scrollHeight;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close ticket assistant" : "Open ticket assistant");
    save();
    if (focus) (open ? (state.ticket ? question : search) : toggle).focus();
  }

  function addMessage(message) {
    const article = document.createElement("div");
    article.className = `ticket-chat-message ticket-chat-message--${message.role}`;
    const label = document.createElement("strong");
    label.textContent = message.role === "user" ? "You" : "Assistant";
    const text = document.createElement("p");
    text.textContent = message.content;
    article.append(label, text);
    if (message.role === "assistant") {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "ticket-chat-copy";
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(message.content);
          copy.textContent = "Copied";
        } catch {
          setStatus("Copy failed. Select the reply text and copy it manually.");
        }
      });
      article.append(copy);
    }
    messages.append(article);
    messages.scrollTop = messages.scrollHeight;
  }

  function renderMessages() {
    messages.replaceChildren();
    if (!state.messages.length) {
      const welcome = document.createElement("p");
      welcome.className = "ticket-chat-welcome";
      welcome.textContent = "Get a quick summary of the issue and progress, or a customer reply you can review and copy.";
      messages.append(welcome);
    }
    state.messages.forEach(addMessage);
  }

  function selectTicket(ticket) {
    state.ticket = ticket;
    state.messages = [];
    state.action = "summarize";
    selection.textContent = `#${ticket.id} · ${ticket.subject}`;
    picker.open = false;
    results.replaceChildren();
    question.value = "";
    setStatus("");
    renderMessages();
    setBusy(false);
    save();
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    if (response.redirected || !response.headers.get("content-type").includes("application/json")) {
      throw new Error("Session expired. Refresh the page and sign in again.");
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error);
    return payload;
  }

  async function send(action, text) {
    state.action = action;
    setBusy(true);
    setStatus(action === "summarize" ? "Summarizing the ticket…" : "Drafting your reply…");
    const message = {role: "user", content: text};
    addMessage(message);
    const body = new URLSearchParams({
      ticket_id: state.ticket.id,
      action,
      question: text,
      history: JSON.stringify(state.messages.slice(-6)),
    });
    try {
      const payload = await requestJson(panel.dataset.url, {
        method: "POST",
        headers: {"X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value},
        body,
      });
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
  document.querySelector("#ticket-chat-close").addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
  actions.forEach((button) => button.addEventListener("click", () => {
    const text = button.dataset.action === "summarize" ? "Summarize this ticket." : "Draft a customer reply.";
    send(button.dataset.action, text);
  }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!question.value.trim()) {
      question.setCustomValidity("Enter a message first.");
      question.reportValidity();
      return;
    }
    send(state.action, question.value);
  });
  question.addEventListener("input", () => question.setCustomValidity(""));
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBusy(true);
    setStatus("Finding tickets…");
    results.replaceChildren();
    const params = new URLSearchParams({
      app_label: "tickets", model_name: "comment", field_name: "ticket", term: search.value,
    });
    try {
      const payload = await requestJson(`${panel.dataset.searchUrl}?${params}`);
      for (const ticket of payload.results) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = `#${ticket.id} · ${ticket.text}`;
        button.addEventListener("click", () => {
          selectTicket({id: ticket.id, subject: ticket.text});
          question.focus();
        });
        item.append(button);
        results.append(item);
      }
      setStatus(payload.results.length ? "" : "No matching tickets.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setBusy(false);
    }
  });

  if (panel.dataset.ticketId && panel.dataset.ticketId !== state.ticket?.id) {
    selectTicket({id: panel.dataset.ticketId, subject: panel.dataset.ticketSubject});
  } else {
    selection.textContent = state.ticket ? `#${state.ticket.id} · ${state.ticket.subject}` : "Choose a ticket";
    picker.open = !state.ticket;
    renderMessages();
    setBusy(false);
  }
  setOpen(state.open, false);
});

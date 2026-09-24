"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#ticket_form");
  if (!form) return;

  function showErrors(errors) {
    form.querySelectorAll(".errorlist, .errornote").forEach((element) => element.remove());
    const heading = document.createElement("p");
    heading.className = "errornote";
    heading.textContent = "Please correct the errors below. Your selected files are still attached.";
    heading.setAttribute("role", "alert");
    const list = document.createElement("ul");
    list.className = "errorlist";
    for (const error of errors) {
      for (const message of error.messages) {
        const item = document.createElement("li");
        if (error.field) {
          const link = document.createElement("a");
          link.href = `#${error.field}`;
          link.textContent = error.label;
          item.append(link, `: ${message}`);
        } else {
          item.textContent = `${error.label}: ${message}`;
        }
        list.append(item);
      }
    }
    form.prepend(heading, list);
    heading.scrollIntoView({block: "center"});
  }

  form.addEventListener("submit", async (event) => {
    const hasFiles = Array.from(form.querySelectorAll('input[type="file"]'))
      .some((input) => input.files.length > 0);
    if (!hasFiles) return;
    event.preventDefault();
    const data = new FormData(form);
    if (event.submitter?.name) data.append(event.submitter.name, event.submitter.value);
    const controls = Array.from(form.querySelectorAll("input, select, textarea, button"))
      .filter((control) => !control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    form.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(form.action, {
        method: "POST", headers: {"Accept": "application/json"}, body: data,
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      if (response.status !== 400 || !response.headers.get("content-type").includes("application/json")) {
        throw new Error(`Save failed (HTTP ${response.status}). Please try again.`);
      }
      const result = await response.json();
      showErrors(result.errors);
    } catch (error) {
      showErrors([{field: null, label: "Save", messages: [error.message]}]);
    }
    controls.forEach((control) => { control.disabled = false; });
    form.removeAttribute("aria-busy");
  });
});

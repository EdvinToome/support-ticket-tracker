"use strict";

(() => {
  let focusedField = "";
  let focusedForm = "";

  document.addEventListener("focusin", (event) => {
    const relation = event.target.closest(".related-widget-wrapper");
    const control = relation ? relation.querySelector("select[name]") : event.target;
    if (control.form && control.name && control.form.id.endsWith("_form") && ![
      "hidden", "password", "submit", "button", "reset",
    ].includes(control.type)) {
      focusedField = control.name;
      focusedForm = control.form.id;
    }
  });

  window.readFormHelpPage = (model) => {
    const form = document.getElementById(`${model}_form`);
    if (!form) return null;

    const values = {};
    for (const control of form.elements) {
      if (!control.name || control.disabled || [
        "hidden", "password", "submit", "button", "reset",
      ].includes(control.type)) continue;
      // Django's empty inline template is not an actual row.
      if (control.name.includes("__prefix__")) continue;
      if (control.type === "file") {
        values[control.name] = Array.from(control.files, (file) => file.name);
      } else if (control.tagName === "SELECT") {
        values[control.name] = Array.from(control.selectedOptions)
          .filter((option) => option.value !== "")
          .map((option) => option.value);
      } else if (control.type === "checkbox") {
        values[control.name] = control.checked ? [control.value] : [];
      } else if (control.type !== "radio" || control.checked) {
        values[control.name] = [control.value];
      }
    }
    // Link inline edits to saved rows without collecting other hidden inputs or CSRF tokens.
    for (const name of Object.keys(values)) {
      const row = name.match(/^(.*-\d+)-/);
      if (!row) continue;
      const id = form.elements.namedItem(`${row[1]}-id`);
      if (id) values[id.name] = [id.value];
    }
    const errors = Array.from(form.querySelectorAll(".errorlist li"), (error) => {
      const label = error.closest(".form-row")?.querySelector("label");
      return label ? `${label.textContent} ${error.textContent}` : error.textContent;
    });
    return {
      values,
      errors,
      active_field: focusedForm === form.id ? focusedField : "",
    };
  };
})();

(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = document.querySelector(".toast");
  const keyTableBody = document.querySelector("[data-key-table-body]");
  const modelSearch = document.getElementById("model-search");
  const clearModelButton = document.querySelector("[data-clear-model]");
  const headerFilters = document.querySelectorAll("[data-filter-key]");
  const trashToggle = document.querySelector("[data-trash-toggle]");
  const url = new URL(window.location.href);
  const rowPairs = new Map();
  let filterTimeoutId;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(showToast.timeoutId);
    showToast.timeoutId = window.setTimeout(() => {
      toast.hidden = true;
      toast.textContent = "";
    }, 2600);
  }

  function openDialog(dialog) {
    if (dialog && !dialog.open) dialog.showModal();
  }

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => openDialog(document.getElementById(button.dataset.openDialog)));
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  function rebuildRowIndex() {
    rowPairs.clear();
    if (!keyTableBody) return;
    const expansionRows = new Map(
      Array.from(keyTableBody.querySelectorAll("tr[data-expansion-for]"), (row) => [
        row.dataset.expansionFor,
        row,
      ])
    );
    keyTableBody.querySelectorAll("tr[data-record-id]").forEach((row) => {
      rowPairs.set(row.dataset.recordId, {
        row,
        expansionRow: expansionRows.get(row.dataset.recordId) || null,
      });
    });
  }

  function navigateWithParam(key, value) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
    url.searchParams.delete("page");
    window.location.assign(url.toString());
  }

  if (clearModelButton) clearModelButton.hidden = !modelSearch?.value.trim();
  if (modelSearch) {
    modelSearch.addEventListener("input", () => {
      window.clearTimeout(filterTimeoutId);
      filterTimeoutId = window.setTimeout(() => {
        navigateWithParam("model", modelSearch.value.trim());
      }, 300);
    });
  }
  clearModelButton?.addEventListener("click", () => navigateWithParam("model", ""));
  headerFilters.forEach((select) => {
    select.addEventListener("change", () => {
      if (select.dataset.filterKey === "provider" && select.value !== "openrouter") {
        url.searchParams.delete("tier");
      }
      navigateWithParam(select.dataset.filterKey, select.value);
    });
  });

  document.querySelectorAll("[data-sort-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sortKey;
      const backendKey = key === "provider" ? "typeofkey" : key === "status" ? "status_code" : key;
      const currentKey = url.searchParams.get("sort") || "id";
      const currentDirection = url.searchParams.get("direction") || "asc";
      url.searchParams.set("sort", backendKey);
      url.searchParams.set(
        "direction",
        currentKey === backendKey && currentDirection === "asc" ? "desc" : "asc"
      );
      url.searchParams.delete("page");
      window.location.assign(url.toString());
    });
  });

  async function getSecret(recordId) {
    const response = await fetch(`/keys/${recordId}/reveal`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken, "Accept": "application/json" },
      credentials: "same-origin",
    });
    const payload = await response.json();
    if (!response.ok || !payload.key) throw new Error(payload.error || "Could not reveal this key.");
    return payload.key;
  }

  async function submitFormAjax(
    formOrAction,
    suppliedFormData = null,
    { reloadAfterMutation = false } = {}
  ) {
    const action = typeof formOrAction === "string" ? formOrAction : formOrAction.action;
    const formData = suppliedFormData || new FormData(formOrAction);
    if (!formData.get("csrf_token")) formData.append("csrf_token", csrfToken);
    const headers = { "Accept": "application/json" };
    if (reloadAfterMutation) headers["X-Reload-After-Mutation"] = "1";
    const response = await fetch(action, {
      method: "POST",
      headers,
      body: formData,
      credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Request failed.");
    return payload;
  }

  function parseRowFragment(html) {
    const table = document.createElement("table");
    const body = document.createElement("tbody");
    table.append(body);
    body.innerHTML = html;
    const row = body.querySelector("tr[data-record-id]");
    if (!row) throw new Error("The server returned an invalid row.");
    return { row, expansionRow: body.querySelector(`[data-expansion-for="${row.dataset.recordId}"]`) };
  }

  function removeRow(recordId) {
    const pair = rowPairs.get(String(recordId));
    if (!pair) return;
    pair.row.remove();
    pair.expansionRow?.remove();
    rowPairs.delete(String(recordId));
  }

  function applyRowPayload(payload) {
    if (payload.removed) {
      removeRow(payload.record_id);
      return;
    }
    if (!payload.html) return;
    const pair = parseRowFragment(payload.html);
    const recordId = String(pair.row.dataset.recordId);
    const oldPair = rowPairs.get(recordId);
    if (!oldPair) return;
    oldPair.expansionRow?.remove();
    oldPair.row.replaceWith(pair.row);
    if (pair.expansionRow) pair.row.after(pair.expansionRow);
    rowPairs.set(recordId, pair);
  }

  function reconcileRows(payloads) {
    payloads.forEach(applyRowPayload);
    rebuildRowIndex();
  }

  const editDialog = document.getElementById("edit-key-dialog");
  const editForm = document.getElementById("edit-key-form");

  function populateEditDialog(button) {
    if (!editDialog || !editForm) return;
    editForm.action = `/keys/${button.dataset.editId}/edit`;
    editForm.querySelector('[data-edit-field="name"]').value = button.dataset.editName || "";
    editForm.querySelector('[data-edit-field="provider"]').value = button.dataset.editProvider || "";
    editForm.querySelector('[data-edit-field="status"]').value = button.dataset.editStatus || "";
    editForm.querySelector('[data-edit-field="models"]').value = button.dataset.editModels || "";
    editForm.querySelector('input[name="key"]').value = "";
    const checkModelSelect = editForm.querySelector('[data-edit-field="check_model"]');
    if (checkModelSelect) {
      const current = button.dataset.editCheckModel || "";
      const models = (button.dataset.editModels || "").split(",").map((model) => model.trim()).filter(Boolean);
      checkModelSelect.replaceChildren(new Option("Provider default", ""));
      models.forEach((model) => checkModelSelect.add(new Option(model, model, false, model === current)));
      if (current && !models.includes(current)) checkModelSelect.add(new Option(`${current} (not in models)`, current, true, true));
      if (!current) checkModelSelect.value = "";
    }
    editForm.querySelector('[data-edit-field="comment"]').value = button.dataset.editComment || "";
    openDialog(editDialog);
  }

  keyTableBody?.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button || !keyTableBody.contains(button)) return;
    if (button.dataset.editId) return populateEditDialog(button);
    if (button.dataset.toggleModels) {
      const expansionRow = rowPairs.get(button.dataset.toggleModels)?.expansionRow;
      if (!expansionRow) return;
      const isOpen = !expansionRow.hidden;
      expansionRow.hidden = isOpen;
      button.setAttribute("aria-expanded", String(!isOpen));
      return;
    }
    if (!button.dataset.copyId && !button.dataset.revealId) return;
    button.disabled = true;
    try {
      if (button.dataset.copyId) {
        await navigator.clipboard.writeText(await getSecret(button.dataset.copyId));
        showToast("API key copied to clipboard.");
      } else {
        const display = button.closest("tr")?.querySelector("[data-secret-display]");
        if (!display) return;
        if (button.dataset.visible === "true") {
          display.textContent = button.dataset.maskedKey;
          button.dataset.visible = "false";
          button.textContent = "Reveal";
        } else {
          display.textContent = await getSecret(button.dataset.revealId);
          button.dataset.visible = "true";
          button.textContent = "Hide";
        }
      }
    } catch (error) {
      showToast(error.message || "Action failed.");
    } finally {
      button.disabled = false;
    }
  });

  keyTableBody?.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-row-action]");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) submitButton.disabled = true;
    if (form.dataset.rowAction === "trash") {
      let includeInput = form.querySelector('input[name="include_trashed"]');
      if (!includeInput) {
        includeInput = document.createElement("input");
        includeInput.type = "hidden";
        includeInput.name = "include_trashed";
        form.append(includeInput);
      }
      includeInput.value = trashToggle?.checked ? "1" : "0";
    }
    try {
      const updateInPlace = ["refresh", "trash"].includes(form.dataset.rowAction);
      const payload = await submitFormAjax(form, null, {
        reloadAfterMutation: !updateInPlace,
      });
      if (updateInPlace) {
        reconcileRows([payload]);
        showToast(payload.message || "Saved.");
      } else {
        window.location.reload();
      }
    } catch (error) {
      showToast(error.message || "Action failed.");
    } finally {
      if (submitButton?.isConnected) submitButton.disabled = false;
    }
  });

  const addKeyDialog = document.getElementById("add-key-dialog");
  const addKeyForm = addKeyDialog?.querySelector("form");
  addKeyForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await submitFormAjax(addKeyForm, null, { reloadAfterMutation: true });
      window.location.reload();
    } catch (error) {
      showToast(error.message || "Could not add key.");
    }
  });

  editForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await submitFormAjax(editForm, null, { reloadAfterMutation: true });
      window.location.reload();
    } catch (error) {
      showToast(error.message || "Could not update key.");
    }
  });

  document.querySelectorAll("form[data-confirm][data-async-skip]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll("[data-auto-submit]").forEach((control) => {
    control.addEventListener("change", () => control.form?.requestSubmit());
  });

  async function revealInOrder(rows, concurrency = 4) {
    const secrets = new Array(rows.length);
    let nextIndex = 0;
    async function worker() {
      while (nextIndex < rows.length) {
        const index = nextIndex;
        nextIndex += 1;
        secrets[index] = await getSecret(rows[index].dataset.recordId);
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, rows.length) }, worker));
    return secrets;
  }

  document.querySelector("[data-copy-bulk]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const rows = Array.from(rowPairs.values(), (pair) => pair.row);
    if (!rows.length) return showToast("No keys in view to copy.");
    button.disabled = true;
    try {
      const secrets = await revealInOrder(rows);
      await navigator.clipboard.writeText(secrets.join("\n"));
      showToast(`Copied ${secrets.length} ${secrets.length === 1 ? "key" : "keys"} to clipboard.`);
    } catch (error) {
      showToast(error.message || "Bulk copy failed.");
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("[data-copy-provider]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const provider = button.dataset.copyProvider;
    if (!provider) return showToast("Select a provider first.");
    button.disabled = true;
    try {
      const formData = new FormData();
      formData.append("csrf_token", csrfToken);
      formData.append("provider", provider);
      const payload = await submitFormAjax("/keys/copy-provider", formData);
      if (!Array.isArray(payload.keys)) throw new Error("The server returned invalid key data.");
      if (!payload.keys.length) return showToast(`No active ${provider} keys to copy.`);
      await navigator.clipboard.writeText(payload.keys.join("\n"));
      showToast(`Copied ${payload.count} ${provider} ${payload.count === 1 ? "key" : "keys"}.`);
    } catch (error) {
      showToast(error.message || "Provider copy failed.");
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("[data-refresh-bulk]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const ids = Array.from(rowPairs.keys());
    if (!ids.length) return showToast("No keys in view to refresh.");
    button.disabled = true;
    try {
      const formData = new FormData();
      formData.append("csrf_token", csrfToken);
      formData.append("record_ids", ids.join(","));
      const payload = await submitFormAjax("/refresh-all", formData);
      reconcileRows(payload.rows);
      showToast(payload.message);
    } catch (error) {
      showToast(error.message || "Refresh failed.");
    } finally {
      button.disabled = false;
    }
  });

  trashToggle?.addEventListener("change", () => {
    navigateWithParam("trashed", trashToggle.checked ? "1" : "");
  });

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });

  rebuildRowIndex();
})();

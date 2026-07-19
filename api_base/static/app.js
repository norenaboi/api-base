(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = document.querySelector(".toast");
  const keyTableBody = document.querySelector("[data-key-table-body]");
  const modelSearch = document.getElementById("model-search");
  const clearModelButton = document.querySelector("[data-clear-model]");
  const headerFilters = document.querySelectorAll("[data-filter-key]");
  const recordCount = document.querySelector(".record-count strong");
  const trashToggle = document.querySelector("[data-trash-toggle]");
  const url = new URL(window.location.href);
  const rowPairs = new Map();
  const textSorter = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  let activeSort = { key: "", direction: "asc" };
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
    updateRecordCount();
  }

  function updateRecordCount() {
    if (recordCount) recordCount.textContent = String(rowPairs.size);
    if (!keyTableBody) return;
    const emptyRow = keyTableBody.querySelector("[data-empty-row]");
    if (rowPairs.size && emptyRow) emptyRow.remove();
    if (!rowPairs.size && !emptyRow) {
      keyTableBody.insertAdjacentHTML(
        "beforeend",
        '<tr data-empty-row><td colspan="7"><div class="empty-state"><span class="empty-icon" aria-hidden="true">◇</span><h3>No keys in this view</h3><p>Add a key or adjust the current filters.</p></div></td></tr>'
      );
    }
  }

  function updateUrlParam(key, value) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
    window.history.replaceState({}, "", url);
  }

  function matchesStatusFilter(rowValue, filterValue) {
    if (filterValue === "") return true;
    if (filterValue === "unchecked") return rowValue === "";
    const code = Number(rowValue);
    if (Number.isNaN(code)) return false;
    if (filterValue === "ok") return code >= 200 && code < 300;
    if (filterValue === "rate") return code === 429;
    if (filterValue === "error") return code !== 429 && (code < 200 || code >= 300);
    return true;
  }

  function applyFilters() {
    const modelTerm = modelSearch ? modelSearch.value.trim().toLowerCase() : "";
    const providerFilter = document.querySelector('[data-filter-key="provider"]')?.value || "";
    const statusFilter = document.querySelector('[data-filter-key="status"]')?.value || "";
    if (clearModelButton) clearModelButton.hidden = modelTerm === "";

    rowPairs.forEach(({ row, expansionRow }) => {
      const matchesModel = modelTerm === "" || (row.dataset.models || "").toLowerCase().includes(modelTerm);
      const matchesProvider = providerFilter === "" || (row.dataset.sortProvider || "").toLowerCase() === providerFilter;
      const visible = matchesModel && matchesProvider && matchesStatusFilter(row.dataset.sortStatus || "", statusFilter);
      row.hidden = !visible;
      if (expansionRow && !visible) expansionRow.hidden = true;
    });
  }

  function initFiltersFromUrl() {
    if (modelSearch) modelSearch.value = url.searchParams.get("model") || "";
    headerFilters.forEach((select) => {
      select.value = url.searchParams.get(select.dataset.filterKey) || "";
    });
    applyFilters();
  }

  if (modelSearch) {
    modelSearch.addEventListener("input", () => {
      window.clearTimeout(filterTimeoutId);
      filterTimeoutId = window.setTimeout(() => {
        updateUrlParam("model", modelSearch.value.trim());
        applyFilters();
      }, 150);
    });
  }
  clearModelButton?.addEventListener("click", () => {
    if (modelSearch) modelSearch.value = "";
    updateUrlParam("model", "");
    applyFilters();
    modelSearch?.focus();
  });
  headerFilters.forEach((select) => {
    select.addEventListener("change", () => {
      updateUrlParam(select.dataset.filterKey, select.value);
      applyFilters();
    });
  });

  function sortValue(row, key) {
    return row.dataset[`sort${key.charAt(0).toUpperCase()}${key.slice(1)}`] ?? "";
  }

  function sortCurrentRows() {
    if (!keyTableBody || !activeSort.key) return;
    const multiplier = activeSort.direction === "asc" ? 1 : -1;
    const pairs = Array.from(rowPairs.values());
    pairs.sort(({ row: rowA }, { row: rowB }) => {
      const valueA = sortValue(rowA, activeSort.key);
      const valueB = sortValue(rowB, activeSort.key);
      if (activeSort.key === "status") {
        if (valueA === "" && valueB === "") return 0;
        if (valueA === "") return 1;
        if (valueB === "") return -1;
        return (Number(valueA) - Number(valueB)) * multiplier;
      }
      return textSorter.compare(valueA, valueB) * multiplier;
    });
    for (const { row, expansionRow } of pairs) {
      keyTableBody.append(row);
      if (expansionRow) keyTableBody.append(expansionRow);
    }
  }

  document.querySelectorAll("[data-sort-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sortKey;
      const direction = activeSort.key === key && activeSort.direction === "asc" ? "desc" : "asc";
      activeSort = { key, direction };
      sortCurrentRows();
      document.querySelectorAll("[data-sort-header]").forEach((header) => {
        const isActive = header.dataset.sortHeader === key;
        header.setAttribute("aria-sort", isActive ? (direction === "asc" ? "ascending" : "descending") : "none");
        const indicator = header.querySelector("[data-sort-indicator]");
        if (indicator) indicator.textContent = isActive ? (direction === "asc" ? "↑" : "↓") : "↕";
      });
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

  async function submitFormAjax(formOrAction, suppliedFormData = null) {
    const action = typeof formOrAction === "string" ? formOrAction : formOrAction.action;
    const formData = suppliedFormData || new FormData(formOrAction);
    if (!formData.get("csrf_token")) formData.append("csrf_token", csrfToken);
    const response = await fetch(action, {
      method: "POST",
      headers: { "Accept": "application/json" },
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
    if (oldPair) {
      oldPair.expansionRow?.remove();
      oldPair.row.replaceWith(pair.row);
      if (pair.expansionRow) pair.row.after(pair.expansionRow);
    } else {
      keyTableBody?.append(pair.row);
      if (pair.expansionRow) keyTableBody?.append(pair.expansionRow);
    }
    rowPairs.set(recordId, pair);
  }

  function reconcileRows(payloads) {
    payloads.forEach(applyRowPayload);
    updateRecordCount();
    applyFilters();
    sortCurrentRows();
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
      const payload = await submitFormAjax(form);
      reconcileRows([payload]);
      showToast(payload.message || "Saved.");
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
      const payload = await submitFormAjax(addKeyForm);
      reconcileRows([payload]);
      addKeyDialog.close();
      addKeyForm.reset();
      showToast(payload.message || "API key added.");
    } catch (error) {
      showToast(error.message || "Could not add key.");
    }
  });

  editForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = await submitFormAjax(editForm);
      reconcileRows([payload]);
      editDialog.close();
      showToast(payload.message || "API key updated.");
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

  document.querySelector("[data-copy-bulk]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const rows = Array.from(rowPairs.values()).map((pair) => pair.row).filter((row) => !row.hidden);
    if (!rows.length) return showToast("No keys in view to copy.");
    button.disabled = true;
    try {
      const secrets = await Promise.all(rows.map((row) => getSecret(row.dataset.recordId)));
      await navigator.clipboard.writeText(secrets.join("\n"));
      showToast(`Copied ${secrets.length} ${secrets.length === 1 ? "key" : "keys"} to clipboard.`);
    } catch (error) {
      showToast(error.message || "Bulk copy failed.");
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("[data-refresh-bulk]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const ids = Array.from(rowPairs.entries()).filter(([, pair]) => !pair.row.hidden).map(([id]) => id);
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

  async function reloadTableBody() {
    if (!keyTableBody) return;
    const response = await fetch(url.toString(), { headers: { "Accept": "text/html" }, credentials: "same-origin" });
    if (!response.ok) throw new Error("Could not change the trash view.");
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    const newBody = doc.querySelector("[data-key-table-body]");
    if (newBody) keyTableBody.replaceChildren(...newBody.childNodes);
    rebuildRowIndex();
    applyFilters();
  }

  trashToggle?.addEventListener("change", async () => {
    updateUrlParam("trashed", trashToggle.checked ? "1" : "");
    try {
      await reloadTableBody();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });

  rebuildRowIndex();
  initFiltersFromUrl();
})();

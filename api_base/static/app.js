(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = document.querySelector(".toast");

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

  const modelFilter = document.querySelector("[data-model-filter]");
  const modelSearch = document.getElementById("model-search");
  const clearModelButton = document.querySelector("[data-clear-model]");
  const headerFilters = document.querySelectorAll("[data-filter-key]");
  const keyTableBody = document.querySelector("[data-key-table-body]");
  const url = new URL(window.location.href);

  function updateUrlParam(key, value) {
    if (value) {
      url.searchParams.set(key, value);
    } else {
      url.searchParams.delete(key);
    }
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
    if (!keyTableBody) return;
    const modelTerm = modelSearch ? modelSearch.value.trim().toLowerCase() : "";
    const providerFilter = document.querySelector('[data-filter-key="provider"]')?.value || "";
    const statusFilter = document.querySelector('[data-filter-key="status"]')?.value || "";
    if (clearModelButton) clearModelButton.hidden = modelTerm === "";

    keyTableBody.querySelectorAll("tr[data-record-id]").forEach((row) => {
      const models = (row.dataset.models || "").toLowerCase();
      const provider = (row.dataset.sortProvider || "").toLowerCase();
      const status = row.dataset.sortStatus || "";
      const matchesModel = modelTerm === "" || models.includes(modelTerm);
      const matchesProvider = providerFilter === "" || provider === providerFilter;
      const matchesStatus = matchesStatusFilter(status, statusFilter);
      const visible = matchesModel && matchesProvider && matchesStatus;
      row.hidden = !visible;
      const expansionRow = keyTableBody.querySelector(
        `[data-expansion-for="${row.dataset.recordId}"]`
      );
      if (expansionRow && !visible) expansionRow.hidden = true;
    });
  }

  function initFiltersFromUrl() {
    if (modelSearch) {
      modelSearch.value = url.searchParams.get("model") || "";
    }
    headerFilters.forEach((select) => {
      select.value = url.searchParams.get(select.dataset.filterKey) || "";
    });
    applyFilters();
  }

  if (modelSearch) {
    modelSearch.addEventListener("input", () => {
      updateUrlParam("model", modelSearch.value.trim());
      applyFilters();
    });
  }

  if (clearModelButton) {
    clearModelButton.addEventListener("click", () => {
      if (modelSearch) modelSearch.value = "";
      updateUrlParam("model", "");
      applyFilters();
      if (modelSearch) modelSearch.focus();
    });
  }

  headerFilters.forEach((select) => {
    select.addEventListener("change", () => {
      updateUrlParam(select.dataset.filterKey, select.value);
      applyFilters();
    });
  });

  initFiltersFromUrl();

  document.querySelectorAll("[data-auto-submit]").forEach((control) => {
    control.addEventListener("change", () => control.form?.requestSubmit());
  });

  const sortButtons = document.querySelectorAll("[data-sort-key]");
  const textSorter = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  let activeSort = { key: "", direction: "asc" };

  function sortValue(row, key) {
    return row.dataset[`sort${key.charAt(0).toUpperCase()}${key.slice(1)}`] ?? "";
  }

  sortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (!keyTableBody) return;
      const key = button.dataset.sortKey;
      const direction = activeSort.key === key && activeSort.direction === "asc" ? "desc" : "asc";
      activeSort = { key, direction };
      const multiplier = direction === "asc" ? 1 : -1;
      const rows = Array.from(keyTableBody.querySelectorAll("tr[data-record-id]"));

      rows.sort((rowA, rowB) => {
        const valueA = sortValue(rowA, key);
        const valueB = sortValue(rowB, key);
        if (key === "status") {
          if (valueA === "" && valueB === "") return 0;
          if (valueA === "") return 1;
          if (valueB === "") return -1;
          return (Number(valueA) - Number(valueB)) * multiplier;
        }
        return textSorter.compare(valueA, valueB) * multiplier;
      });

      // Re-append each data row followed by its expansion row (if any) to keep them paired.
      for (const row of rows) {
        const expansionRow = keyTableBody.querySelector(
          `[data-expansion-for="${row.dataset.recordId}"]`
        );
        keyTableBody.append(row);
        if (expansionRow) keyTableBody.append(expansionRow);
      }

      document.querySelectorAll("[data-sort-header]").forEach((header) => {
        const isActive = header.dataset.sortHeader === key;
        header.setAttribute("aria-sort", isActive ? (direction === "asc" ? "ascending" : "descending") : "none");
        const indicator = header.querySelector("[data-sort-indicator]");
        if (indicator) indicator.textContent = isActive ? (direction === "asc" ? "↑" : "↓") : "↕";
      });
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
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

  const editDialog = document.getElementById("edit-key-dialog");
  const editForm = document.getElementById("edit-key-form");

  async function refreshTableBody(fetchUrl) {
    if (!keyTableBody) return;
    const response = await fetch(fetchUrl || window.location.href, {
      method: "GET",
      headers: { "Accept": "text/html" },
      credentials: "same-origin",
    });
    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const newBody = doc.querySelector("[data-key-table-body]");
    if (newBody) {
      keyTableBody.innerHTML = newBody.innerHTML;
      attachRowActionListeners();
      initFiltersFromUrl();
    }
  }

  function attachRowActionListeners() {
    document.querySelectorAll("[data-copy-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const secret = await getSecret(button.dataset.copyId);
          await navigator.clipboard.writeText(secret);
          showToast("API key copied to clipboard.");
        } catch (error) {
          showToast(error.message || "Copy failed.");
        } finally {
          button.disabled = false;
        }
      });
    });

    document.querySelectorAll("[data-reveal-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const row = button.closest("tr");
        const display = row?.querySelector("[data-secret-display]");
        if (!display) return;
        if (button.dataset.visible === "true") {
          display.textContent = button.dataset.maskedKey;
          button.dataset.visible = "false";
          button.textContent = "Reveal";
          return;
        }
        button.disabled = true;
        try {
          display.textContent = await getSecret(button.dataset.revealId);
          button.dataset.visible = "true";
          button.textContent = "Hide";
        } catch (error) {
          showToast(error.message || "Reveal failed.");
        } finally {
          button.disabled = false;
        }
      });
    });

    document.querySelectorAll("[data-toggle-models]").forEach((button) => {
      button.addEventListener("click", () => {
        const recordId = button.dataset.toggleModels;
        const expansionRow = keyTableBody?.querySelector(
          `[data-expansion-for="${recordId}"]`
        );
        if (!expansionRow) return;
        const isOpen = !expansionRow.hidden;
        expansionRow.hidden = isOpen;
        button.setAttribute("aria-expanded", String(!isOpen));
      });
    });

    document.querySelectorAll("[data-edit-id]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!editDialog || !editForm) return;
        editForm.action = `/keys/${button.dataset.editId}/edit`;
        editForm.querySelector('[data-edit-field="name"]').value = button.dataset.editName || "";
        editForm.querySelector('[data-edit-field="provider"]').value = button.dataset.editProvider || "";
        editForm.querySelector('[data-edit-field="status"]').value = button.dataset.editStatus || "";
        editForm.querySelector('[data-edit-field="models"]').value = button.dataset.editModels || "";
        editForm.querySelector('input[name="key"]').value = "";

        // Populate check-model dropdown from the key's stored models
        const checkModelSelect = editForm.querySelector('[data-edit-field="check_model"]');
        if (checkModelSelect) {
          const currentCheckModel = button.dataset.editCheckModel || "";
          const models = (button.dataset.editModels || "").split(",").map(m => m.trim()).filter(Boolean);
          checkModelSelect.innerHTML = '<option value="">Provider default</option>';
          for (const model of models) {
            const option = document.createElement("option");
            option.value = model;
            option.textContent = model;
            if (model === currentCheckModel) option.selected = true;
            checkModelSelect.appendChild(option);
          }
          if (![...checkModelSelect.options].some(o => o.value === currentCheckModel) && currentCheckModel) {
            const customOption = document.createElement("option");
            customOption.value = currentCheckModel;
            customOption.textContent = currentCheckModel + " (not in models)";
            customOption.selected = true;
            checkModelSelect.appendChild(customOption);
          }
          if (!currentCheckModel) checkModelSelect.value = "";
        }

        editForm.querySelector('[data-edit-field="comment"]').value = button.dataset.editComment || "";
        openDialog(editDialog);
      });
    });

    document.querySelectorAll("form[data-confirm]:not([data-async-skip])").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!window.confirm(form.dataset.confirm)) return;
        const formData = new FormData(form);
        formData.append("csrf_token", csrfToken);
        try {
          const response = await fetch(form.action, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
          });
          if (!response.ok) throw new Error("Delete failed.");
          showToast("API key deleted.");
          await refreshTableBody();
        } catch (error) {
          showToast(error.message || "Delete failed.");
        }
      });
    });

    document.querySelectorAll('form[action$="/refresh"]').forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(form);
        formData.append("csrf_token", csrfToken);
        try {
          const response = await fetch(form.action, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
          });
          if (!response.ok) throw new Error("Refresh failed.");
          showToast("API key refreshed.");
          await refreshTableBody();
        } catch (error) {
          showToast(error.message || "Refresh failed.");
        }
      });
    });

    document.querySelectorAll("form[data-async-trash]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const formData = new FormData(form);
        if (!formData.get("csrf_token")) formData.append("csrf_token", csrfToken);
        const isRestore = formData.get("trashed") === "0";
        try {
          const response = await fetch(form.action, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
          });
          if (!response.ok) throw new Error("Trash toggle failed.");
          showToast(isRestore ? "API key restored." : "API key moved to trash.");
          await refreshTableBody();
        } catch (error) {
          showToast(error.message || "Trash toggle failed.");
        }
      });
    });
  }

  async function submitFormAjax(form) {
    const formData = new FormData(form);
    if (!formData.get("csrf_token")) {
      formData.append("csrf_token", csrfToken);
    }
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || "Save failed.");
    }
  }

  const addKeyDialog = document.getElementById("add-key-dialog");
  const addKeyForm = addKeyDialog?.querySelector("form");
  if (addKeyForm) {
    addKeyForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitFormAjax(addKeyForm);
        addKeyDialog.close();
        addKeyForm.reset();
        showToast("API key added.");
        await refreshTableBody();
      } catch (error) {
        showToast(error.message || "Could not add key.");
      }
    });
  }

  if (editForm) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitFormAjax(editForm);
        editDialog.close();
        showToast("API key updated.");
        await refreshTableBody();
      } catch (error) {
        showToast(error.message || "Could not update key.");
      }
    });
  }

  attachRowActionListeners();

  const copyBulkButton = document.querySelector("[data-copy-bulk]");
  if (copyBulkButton) {
    copyBulkButton.addEventListener("click", async () => {
      if (!keyTableBody) return;
      const visibleRows = Array.from(
        keyTableBody.querySelectorAll("tr[data-record-id]")
      ).filter((row) => !row.hidden);
      if (visibleRows.length === 0) {
        showToast("No keys in view to copy.");
        return;
      }
      copyBulkButton.disabled = true;
      try {
        const secrets = [];
        for (const row of visibleRows) {
          secrets.push(await getSecret(row.dataset.recordId));
        }
        await navigator.clipboard.writeText(secrets.join("\n"));
        const noun = secrets.length === 1 ? "key" : "keys";
        showToast(`Copied ${secrets.length} ${noun} to clipboard.`);
      } catch (error) {
        showToast(error.message || "Bulk copy failed.");
      } finally {
        copyBulkButton.disabled = false;
      }
    });
  }

  const refreshBulkButton = document.querySelector("[data-refresh-bulk]");
  if (refreshBulkButton) {
    refreshBulkButton.addEventListener("click", async () => {
      if (!keyTableBody) return;
      const visibleRows = Array.from(
        keyTableBody.querySelectorAll("tr[data-record-id]")
      ).filter((row) => !row.hidden);
      if (visibleRows.length === 0) {
        showToast("No keys in view to refresh.");
        return;
      }
      refreshBulkButton.disabled = true;
      try {
        const formData = new FormData();
        formData.append("csrf_token", csrfToken);
        formData.append(
          "record_ids",
          visibleRows.map((row) => row.dataset.recordId).join(",")
        );
        const response = await fetch("/refresh-all", {
          method: "POST",
          body: formData,
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error("Refresh failed.");
        const noun = visibleRows.length === 1 ? "key" : "keys";
        showToast(`Refreshed ${visibleRows.length} ${noun} in view.`);
        await refreshTableBody();
      } catch (error) {
        showToast(error.message || "Refresh failed.");
      } finally {
        refreshBulkButton.disabled = false;
      }
    });
  }

  const trashToggle = document.querySelector("[data-trash-toggle]");
  if (trashToggle) {
    trashToggle.addEventListener("change", async () => {
      if (trashToggle.checked) {
        url.searchParams.set("trashed", "1");
      } else {
        url.searchParams.delete("trashed");
      }
      window.history.replaceState({}, "", url);
      await refreshTableBody(url.toString());
    });
  }

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });
})();

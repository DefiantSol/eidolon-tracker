const state = {
  view: "shopping",
  search: "",
  progressFilter: "incomplete",
  data: null,
};

const content = document.querySelector("#content");
const stats = document.querySelector("#stats");
const profileSelect = document.querySelector("#profileSelect");
const profileNew = document.querySelector("#profileNew");
const profileRename = document.querySelector("#profileRename");
const search = document.querySelector("#search");
const progressFilter = document.querySelector("#progressFilter");
const themeToggle = document.querySelector("#themeToggle");
const settingsToggle = document.querySelector("#settingsToggle");
const settingsDialog = document.querySelector("#settingsDialog");
const quickSetupOpen = document.querySelector("#quickSetupOpen");
const quickSetupDialog = document.querySelector("#quickSetupDialog");
const quickSetupSearch = document.querySelector("#quickSetupSearch");
const quickSetupList = document.querySelector("#quickSetupList");
const quickSetupApply = document.querySelector("#quickSetupApply");
const backupDownload = document.querySelector("#backupDownload");
const backupRestore = document.querySelector("#backupRestore");
const backupRestoreInput = document.querySelector("#backupRestoreInput");
const appShutdown = document.querySelector("#appShutdown");
const confirmDialog = document.querySelector("#confirmDialog");
const confirmMessage = document.querySelector("#confirmMessage");
const wishTierLabels = ["I", "II", "III", "IV", "V", "VI", "Done"];

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
  themeToggle.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
}

async function load() {
  const response = await fetch("/api/state");
  state.data = await response.json();
  render();
}

async function post(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  state.data = await response.json();
  render();
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function matchesItem(item) {
  const needle = normalize(state.search);
  if (!needle) return true;
  return [item.eidolon_name, item.wish_group_effective, item.wish_group, item.item, item.quantity_text, item.how_to_obtain]
    .map(normalize)
    .some((value) => value.includes(needle));
}

function matchesEidolon(eidolon, items) {
  const needle = normalize(state.search);
  if (!needle) return true;
  if (normalize(eidolon.name).includes(needle)) return true;
  return items.some(matchesItem);
}

function itemsFor(eidolonId) {
  return state.data.items.filter((item) => item.eidolon_id === eidolonId);
}

function eidolonFor(item) {
  return state.data.eidolons.find((eidolon) => eidolon.id === item.eidolon_id);
}

function isActiveWishItem(item) {
  const eidolon = eidolonFor(item);
  if (!eidolon || !eidolon.owned || eidolon.completed || item.completed) return false;
  return Number(item.wish_tier) === Number(eidolon.current_wish_tier || 0);
}

function matchesProgressComplete(isComplete) {
  if (state.progressFilter === "active") return !isComplete;
  if (state.progressFilter === "all") return true;
  if (state.progressFilter === "complete") return isComplete;
  return !isComplete;
}

function filteredWishItemsFor(eidolonId) {
  return itemsFor(eidolonId).filter((item) => {
    if (state.progressFilter === "active" && !isActiveWishItem(item)) return false;
    return matchesProgressComplete(Boolean(item.completed)) && matchesItem(item);
  });
}

function emptyForView(viewName) {
  if (state.progressFilter === "active") return `No active ${viewName} match that search.`;
  if (state.progressFilter === "complete") return `No completed ${viewName} match that search.`;
  if (state.progressFilter === "all") return `No ${viewName} match that search.`;
  return `No incomplete ${viewName} match that search.`;
}

function renderStats() {
  const summary = state.data.summary;
  stats.innerHTML = [
    statGroup("Eidolon", [
      stat(summary.eidolons, "Total"),
      stat(summary.owned, "Owned"),
      stat(summary.completed, "Completed"),
    ]),
    statGroup("Wishes", [
      stat(summary.wishes_total, "Total"),
      stat(summary.wishes_active, "Active"),
      stat(summary.wishes_completed, "Completed"),
    ]),
    statGroup("Items", [
      stat(summary.items_total, "Total"),
      stat(summary.items_active, "Active"),
      stat(summary.items_completed, "Completed"),
    ]),
  ].join("");
}

function renderProfiles() {
  profileSelect.innerHTML = state.data.profiles
    .map(
      (profile) =>
        `<option value="${profile.id}" ${profile.id === state.data.current_profile_id ? "selected" : ""}>${escapeHtml(profile.name)}</option>`,
    )
    .join("");
}

function statGroup(label, statsHtml) {
  return `
    <section class="stat-group" aria-label="${escapeHtml(label)} tracking">
      <h2>${escapeHtml(label)}</h2>
      <div class="stat-row">${statsHtml.join("")}</div>
    </section>
  `;
}

function stat(value, label) {
  return `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`;
}

function renderSettingsState() {
  const summary = state.data.summary;
  const allOwned = summary.owned === summary.eidolons;
  const starterOnly =
    summary.owned === 6 &&
    state.data.eidolons.every((eidolon) => Boolean(eidolon.owned) === Boolean(eidolon.is_starter));
  const allComplete = summary.items_completed === summary.items_total;
  const noneComplete = summary.items_completed === 0 && summary.completed === 0;
  document.querySelectorAll("[data-setting-action]").forEach((button) => {
    const action = button.dataset.settingAction;
    const active =
      (action === "own_all" && allOwned) ||
      (action === "starter_only" && starterOnly) ||
      (action === "complete_all" && allComplete) ||
      (action === "clear_wishes" && noneComplete);
    button.classList.toggle("active", active);
  });
}

function renderQuickSetup() {
  quickSetupList.innerHTML = state.data.eidolons.map(quickSetupRow).join("");
}

function quickSetupRow(eidolon) {
  const owned = Boolean(eidolon.owned);
  const currentTier = owned ? (eidolon.completed ? "completed" : Number(eidolon.current_wish_tier || 1)) : 0;
  return `
    <div class="quick-setup-row" data-eidolon-id="${eidolon.id}">
      <label class="quick-setup-owned">
        <input type="checkbox" ${owned ? "checked" : ""}>
        <span>${escapeHtml(eidolon.name)}</span>
      </label>
      <div class="quick-setup-tiers" role="group" aria-label="${escapeHtml(eidolon.name)} wish tier">
        ${wishTierLabels.map((label, index) => quickSetupTierButton(label, index + 1, currentTier, owned)).join("")}
      </div>
    </div>
  `;
}

function filterQuickSetupRows() {
  const needle = normalize(quickSetupSearch.value);
  quickSetupList.querySelectorAll(".quick-setup-row").forEach((row) => {
    const name = normalize(row.querySelector(".quick-setup-owned span").textContent);
    row.classList.toggle("filtered-out", Boolean(needle) && !name.includes(needle));
  });
}

function quickSetupTierButton(label, value, currentTier, owned) {
  const tierValue = label === "Done" ? "completed" : String(value);
  return `
    <button
      type="button"
      class="${String(currentTier) === tierValue ? "active" : ""}"
      data-tier="${tierValue}"
      ${owned ? "" : "disabled"}
    >${label}</button>
  `;
}

function quickSetupTooltip(row, tierValue) {
  const eidolonId = Number(row.dataset.eidolonId);
  if (tierValue === "completed") {
    return {
      title: "Done",
      items: ["All wish tiers complete."],
    };
  }
  const tierNumber = Number(tierValue);
  const items = state.data.items
    .filter((item) => item.eidolon_id === eidolonId && Number(item.wish_tier) === tierNumber)
    .map((item) => item.item);
  return {
    title: `Wish ${wishTierLabels[tierNumber - 1]}`,
    items: items.length ? items : ["No items listed for this tier."],
  };
}

function showQuickSetupTooltip(button) {
  const row = button.closest(".quick-setup-row");
  const tooltipData = quickSetupTooltip(row, button.dataset.tier);
  button.setAttribute(
    "data-tooltip",
    `${tooltipData.title}\n${tooltipData.items.map((item) => `- ${item}`).join("\n")}`,
  );
}

function render() {
  if (!state.data) return;
  renderProfiles();
  renderStats();
  renderSettingsState();
  document.querySelectorAll(".tab[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });

  if (state.view === "eidolons") renderEidolons();
  if (state.view === "shopping") renderShopping();
  if (state.view === "items") renderConsolidatedItems();
}

function renderEidolons() {
  const blocks = state.data.eidolons
    .filter((eidolon) => {
      if (state.progressFilter !== "active") return matchesProgressComplete(Boolean(eidolon.completed));
      return Boolean(eidolon.owned) && !eidolon.completed && Number(eidolon.current_wish_tier || 0) > 0;
    })
    .filter((eidolon) => matchesEidolon(eidolon, filteredWishItemsFor(eidolon.id)))
    .map((eidolon) => eidolonBlock(eidolon, filteredWishItemsFor(eidolon.id), { collapsed: true, showDone: true }));
  content.innerHTML = blocks.length ? blocks.join("") : empty(emptyForView("Eidolons"));
}

function renderShopping() {
  const blocks = state.data.eidolons
    .filter((eidolon) => eidolon.owned)
    .map((eidolon) => [eidolon, filteredWishItemsFor(eidolon.id)])
    .filter(([eidolon, items]) => items.length && matchesEidolon(eidolon, items))
    .map(([eidolon, items]) => eidolonBlock(eidolon, items, { shopping: true }));
  content.innerHTML = blocks.length ? blocks.join("") : empty(emptyForView("wishes"));
}

function renderConsolidatedItems() {
  const groups = consolidatedItems()
    .filter((group) => matchesProgressComplete(group.remainingQty === 0))
    .filter((group) => matchesConsolidatedGroup(group))
    .sort((a, b) => a.item.localeCompare(b.item));
  content.innerHTML = groups.length
    ? `
      <section class="consolidated">
        <div class="consolidated-head">
          <div>Wish Item</div>
          <div>Total Quantity</div>
          <div>Eidolons</div>
        </div>
        ${groups.map(consolidatedRow).join("")}
      </section>
    `
    : empty(emptyForView("items"));
}

function consolidatedItems() {
  const groups = new Map();
  state.data.items.forEach((item) => {
    if (state.progressFilter === "active" && !isActiveWishItem(item)) return;
    const key = normalize(item.item);
    if (!groups.has(key)) {
      groups.set(key, {
        item: item.item,
        image_url: item.image_url,
        detail_url: item.detail_url,
        totalQty: 0,
        remainingQty: 0,
        entries: [],
      });
    }
    const group = groups.get(key);
    const quantity = Number(item.quantity_value || item.quantity_text || 1) || 1;
    group.totalQty += quantity;
    if (!item.completed) group.remainingQty += quantity;
    if (!group.image_url && item.image_url) group.image_url = item.image_url;
    if (!group.detail_url && item.detail_url) group.detail_url = item.detail_url;
    group.entries.push({
      eidolon: item.eidolon_name,
      quantity,
      completed: Boolean(item.completed),
      owned: Boolean(item.eidolon_owned),
    });
  });
  return [...groups.values()];
}

function matchesConsolidatedGroup(group) {
  const needle = normalize(state.search);
  if (!needle) return true;
  if (normalize(group.item).includes(needle)) return true;
  return group.entries.some((entry) => normalize(entry.eidolon).includes(needle));
}

function consolidatedRow(group) {
  const entries = [...group.entries].sort((a, b) => {
    if (a.completed !== b.completed) return a.completed ? 1 : -1;
    if (a.owned !== b.owned) return a.owned ? -1 : 1;
    return a.eidolon.localeCompare(b.eidolon);
  });
  return `
    <div class="consolidated-row ${group.remainingQty === 0 ? "complete" : ""}">
      <div class="consolidated-item">
        ${group.image_url ? `<img class="item-icon" src="${escapeHtml(group.image_url)}" alt="">` : `<span class="item-icon placeholder"></span>`}
        <strong>${group.detail_url ? externalLink(group.item, group.detail_url) : escapeHtml(group.item)}</strong>
      </div>
      <div class="consolidated-qty">${formatQty(group.remainingQty)} / ${formatQty(group.totalQty)}</div>
      <div class="eidolon-chips">
        ${entries.map(entryChip).join("")}
      </div>
    </div>
  `;
}

function entryChip(entry) {
  const classes = ["eidolon-chip"];
  if (entry.completed) classes.push("complete");
  if (entry.owned) classes.push("owned");
  return `<span class="${classes.join(" ")}">${escapeHtml(entry.eidolon)} <strong>(${formatQty(entry.quantity)})</strong></span>`;
}

function formatQty(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

function eidolonBlock(eidolon, items, options = {}) {
  const completedWishes = eidolon.completed_wish_count || 0;
  const totalWishes = eidolon.wish_count || 0;
  const completedItems = eidolon.completed_item_count || 0;
  const totalItems = eidolon.item_count || 0;
  const status = eidolon.completed
    ? "Completed"
    : eidolon.owned
      ? `${completedWishes} of ${totalWishes} wishes done - ${completedItems} of ${totalItems} items`
      : "Not owned";
  const header = eidolonHeader(eidolon, status, options);
  const body = `
      ${starterNote(eidolon)}
      <div class="items">
        ${items.map((item) => itemRow(item, options)).join("")}
      </div>
  `;
  if (options.collapsed) {
    return `
      <details class="eidolon eidolon-collapsible">
        <summary>${header}</summary>
        ${body}
      </details>
    `;
  }
  return `
    <article class="eidolon">
      ${header}
      ${body}
    </article>
  `;
}

function eidolonHeader(eidolon, status, options = {}) {
  return `
    <div class="eidolon-header">
      <div class="eidolon-identity">
        ${options.collapsed ? '<span class="collapse-indicator" aria-hidden="true"></span>' : ""}
        ${eidolonImage(eidolon)}
        <div class="eidolon-title">
          <h2>${eidolon.detail_url ? externalLink(eidolon.name, eidolon.detail_url) : escapeHtml(eidolon.name)}</h2>
          <p>${status}</p>
        </div>
      </div>
      <div class="actions">
        ${eidolon.owned
          ? button("Remove", `setOwned(${eidolon.id}, false)`, "danger")
          : button("Own", `setOwned(${eidolon.id}, true)`, "primary")}
        ${eidolon.completed
          ? button("Bring Back", `setCompleted(${eidolon.id}, false)`, "")
          : button("Complete Eidolon", `setCompleted(${eidolon.id}, true)`, "primary", !eidolon.owned)}
      </div>
    </div>
  `;
}

function starterNote(eidolon) {
  if (!eidolon.is_starter) return "";
  return `
    <label class="starter-note">
      <span>Characters</span>
      <input
        class="starter-note-input"
        type="text"
        value="${escapeHtml(eidolon.character_note || "")}"
        placeholder="Who has this starter?"
        onchange="setCharacterNote(${eidolon.id}, this.value)"
      >
    </label>
  `;
}

function itemRow(item) {
  const groupLabel = item.wish_group_effective || item.wish_group || "-";
  const rowClasses = ["item"];
  if (item.completed) rowClasses.push("done");
  if (!item.starts_wish_group) rowClasses.push("continuation");
  return `
    <div class="${rowClasses.join(" ")}">
      <div class="group">${escapeHtml(groupLabel)}</div>
      <div>
        <div class="item-name">
          ${item.image_url ? `<img class="item-icon" src="${escapeHtml(item.image_url)}" alt="">` : `<span class="item-icon placeholder"></span>`}
          <strong>${item.detail_url ? externalLink(item.item, item.detail_url) : escapeHtml(item.item)}</strong>
        </div>
      </div>
      <div class="qty">x${escapeHtml(item.quantity_text)}</div>
      <div class="source">${escapeHtml(item.how_to_obtain || "No source listed")}</div>
      <div class="actions">
        ${item.completed
          ? button("Restore", `setItem(${item.id}, false)`, "")
          : button("Got It", `setItem(${item.id}, true)`, "primary")}
      </div>
    </div>
  `;
}

function eidolonImage(eidolon) {
  const image = eidolon.image_url || eidolon.icon_url;
  if (!image) {
    return `<div class="eidolon-art empty-art">${initials(eidolon.name)}</div>`;
  }
  return `<img class="eidolon-art" src="${escapeHtml(image)}" alt="">`;
}

function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function externalLink(label, url) {
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function button(label, onclick, kind = "", disabled = false) {
  return `<button class="action ${kind}" onclick="${onclick}" ${disabled ? "disabled" : ""}>${label}</button>`;
}

function empty(message) {
  return `<div class="empty">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

window.setOwned = (id, owned) => post(`/api/eidolons/${id}`, { owned });
window.setCompleted = (id, completed) => post(`/api/eidolons/${id}`, { completed });
window.setCharacterNote = (id, character_note) => post(`/api/eidolons/${id}`, { character_note });
window.setItem = (id, completed) => post(`/api/items/${id}`, { completed });

async function createProfile() {
  const name = window.prompt("New profile name");
  if (!name || !name.trim()) return;
  try {
    await post("/api/profiles", { name: name.trim() });
  } catch (error) {
    window.alert(`Profile creation failed: ${error.message}`);
  }
}

async function renameCurrentProfile() {
  const current = state.data.profiles.find((profile) => profile.id === state.data.current_profile_id);
  const name = window.prompt("Profile name", current ? current.name : "");
  if (!name || !name.trim()) return;
  try {
    await post(`/api/profiles/${state.data.current_profile_id}`, { name: name.trim() });
  } catch (error) {
    window.alert(`Profile rename failed: ${error.message}`);
  }
}

function downloadBackup() {
  window.location.href = "/api/backup/download";
}

async function restoreBackupFile(file) {
  if (!file) return;
  const confirmed = await confirmAction(
    "Restore this backup? This replaces the current tracker data. A local safety backup will be created first.",
  );
  if (!confirmed) return;

  try {
    const response = await fetch("/api/backup/restore", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: await file.arrayBuffer(),
    });
    if (!response.ok) {
      const errorText = await response.text();
      let message = errorText || "Restore failed.";
      try {
        message = JSON.parse(errorText).error || message;
      } catch {
        // Keep the plain response text.
      }
      throw new Error(message);
    }
    state.data = await response.json();
    render();
    window.alert("Backup restored.");
  } catch (error) {
    window.alert(`Backup restore failed: ${error.message}`);
  } finally {
    backupRestoreInput.value = "";
  }
}

async function shutdownApplication() {
  const confirmed = await confirmAction("Shut down Eidolon Tracker now? This will stop the local app server.");
  if (!confirmed) return;
  try {
    const response = await fetch("/api/shutdown", { method: "POST" });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Shutdown failed.");
    }
    settingsDialog.close();
    window.alert("Eidolon Tracker is shutting down. You can close this tab.");
  } catch (error) {
    window.alert(`Shutdown failed: ${error.message}`);
  }
}

const settingConfirmations = {
  own_all: "Mark every Eidolon as owned?",
  complete_all: "Mark every Eidolon and every wish item as complete?",
  clear_wishes: "Clear every wish item check and completed Eidolon flag?",
  starter_only: "Reset ownership to only the starter 6 and clear every wish check?",
};

function confirmAction(message) {
  if (!confirmDialog || typeof confirmDialog.showModal !== "function") {
    return Promise.resolve(window.confirm(message));
  }
  confirmMessage.textContent = message;
  confirmDialog.returnValue = "";
  confirmDialog.showModal();
  return new Promise((resolve) => {
    confirmDialog.addEventListener(
      "close",
      () => {
        resolve(confirmDialog.returnValue === "confirm");
      },
      { once: true },
    );
  });
}

settingsToggle.addEventListener("click", () => {
  settingsDialog.showModal();
});

profileSelect.addEventListener("change", async () => {
  try {
    await post("/api/profiles/active", { id: Number(profileSelect.value) });
  } catch (error) {
    window.alert(`Profile switch failed: ${error.message}`);
  }
});

profileNew.addEventListener("click", createProfile);
profileRename.addEventListener("click", renameCurrentProfile);
backupDownload.addEventListener("click", downloadBackup);
backupRestore.addEventListener("click", () => backupRestoreInput.click());
backupRestoreInput.addEventListener("change", () => restoreBackupFile(backupRestoreInput.files[0]));
appShutdown.addEventListener("click", shutdownApplication);

quickSetupOpen.addEventListener("click", () => {
  quickSetupSearch.value = "";
  renderQuickSetup();
  settingsDialog.close();
  quickSetupDialog.showModal();
});

quickSetupSearch.addEventListener("input", filterQuickSetupRows);
quickSetupSearch.addEventListener("keyup", filterQuickSetupRows);
quickSetupSearch.addEventListener("search", filterQuickSetupRows);

quickSetupList.addEventListener("change", (event) => {
  if (!event.target.matches('input[type="checkbox"]')) return;
  const row = event.target.closest(".quick-setup-row");
  const isOwned = event.target.checked;
  row.querySelectorAll("[data-tier]").forEach((button) => {
    button.disabled = !isOwned;
    button.classList.toggle("active", isOwned && button.dataset.tier === "1");
  });
});

quickSetupList.addEventListener("click", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton || tierButton.disabled) return;
  const row = tierButton.closest(".quick-setup-row");
  const wasActive = tierButton.classList.contains("active");
  row.querySelectorAll("[data-tier]").forEach((button) => button.classList.remove("active"));
  if (!wasActive) tierButton.classList.add("active");
});

quickSetupList.addEventListener("mouseover", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton) return;
  showQuickSetupTooltip(tierButton);
});

quickSetupList.addEventListener("focusin", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton) return;
  showQuickSetupTooltip(tierButton);
});

quickSetupApply.addEventListener("click", async () => {
  const confirmed = await confirmAction("Apply this quick setup to owned Eidolons and current wish tiers?");
  if (!confirmed) return;
  const eidolons = [...quickSetupList.querySelectorAll(".quick-setup-row")].map((row) => {
    const activeTier = row.querySelector("[data-tier].active");
    const tierValue = activeTier ? activeTier.dataset.tier : "0";
    return {
      id: Number(row.dataset.eidolonId),
      owned: row.querySelector('input[type="checkbox"]').checked,
      wish_tier: tierValue === "completed" ? 0 : Number(tierValue),
      completed: tierValue === "completed",
    };
  });
  try {
    await post("/api/quick-setup", { eidolons });
    quickSetupDialog.close();
  } catch (error) {
    window.alert(`Quick setup failed: ${error.message}`);
  }
});

document.querySelectorAll("[data-setting-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.settingAction;
    const confirmed = await confirmAction(settingConfirmations[action] || "Apply this setup change?");
    if (!confirmed) return;
    try {
      await post("/api/bulk", { action });
    } catch (error) {
      window.alert(`Settings update failed: ${error.message}`);
    }
  });
});

document.querySelectorAll(".tab[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    render();
  });
});

content.addEventListener("click", (event) => {
  if (event.target.closest(".eidolon-collapsible summary .actions button, .eidolon-collapsible summary a")) {
    event.preventDefault();
    event.stopPropagation();
    const link = event.target.closest("a");
    if (link) window.open(link.href, "_blank", "noreferrer");
  }
});

search.addEventListener("input", () => {
  state.search = search.value;
  render();
});

progressFilter.addEventListener("change", () => {
  state.progressFilter = progressFilter.value;
  render();
});

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme || "light";
  applyTheme(current === "dark" ? "light" : "dark");
});

applyTheme(localStorage.getItem("theme") || "dark");
load();

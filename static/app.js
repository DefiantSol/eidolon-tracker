const state = {
  view: "shopping",
  search: "",
  progressFilter: "incomplete",
  data: null,
  eidolonOpen: {},
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
const quickSetupPanel = quickSetupDialog.querySelector(".quick-setup-panel");
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
const starLabels = ["1", "2", "3", "4"];
const quickSetupTooltipEl = document.createElement("div");
quickSetupTooltipEl.className = "quick-setup-tooltip";
quickSetupTooltipEl.hidden = true;
quickSetupPanel.appendChild(quickSetupTooltipEl);

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

function matchesCollection(collection) {
  const needle = normalize(state.search);
  if (!needle) return true;
  return [
    collection.effect_group_label,
    collection.one_star_text,
    collection.two_star_text,
    collection.three_star_text,
    collection.four_star_text,
    ...(collection.members || []).map((member) => member.name),
  ]
    .map(normalize)
    .some((value) => value.includes(needle));
}

function matchesCollectionProgress(collection) {
  const maxStar = Number(collection.active_star_level || 0);
  const ownedCount = Number(collection.owned_count || 0);
  if (state.progressFilter === "all") return true;
  if (state.progressFilter === "complete") return maxStar >= 4;
  if (state.progressFilter === "active") return ownedCount > 0 && maxStar < 4;
  return maxStar < 4;
}

function collectionFamilyLabel(text) {
  const match = String(text || "").match(/^([^:]+):\s*(.+)$/);
  if (!match) return "";
  return match[1].replace(/\s+Lv\d+$/i, "").trim();
}

function collectionEffectStat(text) {
  const match = String(text || "").match(/^([^:]+):\s*(.+)$/);
  return match ? match[2].trim() : String(text || "").trim();
}

function collectionStatValue(text) {
  const stat = collectionEffectStat(text);
  const match = stat.match(/([+-]\s*\d+(?:\.\d+)?%?)\s*$/);
  return match ? match[1].replace(/\s+/g, "") : stat || "-";
}

function collectionGroupTitle(group) {
  const family = collectionFamilyLabel(group.rows[0]?.three_star_text || group.rows[0]?.four_star_text || "");
  return family ? `${group.label} (${family})` : group.label;
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
  const groups = [
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
  ];
  if (summary.collections_total !== undefined) {
    groups.push(
      statGroup("Collection", [
        stat(summary.collections_total, "Total"),
        stat(summary.collections_three_star, "3 Star"),
        stat(summary.collections_four_star, "4 Star"),
      ]),
    );
  }
  stats.innerHTML = groups.join("");
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
  const starRating = owned ? Math.max(1, Number(eidolon.star_rating || 0)) : 0;
  return `
    <div class="quick-setup-row" data-eidolon-id="${eidolon.id}">
      <label class="quick-setup-owned">
        <input type="checkbox" ${owned ? "checked" : ""}>
        <span>${escapeHtml(eidolon.name)}</span>
      </label>
      <div class="quick-setup-stars" role="group" aria-label="${escapeHtml(eidolon.name)} stars">
        ${starLabels.map((label, index) => quickSetupStarButton(label, index + 1, starRating, owned)).join("")}
      </div>
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
  quickSetupTooltipEl.textContent = `${tooltipData.title}\n${tooltipData.items.map((item) => `- ${item}`).join("\n")}`;
  quickSetupTooltipEl.hidden = false;
  const rect = button.getBoundingClientRect();
  const panelRect = quickSetupPanel.getBoundingClientRect();
  const tipRect = quickSetupTooltipEl.getBoundingClientRect();
  const maxLeft = Math.max(8, panelRect.width - tipRect.width - 8);
  const left = Math.max(8, Math.min(rect.right - panelRect.left - tipRect.width, maxLeft));
  let top = rect.bottom - panelRect.top + 8;
  if (top + tipRect.height > panelRect.height - 8) {
    top = Math.max(8, rect.top - panelRect.top - tipRect.height - 8);
  }
  quickSetupTooltipEl.style.left = `${left}px`;
  quickSetupTooltipEl.style.top = `${top}px`;
}

function hideQuickSetupTooltip() {
  quickSetupTooltipEl.hidden = true;
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
  if (state.view === "collections") renderCollections();
}

function renderEidolons() {
  const blocks = state.data.eidolons
    .filter((eidolon) => {
      if (state.progressFilter !== "active") return matchesProgressComplete(Boolean(eidolon.completed));
      return Boolean(eidolon.owned) && !eidolon.completed && Number(eidolon.current_wish_tier || 0) > 0;
    })
    .filter((eidolon) => matchesEidolon(eidolon, filteredWishItemsFor(eidolon.id)))
    .map((eidolon) =>
      eidolonBlock(eidolon, filteredWishItemsFor(eidolon.id), {
        collapsed: true,
        expanded: isEidolonExpanded(eidolon.id),
        showDone: true,
      }),
    );
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

function renderCollections() {
  const collections = (state.data.collections || [])
    .filter(matchesCollectionProgress)
    .filter(matchesCollection)
    .sort((a, b) => {
      const labelCompare = (a.effect_group_label || "").localeCompare(b.effect_group_label || "");
      if (labelCompare) return labelCompare;
      return Number(a.active_star_level || 0) - Number(b.active_star_level || 0);
    });
  const groups = new Map();
  collections.forEach((collection) => {
    const key = collection.effect_group_key || normalize(collection.effect_group_label || "Other");
    if (!groups.has(key)) {
      groups.set(key, { label: collection.effect_group_label || "Other", rows: [] });
    }
    groups.get(key).rows.push(collection);
  });
  content.innerHTML = groups.size
    ? `<section class="collections">${[...groups.values()].map(collectionSection).join("")}</section>`
    : empty(emptyForView("collections"));
}

function collectionSection(group) {
  return `
    <section class="collection-section">
      <h2 class="collection-section-title">${escapeHtml(collectionGroupTitle(group))}</h2>
      <div class="collection-rows">
        ${group.rows.map(collectionRow).join("")}
      </div>
    </section>
  `;
}

function collectionRow(collection) {
  const classes = ["collection-row"];
  if (collection.four_star_active) classes.push("complete");
  const members = [...(collection.members || [])];
  while (members.length < 3) {
    members.push(null);
  }
  return `
    <article class="${classes.join(" ")}">
      ${members.map(collectionMemberRow).join("")}
      <div class="collection-row-tier ${collection.three_star_active ? "active" : ""}">
        <strong>3*</strong>
        <span>${escapeHtml(collectionStatValue(collection.three_star_text))}</span>
      </div>
      <div class="collection-row-tier ${collection.four_star_active ? "active" : ""}">
        <strong>4*</strong>
        <span>${escapeHtml(collectionStatValue(collection.four_star_text))}</span>
      </div>
    </article>
  `;
}

function collectionMemberRow(member) {
  if (!member) {
    return `<div class="collection-member placeholder"></div>`;
  }
  const classes = ["collection-member"];
  if (member.owned) classes.push("owned");
  if (Number(member.star_rating || 0) >= 4) classes.push("maxed");
  const name = member.detail_url ? externalLink(member.name, member.detail_url) : escapeHtml(member.name);
  return `
    <div class="${classes.join(" ")}">
      <div class="collection-member-name">${name}</div>
    </div>
  `;
}

function collectionTierRow(level, text, active) {
  if (!text) return "";
  return `
    <div class="collection-tier ${active ? "active" : ""}">
      <strong>${level}*</strong>
      <span>${escapeHtml(text)}</span>
    </div>
  `;
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
        item_quality_code: item.item_quality_code || "",
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
    if (!group.item_quality_code && item.item_quality_code) group.item_quality_code = item.item_quality_code;
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
        ${itemIcon(group.image_url, group.item_quality_code)}
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

function eidolonOpenKey(eidolonId) {
  const profileId = state.data?.current_profile_id || 0;
  return `${profileId}:${eidolonId}`;
}

function isEidolonExpanded(eidolonId) {
  return Boolean(state.eidolonOpen[eidolonOpenKey(eidolonId)]);
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
      <details class="eidolon eidolon-collapsible" data-eidolon-id="${eidolon.id}" ${options.expanded ? "open" : ""}>
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
          ${itemIcon(item.image_url, item.item_quality_code)}
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

function quickSetupStarButton(label, value, currentStar, owned) {
  return `
    <button
      type="button"
      class="${Number(currentStar) === value ? "active" : ""}"
      data-star="${value}"
      ${owned ? "" : "disabled"}
    >${label}★</button>
  `;
}

function itemIcon(imageUrl, qualityCode) {
  const qualityAttr = qualityCode ? ` data-quality="${escapeHtml(String(qualityCode))}"` : "";
  if (imageUrl) {
    return `<img class="item-icon" src="${escapeHtml(imageUrl)}" alt=""${qualityAttr}>`;
  }
  return `<span class="item-icon placeholder"${qualityAttr}></span>`;
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
window.setStar = (id, star_rating) => post(`/api/eidolons/${id}`, { star_rating });
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
  star_all_1: "Set every Eidolon to at least 1 star and mark them owned?",
  star_all_4: "Set every Eidolon to 4 stars and mark them owned?",
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
  row.querySelectorAll("[data-tier], [data-star]").forEach((button) => {
    button.disabled = !isOwned;
    if (!isOwned) {
      button.classList.remove("active");
      return;
    }
    if (button.dataset.tier) button.classList.toggle("active", button.dataset.tier === "1");
    if (button.dataset.star) button.classList.toggle("active", button.dataset.star === "1");
  });
});

quickSetupList.addEventListener("click", (event) => {
  const toggleButton = event.target.closest("[data-tier], [data-star]");
  if (!toggleButton || toggleButton.disabled) return;
  const row = toggleButton.closest(".quick-setup-row");
  const selector = toggleButton.dataset.tier ? "[data-tier]" : "[data-star]";
  const wasActive = toggleButton.classList.contains("active");
  row.querySelectorAll(selector).forEach((button) => button.classList.remove("active"));
  if (!wasActive) toggleButton.classList.add("active");
});

quickSetupList.addEventListener("pointerover", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton) return;
  showQuickSetupTooltip(tierButton);
});

quickSetupList.addEventListener("pointerout", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton) return;
  if (event.relatedTarget && tierButton.contains(event.relatedTarget)) return;
  hideQuickSetupTooltip();
});

quickSetupList.addEventListener("focusin", (event) => {
  const tierButton = event.target.closest("[data-tier]");
  if (!tierButton) return;
  showQuickSetupTooltip(tierButton);
});

quickSetupList.addEventListener("focusout", (event) => {
  if (event.target.closest("[data-tier]")) hideQuickSetupTooltip();
});

quickSetupApply.addEventListener("click", async () => {
  const confirmed = await confirmAction("Apply this quick setup to owned Eidolons and current wish tiers?");
  if (!confirmed) return;
  const eidolons = [...quickSetupList.querySelectorAll(".quick-setup-row")].map((row) => {
    const activeTier = row.querySelector("[data-tier].active");
    const activeStar = row.querySelector("[data-star].active");
    const tierValue = activeTier ? activeTier.dataset.tier : "0";
    const owned = row.querySelector('input[type="checkbox"]').checked;
    return {
      id: Number(row.dataset.eidolonId),
      owned,
      star_rating: owned ? Number(activeStar ? activeStar.dataset.star : 1) : 0,
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

content.addEventListener("toggle", (event) => {
  const details = event.target.closest(".eidolon-collapsible");
  if (!details) return;
  state.eidolonOpen[eidolonOpenKey(Number(details.dataset.eidolonId || 0))] = details.open;
}, true);

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

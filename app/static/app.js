/* curlbook frontend — plain JS, no build step. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers --
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const VAR_RE = /\{\{\s*([$A-Za-z0-9_.\-]+)\s*\}\}/g;
  const BUILTINS = new Set(["$timestamp", "$timestampMs", "$uuid", "$randomInt"]);

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  }

  function toast(msg, kind = "info", ms = 3500) {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.classList.add("hide"), ms);
    setTimeout(() => el.remove(), ms + 400);
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    toast("Copied to clipboard", "ok", 1500);
  }

  const newRequest = () => ({
    id: null, name: "New Request", method: "GET", url: "", headers: [], body: "",
    options: { insecure: false, followRedirects: true, timeout: 30 }, extractions: [], tags: [],
  });

  // -------------------------------------------------------------- state --
  const state = {
    store: { collections: [], globals: {}, tags: {} },
    current: null,
    currentId: null,
    collectionId: null,
    dirty: false,
    rawDirty: false,
    lastResponse: null,
    collapsed: new Set(JSON.parse(localStorage.getItem("curlbook.collapsed") || "[]")),
    search: "",
  };

  const saveCollapsed = () => localStorage.setItem("curlbook.collapsed", JSON.stringify([...state.collapsed]));

  async function reloadStore() {
    state.store = await api("GET", "/api/store");
    state.store.tags = state.store.tags || {};
    renderSidebar();
    renderCollectionSelects();
    renderGlobalsCount();
    renderVarChips();
    renderTagSuggestions();
    if (state.current) renderTags();
  }

  function setDirty(v = true) {
    state.dirty = v;
    $("#dirty-indicator").classList.toggle("hidden", !v);
  }

  // --------------------------------------------------------------- tags --
  const TAG_FALLBACK_COLOR = "#8b93a5";
  const tagColor = (t) => state.store.tags[t] || TAG_FALLBACK_COLOR;

  /** Mirror of the server's normalisation: '  Auth Flow ' -> 'auth-flow'. */
  function normalizeTag(raw) {
    return String(raw || "").trim().replace(/^#+/, "").toLowerCase()
      .replace(/\s+/g, "-").replace(/[^\p{L}\p{N}_\-./:+]/gu, "").replace(/^-+|-+$/g, "").slice(0, 32);
  }

  function tagChip(tag, { small = false, removable = false, recolorable = false, filter = false, active = false } = {}) {
    const color = tagColor(tag);
    const dot = recolorable
      ? `<button type="button" class="tag-dot" data-recolor="${esc(tag)}" title="Change colour of '${esc(tag)}'"></button>`
      : `<span class="tag-dot"></span>`;
    const x = removable ? `<button type="button" class="tag-x" data-remove-tag="${esc(tag)}" title="Remove tag">&times;</button>` : "";
    const el = filter ? "button" : "span";
    const attrs = filter ? ` type="button" data-action="filter-tag" data-tag="${esc(tag)}" title="Show requests tagged '${esc(tag)}'"` : "";
    return `<${el} class="tag${small ? " tag-sm" : ""}${active ? " active" : ""}" style="--tag:${esc(color)}"${attrs}>${dot}<span class="tag-name">${esc(tag)}</span>${x}</${el}>`;
  }

  /** Parse the search box into terms. `tag:x` / `#x` are exact tag filters; other words are free text. */
  function parseSearch(q) {
    return q.trim().toLowerCase().split(/\s+/).filter(Boolean).map((term) => {
      const m = term.match(/^(?:tag:|#)(.*)$/);
      return m ? { tag: normalizeTag(m[1]) } : { text: term };
    }).filter((t) => t.text || t.tag);
  }

  function requestMatches(r, col, terms) {
    const tags = r.tags || [];
    return terms.every((t) => t.tag
      ? tags.includes(t.tag)
      : r.name.toLowerCase().includes(t.text) || (r.url || "").toLowerCase().includes(t.text)
        || r.method.toLowerCase() === t.text || col.name.toLowerCase().includes(t.text)
        || tags.some((tag) => tag.includes(t.text)));
  }

  function activeTagFilters() {
    return new Set(parseSearch(state.search).filter((t) => t.tag).map((t) => t.tag));
  }

  function setSearch(value) {
    state.search = value;
    $("#search").value = value;
    renderSidebar();
  }

  function toggleTagFilter(tag) {
    const terms = state.search.trim().split(/\s+/).filter(Boolean);
    const isThis = (t) => /^(tag:|#)/i.test(t) && normalizeTag(t.replace(/^(tag:|#)/i, "")) === tag;
    const next = terms.some(isThis) ? terms.filter((t) => !isThis(t)) : [...terms, `tag:${tag}`];
    setSearch(next.join(" "));
  }

  // ------------------------------------------------------------ sidebar --
  function renderSidebar() {
    const root = $("#collections");
    const terms = parseSearch(state.search);
    const searching = terms.length > 0;
    const activeTags = activeTagFilters();
    const parts = [];
    for (const col of state.store.collections) {
      const reqs = col.requests.filter((r) => !searching || requestMatches(r, col, terms));
      if (searching && !reqs.length) continue;
      const collapsed = !searching && state.collapsed.has(col.id);
      parts.push(`
        <div class="collection" data-cid="${col.id}">
          <div class="collection-head" data-action="toggle-col">
            <span class="caret">${collapsed ? "&#9656;" : "&#9662;"}</span>
            <span class="col-name">${esc(col.name)}</span>
            <span class="pill">${searching ? `${reqs.length}/${col.requests.length}` : col.requests.length}</span>
            <span class="col-actions">
              <button class="icon-btn" data-action="col-add" title="New request in collection">+</button>
              <button class="icon-btn" data-action="col-rename" title="Rename">&#9998;</button>
              <button class="icon-btn danger" data-action="col-delete" title="Delete collection">&times;</button>
            </span>
          </div>
          <div class="req-list ${collapsed ? "hidden" : ""}">
            ${reqs.map((r) => `
              <div class="req-item ${r.id === state.currentId ? "active" : ""}" data-rid="${r.id}" data-action="open-req" title="${esc(r.url)}">
                <span class="method m-${esc(r.method)}">${esc(r.method)}</span>
                <span class="req-main">
                  <span class="req-name">${esc(r.name)}</span>
                  ${(r.tags || []).length ? `<span class="req-tags">${r.tags.map((t) => tagChip(t, { small: true, filter: true, active: activeTags.has(t) })).join("")}</span>` : ""}
                </span>
                <span class="req-actions">
                  <button class="icon-btn" data-action="req-dup" title="Duplicate">&#10697;</button>
                  <button class="icon-btn danger" data-action="req-delete" title="Delete">&times;</button>
                </span>
              </div>`).join("") || `<div class="muted small empty-col">No requests</div>`}
          </div>
        </div>`);
    }
    root.innerHTML = parts.join("") || (searching
      ? `<div class="muted small pad">No requests match <code>${esc(state.search.trim())}</code>.</div>`
      : `<div class="muted small pad">No collections. Create one with "+ Collection".</div>`);
  }

  $("#collections").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const cid = btn.closest("[data-cid]")?.dataset.cid;
    const rid = btn.closest("[data-rid]")?.dataset.rid;
    e.stopPropagation();
    try {
      switch (action) {
        case "filter-tag":
          toggleTagFilter(btn.dataset.tag); break;
        case "toggle-col":
          state.collapsed.has(cid) ? state.collapsed.delete(cid) : state.collapsed.add(cid);
          saveCollapsed(); renderSidebar(); break;
        case "col-add":
          startNewRequest(cid); break;
        case "col-rename": {
          const col = state.store.collections.find((c) => c.id === cid);
          const name = prompt("Rename collection", col?.name || "");
          if (name && name.trim()) { await api("PUT", `/api/collections/${cid}`, { name }); await reloadStore(); }
          break;
        }
        case "col-delete": {
          const col = state.store.collections.find((c) => c.id === cid);
          if (!confirm(`Delete collection "${col.name}" and its ${col.requests.length} request(s)?`)) break;
          await api("DELETE", `/api/collections/${cid}`);
          if (state.collectionId === cid) closeEditor();
          await reloadStore(); break;
        }
        case "open-req":
          openRequest(rid); break;
        case "req-dup": {
          const res = await api("POST", `/api/requests/${rid}/duplicate`);
          await reloadStore(); openRequest(res.request.id, true); break;
        }
        case "req-delete": {
          const { req } = findReq(rid);
          if (!confirm(`Delete request "${req.name}"?`)) break;
          await api("DELETE", `/api/requests/${rid}`);
          if (state.currentId === rid) closeEditor();
          await reloadStore(); break;
        }
      }
    } catch (err) { toast(err.message, "err"); }
  });

  $("#search").addEventListener("input", (e) => { state.search = e.target.value; renderSidebar(); });

  function findReq(rid) {
    for (const c of state.store.collections) {
      const r = c.requests.find((x) => x.id === rid);
      if (r) return { col: c, req: r };
    }
    return {};
  }

  function renderCollectionSelects() {
    const opts = state.store.collections.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    for (const sel of [$("#req-collection"), $("#import-collection")]) {
      const prev = sel.value;
      sel.innerHTML = opts;
      if (prev && state.store.collections.some((c) => c.id === prev)) sel.value = prev;
    }
    if (state.collectionId) $("#req-collection").value = state.collectionId;
  }

  // ------------------------------------------------------------- editor --
  function confirmDiscard() {
    return !state.dirty || confirm("You have unsaved changes. Discard them?");
  }

  function openRequest(rid, force = false) {
    if (!force && rid === state.currentId) return;
    if (!force && !confirmDiscard()) return;
    const { col, req } = findReq(rid);
    if (!req) return;
    loadIntoEditor(clone(req), rid, col.id);
    setDirty(false);
  }

  async function startNewRequest(cid) {
    if (!confirmDiscard()) return;
    if (!state.store.collections.length) {
      await api("POST", "/api/collections", { name: "Default" });
      await reloadStore();
    }
    cid = cid || state.collectionId || state.store.collections[0].id;
    loadIntoEditor(newRequest(), null, cid);
    setDirty(true);
    $("#req-url").focus();
  }

  function closeEditor() {
    state.current = null; state.currentId = null; state.collectionId = null;
    setDirty(false);
    $("#editor").classList.add("hidden");
    $("#empty-state").classList.remove("hidden");
    renderSidebar();
  }

  function loadIntoEditor(req, rid, cid) {
    req.tags = req.tags || [];
    state.current = req;
    state.currentId = rid;
    state.collectionId = cid;
    state.rawDirty = false;
    state.lastResponse = null;
    $("#empty-state").classList.add("hidden");
    $("#editor").classList.remove("hidden");
    renderForm();
    clearResponse();
    renderSidebar();
    if (activeTab("req") === "raw") refreshRaw();
  }

  function renderForm() {
    const r = state.current;
    $("#req-name").value = r.name;
    $("#req-collection").value = state.collectionId;
    $("#req-method").value = r.method;
    $("#req-url").value = r.url;
    $("#req-body").value = r.body;
    $("#opt-insecure").checked = !!r.options.insecure;
    $("#opt-follow").checked = !!r.options.followRedirects;
    $("#opt-timeout").value = r.options.timeout ?? 30;
    renderHeaders();
    renderExtractions();
    renderVarChips();
    renderTags();
    updateMethodColor();
  }

  function updateMethodColor() {
    const sel = $("#req-method");
    sel.className = `input select method-select m-${sel.value}`;
  }

  function onFormChange() {
    setDirty(true);
    state.rawDirty = false;
    renderVarChips();
    if (activeTab("req") === "raw") refreshRawDebounced();
  }

  // ------------------------------------------------------- editor: tags --
  function renderTags() {
    if (!state.current) return;
    $("#req-tags").innerHTML = state.current.tags.map((t) => tagChip(t, { removable: true, recolorable: true })).join("");
    renderTagSuggestions();
  }

  function renderTagSuggestions() {
    const have = new Set(state.current?.tags || []);
    $("#tag-suggestions").innerHTML = Object.keys(state.store.tags || {}).sort()
      .filter((t) => !have.has(t)).map((t) => `<option value="${esc(t)}"></option>`).join("");
  }

  async function addTags(text) {
    if (!state.current) return;
    const fresh = String(text).split(",").map(normalizeTag).filter((t) => t && !state.current.tags.includes(t));
    if (!fresh.length) return;
    if (state.current.tags.length + fresh.length > 20) { toast("A request can have at most 20 tags", "warn"); return; }
    state.current.tags.push(...fresh);
    setDirty(true);
    renderTags();
    // reserve a unique colour for brand-new tags so the chip shows its final colour right away
    for (const t of fresh.filter((t) => !state.store.tags[t])) {
      try {
        const res = await api("POST", "/api/tags", { name: t });
        state.store.tags = res.tags;
      } catch (err) { toast(err.message, "err"); }
    }
    renderTags();
  }

  function removeTag(tag) {
    state.current.tags = state.current.tags.filter((t) => t !== tag);
    setDirty(true);
    renderTags();
  }

  const tagInput = $("#tag-input");
  tagInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTags(tagInput.value); tagInput.value = "";
    } else if (e.key === "Tab" && tagInput.value.trim()) {
      addTags(tagInput.value); tagInput.value = "";
    } else if (e.key === "Backspace" && !tagInput.value && state.current?.tags.length) {
      removeTag(state.current.tags[state.current.tags.length - 1]);
    }
  });
  tagInput.addEventListener("input", (e) => {
    // picking a datalist suggestion fires an input event without a keyboard inputType
    if (!e.inputType || e.inputType === "insertReplacementText") { addTags(tagInput.value); tagInput.value = ""; }
    else if (tagInput.value.includes(",")) { addTags(tagInput.value); tagInput.value = ""; }
  });
  tagInput.addEventListener("blur", () => { if (tagInput.value.trim()) { addTags(tagInput.value); tagInput.value = ""; } });
  $("#tag-editor").addEventListener("click", (e) => {
    if (e.target === e.currentTarget || e.target.id === "req-tags") tagInput.focus();
  });

  const colorPicker = $("#tag-color-picker");
  $("#req-tags").addEventListener("click", (e) => {
    const rm = e.target.closest("[data-remove-tag]");
    if (rm) { removeTag(rm.dataset.removeTag); return; }
    const dot = e.target.closest("[data-recolor]");
    if (dot) {
      colorPicker.dataset.tag = dot.dataset.recolor;
      colorPicker.value = tagColor(dot.dataset.recolor);
      if (colorPicker.showPicker) colorPicker.showPicker(); else colorPicker.click();
    }
  });
  colorPicker.addEventListener("change", async () => {
    const tag = colorPicker.dataset.tag;
    if (!tag || colorPicker.value.toLowerCase() === tagColor(tag).toLowerCase()) return;
    try {
      const res = await api("PUT", `/api/tags/${encodeURIComponent(tag)}`, { color: colorPicker.value });
      state.store.tags = res.tags;
      renderTags(); renderSidebar();
      toast(`Tag '${tag}' recoloured`, "ok", 1500);
    } catch (err) { toast(err.message, "err", 5000); }
  });

  // simple bindings
  $("#req-name").addEventListener("input", (e) => { state.current.name = e.target.value; setDirty(true); });
  $("#req-collection").addEventListener("change", (e) => { state.collectionId = e.target.value; setDirty(true); });
  $("#req-method").addEventListener("change", (e) => { state.current.method = e.target.value; updateMethodColor(); onFormChange(); });
  $("#req-url").addEventListener("input", (e) => { state.current.url = e.target.value; onFormChange(); });
  $("#req-body").addEventListener("input", (e) => { state.current.body = e.target.value; onFormChange(); });
  $("#opt-insecure").addEventListener("change", (e) => { state.current.options.insecure = e.target.checked; onFormChange(); });
  $("#opt-follow").addEventListener("change", (e) => { state.current.options.followRedirects = e.target.checked; onFormChange(); });
  $("#opt-timeout").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    state.current.options.timeout = v > 0 ? v : 30;
    onFormChange();
  });

  // Paste a full curl command into the URL bar -> parse it automatically.
  $("#req-url").addEventListener("paste", async (e) => {
    const text = (e.clipboardData || window.clipboardData).getData("text");
    if (!/^\s*curl\s/i.test(text)) return;
    e.preventDefault();
    await applyCurlToForm(text);
  });

  $("#btn-format-body").addEventListener("click", () => {
    try {
      // Temporarily protect unquoted {{vars}} so JSON.parse can handle them
      const placeholders = [];
      const protectedBody = state.current.body.replace(/(?<!")\{\{[^}]+\}\}(?!")/g, (m) => {
        placeholders.push(m); return `"__CURLBOOK_PH_${placeholders.length - 1}__"`;
      });
      let out = JSON.stringify(JSON.parse(protectedBody), null, 2);
      out = out.replace(/"__CURLBOOK_PH_(\d+)__"/g, (_, i) => placeholders[Number(i)]);
      state.current.body = out;
      $("#req-body").value = out;
      onFormChange();
    } catch (err) { toast("Body is not valid JSON: " + err.message, "err"); }
  });

  // headers table
  function renderHeaders() {
    const rows = state.current.headers.map((h, i) => `
      <tr data-i="${i}">
        <td><input type="checkbox" data-f="enabled" ${h.enabled ? "checked" : ""} /></td>
        <td><input class="input mono" data-f="key" value="${esc(h.key)}" placeholder="Header" /></td>
        <td><input class="input mono" data-f="value" value="${esc(h.value)}" placeholder="Value" /></td>
        <td><button class="icon-btn danger" data-del title="Remove">&times;</button></td>
      </tr>`).join("");
    $("#headers-body").innerHTML = rows || `<tr><td colspan="4" class="muted small">No headers</td></tr>`;
    const n = state.current.headers.filter((h) => h.enabled).length;
    $("#headers-count").textContent = n || "";
  }

  function bindRowTable(tbodySel, listGetter, rerender) {
    const tb = $(tbodySel);
    tb.addEventListener("input", (e) => {
      const tr = e.target.closest("tr[data-i]"); const f = e.target.dataset.f;
      if (!tr || !f) return;
      const item = listGetter()[Number(tr.dataset.i)];
      item[f] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      if (e.target.type === "checkbox") rerender();
      onFormChange();
    });
    tb.addEventListener("change", (e) => {
      if (e.target.tagName !== "SELECT") return;
      const tr = e.target.closest("tr[data-i]");
      listGetter()[Number(tr.dataset.i)][e.target.dataset.f] = e.target.value;
      rerender(); onFormChange();
    });
    tb.addEventListener("click", (e) => {
      if (!e.target.closest("[data-del]")) return;
      const tr = e.target.closest("tr[data-i]");
      listGetter().splice(Number(tr.dataset.i), 1);
      rerender(); onFormChange();
    });
  }

  bindRowTable("#headers-body", () => state.current.headers, renderHeaders);
  $("#btn-add-header").addEventListener("click", () => {
    state.current.headers.push({ key: "", value: "", enabled: true });
    renderHeaders(); onFormChange();
    $$("#headers-body tr:last-child input[data-f=key]")[0]?.focus();
  });

  // extraction rules table
  function renderExtractions() {
    const rows = state.current.extractions.map((x, i) => `
      <tr data-i="${i}">
        <td><input class="input mono" data-f="var" value="${esc(x.var)}" placeholder="token" /></td>
        <td><select class="input select" data-f="source">
          ${["body", "header", "status"].map((s) => `<option ${x.source === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></td>
        <td><input class="input mono" data-f="path" value="${esc(x.path)}" ${x.source === "status" ? "disabled" : ""}
             placeholder="${x.source === "header" ? "Set-Cookie" : "data.items[0].id"}" /></td>
        <td><button class="icon-btn danger" data-del title="Remove">&times;</button></td>
      </tr>`).join("");
    $("#extract-body").innerHTML = rows || `<tr><td colspan="4" class="muted small">No extraction rules</td></tr>`;
    $("#extract-count").textContent = state.current.extractions.length || "";
  }

  bindRowTable("#extract-body", () => state.current.extractions, renderExtractions);
  $("#btn-add-extract").addEventListener("click", () => {
    state.current.extractions.push({ var: "", source: "body", path: "" });
    renderExtractions(); onFormChange();
  });

  // variable chips under URL bar
  function renderVarChips() {
    const el = $("#var-chips");
    if (!state.current) { el.innerHTML = ""; return; }
    const r = state.current;
    const text = [r.url, r.body, ...r.headers.filter((h) => h.enabled).flatMap((h) => [h.key, h.value])].join("\n");
    const names = [...new Set([...text.matchAll(VAR_RE)].map((m) => m[1]))];
    const g = state.store.globals;
    el.innerHTML = names.map((n) => {
      if (BUILTINS.has(n)) return `<span class="chip builtin" title="built-in">{{${esc(n)}}}</span>`;
      if (n in g) return `<span class="chip ok" title="${esc(g[n])}">{{${esc(n)}}} = ${esc(truncate(g[n], 40))}</span>`;
      return `<span class="chip missing" title="Not defined in globals">{{${esc(n)}}} undefined</span>`;
    }).join("");
  }
  const truncate = (s, n) => (String(s).length > n ? String(s).slice(0, n) + "…" : String(s));

  // ---------------------------------------------------------------- tabs --
  function activeTab(group) {
    return $(`.tabs[data-tabgroup="${group}"] .tab.active`)?.dataset.tab;
  }
  function showTab(group, tab) {
    $$(`.tabs[data-tabgroup="${group}"] .tab`).forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    $$(`.tab-panels[data-tabgroup="${group}"] > .tab-panel`).forEach((p) => p.classList.toggle("active", p.dataset.panel === tab));
    if (group === "req" && tab === "raw" && !state.rawDirty) refreshRaw();
  }
  $$(".tabs").forEach((nav) => nav.addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) showTab(nav.dataset.tabgroup, t.dataset.tab);
  }));

  // ------------------------------------------------------------ raw curl --
  async function refreshRaw() {
    if (!state.current) return;
    try {
      const { curl } = await api("POST", "/api/build-curl", { request: state.current });
      $("#req-raw").value = curl;
      state.rawDirty = false;
    } catch (err) { toast(err.message, "err"); }
  }
  const refreshRawDebounced = debounce(refreshRaw, 300);

  $("#req-raw").addEventListener("input", () => { state.rawDirty = true; });
  $("#btn-raw-refresh").addEventListener("click", refreshRaw);
  $("#btn-raw-copy").addEventListener("click", () => copyText($("#req-raw").value));
  $("#btn-raw-copy-resolved").addEventListener("click", async () => {
    try {
      const { curl, missing } = await api("POST", "/api/build-curl", { request: state.current, resolve: true });
      await copyText(curl);
      if (missing.length) toast("Unresolved variables: " + missing.join(", "), "warn");
    } catch (err) { toast(err.message, "err"); }
  });
  $("#btn-raw-apply").addEventListener("click", () => applyCurlToForm($("#req-raw").value));

  async function applyCurlToForm(text) {
    try {
      const { request, warnings } = await api("POST", "/api/parse-curl", { curl: text });
      Object.assign(state.current, {
        method: request.method, url: request.url, headers: request.headers,
        body: request.body, options: request.options,
      });
      renderForm();
      setDirty(true);
      state.rawDirty = false;
      if (activeTab("req") === "raw") refreshRaw();
      toast("curl parsed into form", "ok", 2000);
      warnings.forEach((w) => toast(w, "warn", 6000));
    } catch (err) { toast("Parse error: " + err.message, "err"); }
  }

  // --------------------------------------------------------------- save --
  async function save() {
    if (!state.current) return;
    try {
      let res;
      if (state.currentId) {
        res = await api("PUT", `/api/requests/${state.currentId}`, { request: state.current, collectionId: state.collectionId });
      } else {
        res = await api("POST", "/api/requests", { request: state.current, collectionId: state.collectionId });
      }
      state.currentId = res.request.id;
      state.current.id = res.request.id;
      state.collectionId = res.collectionId;
      setDirty(false);
      await reloadStore();
      toast("Saved", "ok", 1500);
    } catch (err) { toast("Save failed: " + err.message, "err"); }
  }
  $("#btn-save").addEventListener("click", save);

  // --------------------------------------------------------------- send --
  async function send() {
    if (!state.current) return;
    const btn = $("#btn-send");
    btn.disabled = true; btn.textContent = "Sending…";
    $("#resp-status").className = "status"; $("#resp-status").textContent = "…";
    $("#resp-meta").textContent = "";
    try {
      const res = await api("POST", "/api/send", { request: state.current });
      state.lastResponse = res;
      if (res.globals) { state.store.globals = res.globals; renderGlobalsCount(); renderVarChips(); }
      renderResponse(res);
    } catch (err) {
      renderResponse({ error: err.message });
    } finally {
      btn.disabled = false; btn.textContent = "Send";
    }
  }
  $("#btn-send").addEventListener("click", send);
  $("#req-url").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

  // ----------------------------------------------------------- response --
  function clearResponse() {
    $("#resp-status").textContent = ""; $("#resp-status").className = "status";
    $("#resp-meta").textContent = "";
    $("#resp-alerts").innerHTML = "";
    $("#resp-body").innerHTML = `<span class="muted">Send the request to see the response.</span>`;
    $("#resp-headers").innerHTML = "";
    $("#resp-sent").textContent = "";
    $("#resp-extract").innerHTML = "";
    $("#rextract-count").textContent = "";
    $("#qx-result").textContent = "";
  }

  const fmtSize = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`);

  function renderResponse(res) {
    clearResponse();
    const alerts = [];
    if (res.missing?.length) alerts.push(`<div class="alert warn">Undefined variables sent literally: ${res.missing.map((m) => `<code>{{${esc(m)}}}</code>`).join(" ")}</div>`);
    if (res.error) alerts.push(`<div class="alert err">${esc(res.error)}</div>`);
    if (res.truncated) alerts.push(`<div class="alert warn">Response body truncated.</div>`);
    $("#resp-alerts").innerHTML = alerts.join("");
    $("#resp-sent").textContent = res.sentCurl || "";

    if (res.error) {
      $("#resp-status").textContent = "Error"; $("#resp-status").classList.add("s-err");
      $("#resp-body").innerHTML = "";
      return;
    }
    const cls = res.status < 300 ? "s-ok" : res.status < 400 ? "s-redirect" : "s-err";
    $("#resp-status").textContent = `${res.status} ${res.reason || ""}`;
    $("#resp-status").classList.add(cls);
    $("#resp-meta").textContent = `${res.timeMs} ms · ${fmtSize(res.size)}${res.finalUrl && res.finalUrl !== res.resolvedUrl ? " · → " + res.finalUrl : ""}`;

    // body
    let parsed, isJson = false;
    try { parsed = JSON.parse(res.body); isJson = typeof parsed === "object" && parsed !== null; } catch (_) { /* not json */ }
    if (isJson && res.body.length < 2_000_000) {
      $("#resp-body").innerHTML = renderJson(parsed, "", 0);
      $("#resp-body").classList.add("json");
    } else {
      $("#resp-body").textContent = isJson ? JSON.stringify(parsed, null, 2) : res.body;
      $("#resp-body").classList.remove("json");
    }

    // headers
    $("#resp-headers").innerHTML = Object.entries(res.headers || {}).map(([k, v]) =>
      `<tr><td class="mono hdr-name" data-header="${esc(k)}" title="Click to extract">${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join("");

    // extractions
    const ex = res.extractions || [];
    $("#rextract-count").textContent = ex.length || "";
    $("#resp-extract").innerHTML = ex.map((x) => x.ok
      ? `<tr><td class="mono ok-text">{{${esc(x.var)}}}</td><td class="mono">${esc(x.value)}</td></tr>`
      : `<tr><td class="mono err-text">{{${esc(x.var)}}}</td><td class="err-text">${esc(x.error)}</td></tr>`).join("")
      || `<tr><td class="muted small">No extraction rules on this request.</td></tr>`;
    if (ex.length) {
      const okN = ex.filter((x) => x.ok).length;
      toast(`Extracted ${okN}/${ex.length} variable(s)`, okN === ex.length ? "ok" : "warn", 2500);
    }
  }

  // JSON tree renderer with clickable paths
  const IDENT = /^[A-Za-z_][\w-]*$/;
  function childPath(base, key) {
    if (typeof key === "number") return `${base}[${key}]`;
    if (IDENT.test(key)) return base ? `${base}.${key}` : key;
    return `${base}["${key}"]`;
  }
  function renderJson(v, path, depth) {
    const pad = "  ".repeat(depth);
    const pad1 = "  ".repeat(depth + 1);
    if (Array.isArray(v)) {
      if (!v.length) return `<span class="j-val" data-path="${esc(path)}">[]</span>`;
      return `<span class="j-val j-brace" data-path="${esc(path)}">[</span>\n` +
        v.map((item, i) => pad1 + renderJson(item, childPath(path, i), depth + 1)).join(",\n") + `\n${pad}]`;
    }
    if (v && typeof v === "object") {
      const keys = Object.keys(v);
      if (!keys.length) return `<span class="j-val" data-path="${esc(path)}">{}</span>`;
      return `<span class="j-val j-brace" data-path="${esc(path)}">{</span>\n` +
        keys.map((k) => {
          const p = childPath(path, k);
          return `${pad1}<span class="j-key" data-path="${esc(p)}">"${esc(k)}"</span>: ${renderJson(v[k], p, depth + 1)}`;
        }).join(",\n") + `\n${pad}}`;
    }
    const t = v === null ? "null" : typeof v;
    return `<span class="j-val j-${t}" data-path="${esc(path)}">${esc(JSON.stringify(v))}</span>`;
  }

  $("#resp-body").addEventListener("click", (e) => {
    const el = e.target.closest("[data-path]");
    if (!el) return;
    $("#qx-source").value = "body";
    $("#qx-path").value = el.dataset.path;
    if (!$("#qx-var").value) {
      const last = el.dataset.path.split(/[.[\]"]+/).filter(Boolean).pop() || "value";
      $("#qx-var").value = /^\d+$/.test(last) ? "value" : last;
    }
    previewExtract();
  });
  $("#resp-headers").addEventListener("click", (e) => {
    const el = e.target.closest("[data-header]");
    if (!el) return;
    $("#qx-source").value = "header";
    $("#qx-path").value = el.dataset.header;
    if (!$("#qx-var").value) $("#qx-var").value = el.dataset.header.replace(/[^\w]/g, "");
    showTab("resp", "rbody");
    previewExtract();
  });

  // quick extract bar
  async function previewExtract() {
    const res = state.lastResponse;
    const out = $("#qx-result");
    if (!res || res.error) { out.textContent = "No response yet"; out.className = "mono small qx-result err-text"; return null; }
    const r = await api("POST", "/api/extract", {
      source: $("#qx-source").value, path: $("#qx-path").value,
      status: res.status, headers: res.headers, body: res.body,
    });
    out.textContent = r.ok ? `= ${truncate(r.value, 120)}` : r.error;
    out.title = r.ok ? r.value : "";
    out.className = `mono small qx-result ${r.ok ? "ok-text" : "err-text"}`;
    return r;
  }
  $("#btn-qx-preview").addEventListener("click", () => previewExtract().catch((e) => toast(e.message, "err")));
  $("#qx-path").addEventListener("keydown", (e) => { if (e.key === "Enter") previewExtract(); });
  $("#btn-qx-save").addEventListener("click", async () => {
    try {
      const name = $("#qx-var").value.trim();
      if (!name) { toast("Enter a variable name", "warn"); $("#qx-var").focus(); return; }
      const r = await previewExtract();
      if (!r || !r.ok) return;
      const { globals } = await api("PATCH", "/api/globals", { globals: { [name]: r.value } });
      state.store.globals = globals;
      renderGlobalsCount(); renderVarChips();
      toast(`Saved {{${name}}}`, "ok");
    } catch (err) { toast(err.message, "err"); }
  });
  $("#btn-qx-rule").addEventListener("click", () => {
    const name = $("#qx-var").value.trim();
    if (!name) { toast("Enter a variable name", "warn"); $("#qx-var").focus(); return; }
    state.current.extractions.push({ var: name, source: $("#qx-source").value, path: $("#qx-path").value });
    renderExtractions(); onFormChange();
    toast(`Added extraction rule for {{${name}}} — remember to save`, "ok");
  });
  $("#btn-copy-sent").addEventListener("click", () => copyText($("#resp-sent").textContent));

  // ------------------------------------------------------------- modals --
  function openModal(id) { $(id).classList.remove("hidden"); }
  function closeModal(el) { el.closest(".modal").classList.add("hidden"); }
  $$(".modal").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m || e.target.closest("[data-close]")) closeModal(m); });
  });

  // import
  function openImport() {
    renderCollectionSelects();
    if (state.collectionId) $("#import-collection").value = state.collectionId;
    $("#import-curl").value = ""; $("#import-name").value = ""; $("#import-tags").value = "";
    openModal("#modal-import");
    $("#import-curl").focus();
  }
  $("#btn-import").addEventListener("click", openImport);
  $("#btn-import-go").addEventListener("click", async () => {
    if (!confirmDiscard()) return;
    try {
      if (!state.store.collections.length) await api("POST", "/api/collections", { name: "Default" });
      const res = await api("POST", "/api/import", {
        curl: $("#import-curl").value, name: $("#import-name").value, collectionId: $("#import-collection").value,
        tags: $("#import-tags").value.split(",").map(normalizeTag).filter(Boolean),
      });
      closeModal($("#modal-import"));
      await reloadStore();
      state.collapsed.delete(res.collectionId); saveCollapsed();
      openRequest(res.request.id, true);
      toast(`Imported "${res.request.name}"`, "ok");
      res.warnings.forEach((w) => toast(w, "warn", 6000));
    } catch (err) { toast("Import failed: " + err.message, "err"); }
  });

  // globals
  let globalsDraft = [];
  function renderGlobalsCount() { $("#globals-count").textContent = Object.keys(state.store.globals).length; }
  function renderGlobalsTable() {
    $("#globals-body").innerHTML = globalsDraft.map((g, i) => `
      <tr data-i="${i}">
        <td><input class="input mono" data-f="key" value="${esc(g.key)}" placeholder="name" /></td>
        <td><input class="input mono" data-f="value" value="${esc(g.value)}" placeholder="value" /></td>
        <td><button class="icon-btn" data-copy title="Copy value">&#10697;</button><button class="icon-btn danger" data-del title="Remove">&times;</button></td>
      </tr>`).join("") || `<tr><td colspan="3" class="muted small">No global variables yet.</td></tr>`;
  }
  $("#globals-body").addEventListener("input", (e) => {
    const tr = e.target.closest("tr[data-i]");
    if (tr && e.target.dataset.f) globalsDraft[Number(tr.dataset.i)][e.target.dataset.f] = e.target.value;
  });
  $("#globals-body").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-i]");
    if (!tr) return;
    if (e.target.closest("[data-del]")) { globalsDraft.splice(Number(tr.dataset.i), 1); renderGlobalsTable(); }
    if (e.target.closest("[data-copy]")) copyText(globalsDraft[Number(tr.dataset.i)].value);
  });
  $("#btn-globals").addEventListener("click", async () => {
    try { await reloadStore(); } catch (_) { /* use cached */ }
    globalsDraft = Object.entries(state.store.globals).map(([key, value]) => ({ key, value }));
    renderGlobalsTable();
    openModal("#modal-globals");
  });
  $("#btn-add-global").addEventListener("click", () => {
    globalsDraft.push({ key: "", value: "" }); renderGlobalsTable();
    $$("#globals-body tr:last-child input")[0]?.focus();
  });
  $("#btn-globals-save").addEventListener("click", async () => {
    const obj = {};
    for (const g of globalsDraft) if (g.key.trim()) obj[g.key.trim()] = g.value;
    try {
      const { globals } = await api("PUT", "/api/globals", { globals: obj });
      state.store.globals = globals;
      renderGlobalsCount(); renderVarChips();
      closeModal($("#modal-globals"));
      toast("Globals saved", "ok", 1500);
    } catch (err) { toast(err.message, "err"); }
  });

  // -------------------------------------------------------- top buttons --
  $("#btn-new-request").addEventListener("click", () => startNewRequest());
  $("#btn-new-collection").addEventListener("click", async () => {
    const name = prompt("Collection name", "New Collection");
    if (!name || !name.trim()) return;
    try { await api("POST", "/api/collections", { name }); await reloadStore(); } catch (err) { toast(err.message, "err"); }
  });
  document.addEventListener("click", (e) => {
    const a = e.target.closest("#empty-state [data-action]");
    if (!a) return;
    if (a.dataset.action === "new-request") startNewRequest();
    if (a.dataset.action === "import") openImport();
  });

  // ------------------------------------------------------------ keyboard --
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    else if (mod && e.key === "Enter") { e.preventDefault(); send(); }
    else if (e.key === "Escape") $$(".modal:not(.hidden)").forEach((m) => m.classList.add("hidden"));
  });
  window.addEventListener("beforeunload", (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ""; } });

  // ---------------------------------------------------------------- theme --
  const THEME_KEY = "curlbook.theme";
  function applyTheme(theme) {
    const dark = theme === "dark";
    if (dark) document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    const btn = $("#btn-theme");
    const label = dark ? "Switch to light mode" : "Switch to dark mode";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.setAttribute("aria-pressed", String(dark));
  }
  $("#btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* ignore */ }
  });
  applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

  // ---------------------------------------------------------------- init --
  reloadStore().catch((err) => toast("Failed to load store: " + err.message, "err", 8000));
})();

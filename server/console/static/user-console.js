// src/dom.ts
var byId = (id) => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing required element #${id}`);
  return el;
};
function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function fmtTime(ms) {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fmtRelative(ms) {
  const now = Date.now();
  const diff = now - ms;
  if (diff < 864e5) return "Today";
  if (diff < 1728e5) return "Yesterday";
  return new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" });
}

// src/refs.ts
var _refs = {};
var refs = _refs;
function populateRefs() {
  _refs.sidebar = byId("sidebar");
  _refs.backdrop = byId("sidebarBackdrop");
  _refs.settingsOverlay = byId("settingsOverlay");
  _refs.settingsPanel = byId("settingsPanel");
  _refs.thread = byId("thread");
  _refs.fab = byId("scrollFab");
  _refs.dropdown = byId("slashDropdown");
  _refs.ta = byId("inputArea");
  _refs.attachPopover = byId("attachPopover");
  _refs.webInputPanel = byId("webInputPanel");
  _refs.kbPanel = byId("kbPanel");
  _refs.cmdPicker = byId("cmdPicker");
  _refs.attachBtn = byId("attachBtn");
  _refs.cmdBtn = byId("cmdBtn");
}

// src/state.ts
var state = {
  activeConversationId: localStorage.getItem("nc_active_conv") || null,
  isStreaming: false,
  dynamicCmds: [],
  allSlashItems: [],
  slashSelIdx: 0,
  allPickerItems: [],
  pickerIdx: 0,
  attachments: [],
  userScrolledUp: false,
  streamAbortCtrl: null,
  convMenuTargetId: null,
  convMenuTargetTitle: "",
  renameTargetId: null
};
function setActiveConversation(id) {
  state.activeConversationId = id;
  if (id) localStorage.setItem("nc_active_conv", id);
  else localStorage.removeItem("nc_active_conv");
}

// src/toast.ts
function showToast(msg) {
  const t = byId("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}
function copyMsg(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add("copied");
    btn.textContent = "\u2713 Copied";
    setTimeout(() => {
      btn.classList.remove("copied");
      btn.innerHTML = "&#128203; Copy";
    }, 2e3);
  });
  showToast("Copied to clipboard");
}
function copyBubble(btn, id) {
  copyMsg(btn, document.getElementById(id)?.innerText || "");
}
function initToast() {
  window["copyMsg"] = copyMsg;
  window["copyBubble"] = copyBubble;
  window["showToast"] = showToast;
  refs.thread.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy-code-btn");
    if (!btn) return;
    const codeDiv = btn.closest(".code-block-wrap")?.querySelector(".code-block");
    if (codeDiv) {
      navigator.clipboard.writeText(codeDiv.textContent ?? "");
      showToast("Code copied");
    }
  });
}

// src/citations.ts
function buildCitationsHtml(results) {
  if (!results.length) return "";
  let html = `<div class="citation-label">&#128206; ${results.length} source${results.length > 1 ? "s" : ""} cited</div>`;
  results.forEach((r, i) => {
    const meta = r.metadata || {};
    const filename = escHtml(String(meta.source ?? meta.filename ?? "Unknown source"));
    const section = escHtml(String(meta.section ?? meta.heading ?? ""));
    const score = Math.round(r.score * 100);
    const scoreClass = score >= 80 ? "high" : score >= 50 ? "mid" : "low";
    const chunkText = escHtml(r.text || "").slice(0, 400);
    const chunkId = `chunk-${i}-${Date.now()}`;
    const sourceUri = String(meta.source_uri ?? "").trim();
    const source = String(meta.source ?? "").trim();
    const sourceKey = String(meta.source_key ?? "").trim();
    const start = meta.original_char_start;
    const end = meta.original_char_end;
    let viewHref = "";
    if (sourceKey || sourceUri || source) {
      const p = new URLSearchParams();
      if (sourceKey) p.set("source_key", sourceKey);
      if (sourceUri) p.set("source_uri", sourceUri);
      else if (source) p.set("source", source);
      if (start !== void 0 && end !== void 0) {
        p.set("start", String(start));
        p.set("end", String(end));
      }
      viewHref = `/console/source-document/view?${p.toString()}`;
    }
    html += `
          <div class="citation-card" onclick="toggleCitation(this)">
            <div class="citation-header">
              <span class="citation-icon">&#128196;</span>
              <div class="citation-info">
                <div class="citation-filename">${filename}${viewHref ? ` <a href="${viewHref}" target="_blank" onclick="event.stopPropagation()" style="font-size:10px;color:var(--accent)">[view]</a>` : ""}</div>
                ${section ? `<div class="citation-section">${section}</div>` : ""}
              </div>
              <div class="relevance-bar-wrap">
                <span class="relevance-pct ${scoreClass}">${score}%</span>
                <div class="relevance-bar"><div class="relevance-fill ${scoreClass}" style="width:${score}%"></div></div>
              </div>
              <span class="citation-chevron">&#8964;</span>
            </div>
            <div class="citation-body">
              <div class="citation-chunk" id="${chunkId}">"${chunkText}${r.text.length > 400 ? "\u2026" : ""}"</div>
              <button class="citation-show-more" onclick="event.stopPropagation();toggleChunk(event,'${chunkId}')">Show more</button>
            </div>
          </div>`;
  });
  return html;
}
function toggleCitation(card) {
  card.classList.toggle("expanded");
}
function toggleChunk(e, id) {
  e.stopPropagation();
  const el = byId(id);
  el.classList.toggle("show-all");
  e.target.textContent = el.classList.contains("show-all") ? "Show less" : "Show more";
}
function revealCitations(citationsEl) {
  citationsEl.style.display = "block";
  citationsEl.classList.remove("reveal");
  void citationsEl.offsetWidth;
  citationsEl.classList.add("reveal");
}
function initCitations() {
  window["toggleCitation"] = toggleCitation;
  window["toggleChunk"] = toggleChunk;
}

// src/api.ts
function getSettings() {
  const raw = localStorage.getItem("nc_settings");
  return raw ? JSON.parse(raw) : {};
}
function authHeaders() {
  const s = getSettings();
  const token = s.auth_token || "";
  const h = { "Content-Type": "application/json" };
  if (token) {
    h["Authorization"] = `Bearer ${token}`;
    h["x-api-key"] = token;
  }
  return h;
}
function apiBase() {
  const s = getSettings();
  const ep = (s.api_endpoint || "").trim();
  return ep ? ep.replace(/\/$/, "") : "";
}
async function api(method, path, body) {
  const url = apiBase() + path;
  const opts = { method, headers: authHeaders() };
  if (body !== void 0) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const json = await res.json();
  if (!res.ok || !json.ok) {
    throw new Error(json.error?.message || `HTTP ${res.status}`);
  }
  return json.data;
}

// src/contextWindow.ts
function updateContextIndicator(pct, bd) {
  const breakdown = {
    system: bd?.system ?? 0,
    memory: bd?.memory ?? 0,
    chunks: bd?.chunks ?? 0,
    query: bd?.query ?? 0
  };
  const chip = byId("ctxChip");
  byId("ctxBarFill").style.width = Math.min(pct, 100) + "%";
  byId("ctxPct").textContent = "~" + Math.round(pct) + "%";
  chip.classList.remove("warn", "crit");
  if (pct >= 95) chip.classList.add("crit");
  else if (pct >= 80) chip.classList.add("warn");
  const fmt = (n) => n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
  byId("ttSystem").textContent = fmt(breakdown.system) + " tok";
  byId("ttMemory").textContent = fmt(breakdown.memory) + " tok";
  byId("ttChunks").textContent = fmt(breakdown.chunks) + " tok";
  byId("ttQuery").textContent = fmt(breakdown.query) + " tok";
  const total = breakdown.system + breakdown.memory + breakdown.chunks + breakdown.query;
  byId("ttTotal").textContent = fmt(total) + " tok";
  byId("ctxCompactBtn").style.display = pct >= 95 ? "block" : "none";
}
function initContextIndicator() {
  byId("ctxCompactBtn").addEventListener("click", async () => {
    if (!state.activeConversationId) return;
    try {
      await api("POST", `/console/conversations/${state.activeConversationId}/compact`);
      showToast("Conversation compacted");
      updateContextIndicator(0);
    } catch (err) {
      showToast("Compact failed: " + String(err));
    }
  });
  byId("ctxChip").addEventListener("click", () => {
    byId("ctxChip").classList.toggle("tooltip-open");
  });
}

// src/scrollFab.ts
function scrollToBottom() {
  if (!state.userScrolledUp) refs.thread.scrollTop = refs.thread.scrollHeight;
}
function initScrollFab() {
  refs.thread.addEventListener("scroll", () => {
    const atBottom = refs.thread.scrollHeight - refs.thread.scrollTop - refs.thread.clientHeight < 80;
    state.userScrolledUp = !atBottom;
    refs.fab.classList.toggle("visible", state.userScrolledUp);
  });
  refs.fab.addEventListener("click", () => {
    refs.thread.scrollTop = refs.thread.scrollHeight;
  });
}

// src/sidebar.ts
function isDesktop() {
  return window.innerWidth > 1024;
}
function showPanel(panelId) {
  document.querySelectorAll(".sidebar-panel").forEach(
    (p) => p.classList.remove("active")
  );
  if (panelId) document.getElementById(panelId)?.classList.add("active");
}
function setNavActive(el) {
  document.querySelectorAll(".sidebar-nav-item").forEach(
    (n) => n.classList.remove("active")
  );
  el.classList.add("active");
  if (!refs.sidebar.classList.contains("collapsed")) showPanel(el.dataset.panel);
  if (!isDesktop()) closeSidebar();
}
function toggleSidebarCollapse() {
  refs.sidebar.classList.toggle("collapsed");
  byId("sidebarCollapseBtn").innerHTML = refs.sidebar.classList.contains("collapsed") ? "&#8250;" : "&#8249;";
  if (refs.sidebar.classList.contains("collapsed")) {
    document.querySelectorAll(".sidebar-panel").forEach(
      (p) => p.classList.remove("active")
    );
  } else {
    const activeNav = refs.sidebar.querySelector(".sidebar-nav-item.active");
    if (activeNav) showPanel(activeNav.dataset.panel);
  }
}
function openSidebar() {
  if (isDesktop()) {
    refs.sidebar.classList.remove("collapsed");
    byId("sidebarCollapseBtn").innerHTML = "&#8249;";
    const activeNav = refs.sidebar.querySelector(".sidebar-nav-item.active");
    if (activeNav) showPanel(activeNav.dataset.panel);
  } else {
    refs.sidebar.classList.add("open");
    refs.backdrop.classList.add("active");
  }
}
function closeSidebar() {
  if (isDesktop()) {
    refs.sidebar.classList.add("collapsed");
    byId("sidebarCollapseBtn").innerHTML = "&#8250;";
  } else {
    refs.sidebar.classList.remove("open");
    refs.backdrop.classList.remove("active");
  }
}
function initSidebar() {
  byId("toggleBtn").addEventListener(
    "click",
    () => refs.sidebar.classList.contains("open") ? closeSidebar() : openSidebar()
  );
  document.querySelectorAll(".sidebar-nav-item").forEach(
    (item) => item.addEventListener("click", () => setNavActive(item))
  );
  document.getElementById("sidebarCollapseBtn")?.addEventListener("click", toggleSidebarCollapse);
  window.addEventListener("resize", () => {
    if (isDesktop()) {
      refs.sidebar.classList.remove("open");
      refs.backdrop.classList.remove("active");
    }
  });
  let touchStartX = 0;
  document.addEventListener(
    "touchstart",
    (e) => {
      touchStartX = e.touches[0].clientX;
    },
    { passive: true }
  );
  document.addEventListener(
    "touchend",
    (e) => {
      const dx = e.changedTouches[0].clientX - touchStartX;
      if (!isDesktop()) {
        if (dx > 60 && touchStartX < 30) openSidebar();
        if (dx < -60 && refs.sidebar.classList.contains("open")) closeSidebar();
      }
    },
    { passive: true }
  );
}

// src/settings.ts
var mq = window.matchMedia("(prefers-color-scheme: light)");
function applyThemeToDOM(val) {
  const resolved = val === "system" ? mq.matches ? "light" : "dark" : val;
  document.documentElement.dataset.theme = resolved;
  document.querySelectorAll(".theme-opt").forEach((el) => {
    el.classList.toggle("active", el.dataset.themeVal === val);
  });
}
function setTheme(val) {
  applyThemeToDOM(val);
  localStorage.setItem("nc_theme", val);
}
var PRESETS = {
  balanced: { searchLimit: 10, rerankTopK: 5 },
  precise: { searchLimit: 8, rerankTopK: 3 },
  broad: { searchLimit: 25, rerankTopK: 10 },
  fast: { searchLimit: 5, rerankTopK: 2 }
};
function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  byId("searchLimit").value = String(p.searchLimit);
  byId("searchLimitVal").textContent = String(p.searchLimit);
  byId("rerankTopK").value = String(p.rerankTopK);
  byId("rerankVal").textContent = String(p.rerankTopK);
}
function openSettings() {
  refs.settingsOverlay.classList.add("open");
  refs.settingsPanel.classList.add("open");
  loadSettings();
}
function closeSettings() {
  refs.settingsOverlay.classList.remove("open");
  refs.settingsPanel.classList.remove("open");
}
function saveSettings() {
  const s = {
    theme: localStorage.getItem("nc_theme") || "dark",
    preset: byId("presetSelect").value,
    searchLimit: byId("searchLimit").value,
    rerankTopK: byId("rerankTopK").value,
    streaming: byId("streamingToggle").checked,
    memory_enabled: byId("memoryToggle").checked,
    citations: byId("citationsToggle").checked,
    api_endpoint: byId("apiEndpoint").value.trim(),
    auth_token: byId("apiToken").value.trim()
  };
  localStorage.setItem("nc_settings", JSON.stringify(s));
  closeSettings();
  showToast("Settings saved");
}
function loadSettings() {
  const s = getSettings();
  const theme = localStorage.getItem("nc_theme") || s.theme || "dark";
  applyThemeToDOM(theme);
  if (s.preset) byId("presetSelect").value = s.preset;
  if (s.searchLimit) {
    byId("searchLimit").value = s.searchLimit;
    byId("searchLimitVal").textContent = s.searchLimit;
  }
  if (s.rerankTopK) {
    byId("rerankTopK").value = s.rerankTopK;
    byId("rerankVal").textContent = s.rerankTopK;
  }
  if (s.streaming !== void 0) byId("streamingToggle").checked = s.streaming;
  if (s.memory_enabled !== void 0) byId("memoryToggle").checked = s.memory_enabled;
  if (s.citations !== void 0) byId("citationsToggle").checked = s.citations;
  if (s.api_endpoint) byId("apiEndpoint").value = s.api_endpoint;
  if (s.auth_token) byId("apiToken").value = s.auth_token;
}
function resetSettings() {
  localStorage.removeItem("nc_settings");
  localStorage.removeItem("nc_theme");
  applyThemeToDOM("dark");
  byId("presetSelect").value = "balanced";
  applyPreset("balanced");
  byId("streamingToggle").checked = true;
  byId("memoryToggle").checked = true;
  byId("citationsToggle").checked = true;
  byId("apiEndpoint").value = "";
  byId("apiToken").value = "";
  showToast("Settings reset to defaults");
}
function initSettings() {
  mq.addEventListener("change", () => {
    if (localStorage.getItem("nc_theme") === "system") applyThemeToDOM("system");
  });
  document.querySelectorAll(".theme-opt").forEach((el) => {
    el.addEventListener("click", () => setTheme(el.dataset.themeVal || "dark"));
  });
  document.getElementById("presetSelect")?.addEventListener("change", (e) => {
    applyPreset(e.target.value);
  });
  document.getElementById("searchLimit")?.addEventListener("input", (e) => {
    byId("searchLimitVal").textContent = e.target.value;
  });
  document.getElementById("rerankTopK")?.addEventListener("input", (e) => {
    byId("rerankVal").textContent = e.target.value;
  });
  document.getElementById("settingsBtn")?.addEventListener("click", openSettings);
  document.getElementById("customizeOpenSettings")?.addEventListener("click", openSettings);
  refs.settingsOverlay.addEventListener("click", closeSettings);
  document.getElementById("settingsClose")?.addEventListener("click", closeSettings);
  document.getElementById("settingsSaveBtn")?.addEventListener("click", saveSettings);
  document.getElementById("settingsResetBtn")?.addEventListener("click", resetSettings);
  applyThemeToDOM(localStorage.getItem("nc_theme") || "dark");
}

// src/markdown.ts
import { marked } from "marked";
import DOMPurify from "dompurify";
marked.use({
  gfm: true,
  breaks: false,
  renderer: {
    code({ text, lang }) {
      const langLabel = escHtml(lang ?? "code");
      const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return [
        `<div class="code-block-wrap">`,
        `<div class="code-block-header">`,
        `<span>${langLabel}</span>`,
        `<button class="copy-code-btn">&#128203; Copy</button>`,
        `</div>`,
        `<div class="code-block">${escaped}</div>`,
        `</div>`
      ].join("");
    }
  }
});
function isListMarker(word) {
  if (!word.endsWith(".")) return false;
  const n = Number(word.slice(0, -1));
  return Number.isInteger(n) && n > 0;
}
function splitInlineList(line) {
  const words = line.split(" ");
  if (words.length < 3) return line;
  const lineStartsWithBullet = words[0] === "-" || words[0] === "*";
  const subLines = [];
  let current = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const isBulletCont = lineStartsWithBullet && i > 0 && (w === "-" || w === "*");
    const isNumberedCont = i > 0 && isListMarker(w);
    if (current.length > 0 && (isBulletCont || isNumberedCont)) {
      subLines.push(current.join(" "));
      current = [w];
    } else {
      current.push(w);
    }
  }
  if (current.length) subLines.push(current.join(" "));
  return subLines.length > 1 ? subLines.join("\n") : line;
}
function normalizeMarkdown(raw) {
  const segments = raw.split(/(```[\s\S]*?```)/);
  return segments.map((seg, i) => {
    if (i % 2 === 1) return seg;
    return seg.split("\n").map(splitInlineList).join("\n");
  }).join("");
}
function parseMarkdown(raw) {
  return DOMPurify.sanitize(marked.parse(normalizeMarkdown(raw)));
}

// src/thread.ts
function setEmptyState(visible) {
  const el = document.getElementById("threadEmpty");
  if (el) el.style.display = visible ? "" : "none";
}
function appendUserMsg(text) {
  setEmptyState(false);
  const ts = fmtTime(Date.now());
  const group = document.createElement("div");
  group.className = "msg-group";
  group.innerHTML = `
        <div class="msg-row user">
          <div class="avatar user-av">U</div>
          <div class="bubble-wrap">
            <div class="bubble">${escHtml(text)}</div>
            <div class="msg-actions">
              <button class="msg-action-btn" onclick="copyMsg(this,'${escHtml(text)}')" >&#128203; Copy</button>
            </div>
            <div class="msg-meta">${ts}</div>
          </div>
        </div>`;
  refs.thread.appendChild(group);
  scrollToBottom();
}
function appendPendingAssistant() {
  setEmptyState(false);
  const group = document.createElement("div");
  group.className = "msg-group";
  group.innerHTML = `
        <div class="msg-row assistant">
          <div class="avatar ai-av">AI</div>
          <div class="bubble-wrap">
            <div class="typing-indicator">
              <div class="typing-dot"></div>
              <div class="typing-dot"></div>
              <div class="typing-dot"></div>
            </div>
            <div class="bubble" style="display:none"></div>
            <div class="citations" style="display:none"></div>
            <div class="msg-actions" style="display:none">
              <button class="msg-action-btn">&#128203; Copy</button>
              <button class="msg-action-btn">&#128257; Regenerate</button>
            </div>
            <div class="msg-meta" style="display:none"></div>
          </div>
        </div>`;
  refs.thread.appendChild(group);
  scrollToBottom();
  const bw = group.querySelector(".bubble-wrap");
  const bubbleEl = bw.querySelector(".bubble");
  const typingEl = bw.querySelector(".typing-indicator");
  const citationsEl = bw.querySelector(".citations");
  const actionsEl = bw.querySelector(".msg-actions");
  const metaEl = bw.querySelector(".msg-meta");
  const copyBtn = actionsEl.querySelector("button");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => copyMsg(copyBtn, bubbleEl.innerText));
  }
  return { group, bubbleEl, typingEl, citationsEl, actionsEl, metaEl };
}
function appendSystemMsg(text) {
  const div = document.createElement("div");
  div.className = "msg-group";
  div.innerHTML = `<div class="msg-row assistant"><div class="avatar ai-av">&#9432;</div><div class="bubble-wrap"><div class="bubble">${escHtml(text)}</div></div></div>`;
  refs.thread.appendChild(div);
  scrollToBottom();
}
function appendErrorMsg(text) {
  const div = document.createElement("div");
  div.className = "msg-group";
  div.innerHTML = `<div class="msg-row assistant"><div class="avatar ai-av">!</div><div class="bubble-wrap"><div class="bubble error-bubble">&#9888; ${escHtml(text)}</div></div></div>`;
  refs.thread.appendChild(div);
  scrollToBottom();
}

// src/user-types.ts
function sourceRefToChunkResult(ref) {
  return {
    text: ref.text ?? "",
    score: ref.score ?? 0,
    metadata: {
      source: ref.source ?? "",
      source_uri: ref.source_uri ?? "",
      section: ref.section ?? "",
      original_char_start: ref.original_char_start,
      original_char_end: ref.original_char_end
    }
  };
}

// src/conversations.ts
function renderConversationList(convs) {
  const container = byId("convList");
  if (!convs.length) {
    container.innerHTML = `<div class="conv-list-empty">No conversations yet.<br>Start one below!</div>`;
    return;
  }
  const groups = {};
  convs.forEach((c) => {
    const label = fmtRelative(c.updated_at_ms ?? Date.now());
    if (!groups[label]) groups[label] = [];
    groups[label].push(c);
  });
  let html = "";
  for (const [label, items] of Object.entries(groups)) {
    html += `<div class="conv-section-label">${escHtml(label)}</div>`;
    items.forEach((c) => {
      const isActive = c.conversation_id === state.activeConversationId;
      const title = escHtml(c.title || c.conversation_id);
      html += `
              <div class="conv-item-wrap">
                <div class="conv-item${isActive ? " active" : ""}" data-conv-id="${escHtml(c.conversation_id)}" title="${title}">
                  <span class="dot"></span>${title}
                </div>
                <button class="conv-item-del" data-conv-id="${escHtml(c.conversation_id)}" title="Delete">&#10005;</button>
              </div>`;
    });
  }
  container.innerHTML = html;
  container.querySelectorAll(".conv-item").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.dataset.convId;
      if (id) void selectConversation(id);
    });
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const id = el.dataset.convId;
      if (!id) return;
      const conv = convs.find((c) => c.conversation_id === id);
      showConvCtxMenu(e.clientX, e.clientY, id, conv?.title || "");
    });
  });
  container.querySelectorAll(".conv-item-del").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset.convId;
      if (id) void deleteConversation(id);
    });
  });
}
async function loadConversations() {
  try {
    const data = await api(
      "GET",
      "/console/conversations?limit=50"
    );
    renderConversationList(data.conversations || []);
  } catch {
  }
}
async function selectConversation(id) {
  if (state.isStreaming) {
    state.streamAbortCtrl?.abort();
    state.isStreaming = false;
  }
  setActiveConversation(id);
  byId("convList").querySelectorAll(".conv-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.convId === id);
  });
  await loadConversationHistory(id);
}
async function loadConversationHistory(id) {
  const convId = id ?? state.activeConversationId;
  if (!convId) return;
  try {
    const data = await api("GET", `/console/conversations/${convId}/history?limit=100`);
    refs.thread.innerHTML = "";
    if (!data.turns || !data.turns.length) {
      refs.thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#128172;</div><div class="thread-empty-title">Empty conversation</div><div class="thread-empty-sub">Send a message to start the conversation.</div></div>`;
      return;
    }
    data.turns.forEach((turn) => {
      if (turn.role === "user") {
        appendUserMsg(turn.content);
      } else {
        setEmptyState(false);
        const group = document.createElement("div");
        group.className = "msg-group";
        const ts = fmtTime(turn.timestamp_ms ?? Date.now());
        const sources = turn.sources ?? [];
        const citationsHtml = sources.length ? `<div class="citations">${buildCitationsHtml(sources.map(sourceRefToChunkResult))}</div>` : "";
        group.innerHTML = `
                    <div class="msg-row assistant">
                      <div class="avatar ai-av">AI</div>
                      <div class="bubble-wrap">
                        <div class="bubble">${parseMarkdown(turn.content)}</div>
                        ${citationsHtml}
                        <div class="msg-actions">
                          <button class="msg-action-btn">&#128203; Copy</button>
                        </div>
                        <div class="msg-meta">${ts}</div>
                      </div>
                    </div>`;
        const copyBtn = group.querySelector(".msg-action-btn");
        if (copyBtn) {
          const bubbleEl = group.querySelector(".bubble");
          copyBtn.addEventListener("click", () => copyMsg(copyBtn, bubbleEl.innerText));
        }
        refs.thread.appendChild(group);
      }
    });
    const activeConv = document.querySelector(`.conv-item[data-conv-id="${convId}"]`);
    if (activeConv) {
      byId("convTitle").textContent = activeConv.title ?? activeConv.textContent?.trim() ?? "Conversation";
    }
    setTimeout(() => {
      refs.thread.scrollTop = refs.thread.scrollHeight;
    }, 50);
  } catch (err) {
    appendErrorMsg("Failed to load conversation history: " + String(err));
  }
}
function createNewConversation() {
  setActiveConversation(null);
  refs.thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#128172;</div><div class="thread-empty-title">New conversation</div><div class="thread-empty-sub">Send a message to get started.</div></div>`;
  byId("convTitle").textContent = "New conversation";
  byId("convList").querySelectorAll(".conv-item").forEach((el) => {
    el.classList.remove("active");
  });
  const input = document.getElementById("msgInput");
  if (input) input.focus();
}
async function deleteConversation(id) {
  try {
    await api("DELETE", `/console/conversations/${id}`);
    if (state.activeConversationId === id) {
      setActiveConversation(null);
      refs.thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#9670;</div><div class="thread-empty-title">RagWeave</div><div class="thread-empty-sub">Ask anything \u2014 I'll search your knowledge base and generate a response with sources.</div></div>`;
      byId("convTitle").textContent = "RagWeave";
    }
    await loadConversations();
    showToast("Conversation deleted");
  } catch {
    showToast("Failed to delete conversation");
  }
}
function updateConvTitle() {
  if (!state.activeConversationId) return;
  const item = byId("convList").querySelector(
    `.conv-item[data-conv-id="${state.activeConversationId}"]`
  );
  if (item) {
    byId("convTitle").textContent = item.textContent?.trim().replace(/^●/, "").trim() ?? "Conversation";
  }
}
function hideConvCtxMenu() {
  const menu = byId("convCtxMenu");
  menu.classList.remove("open");
  menu.setAttribute("aria-hidden", "true");
  state.convMenuTargetId = null;
}
function showConvCtxMenu(x, y, id, title) {
  const menu = byId("convCtxMenu");
  state.convMenuTargetId = id;
  state.convMenuTargetTitle = title;
  menu.style.left = "-9999px";
  menu.style.top = "-9999px";
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  const rect = menu.getBoundingClientRect();
  const maxX = window.innerWidth - rect.width - 8;
  const maxY = window.innerHeight - rect.height - 8;
  menu.style.left = `${Math.max(8, Math.min(x, maxX))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, maxY))}px`;
}
function openRenameModal(id, currentTitle) {
  state.renameTargetId = id;
  const overlay = byId("renameModal");
  const input = byId("renameInput");
  input.value = currentTitle || "";
  overlay.classList.add("open");
  overlay.setAttribute("aria-hidden", "false");
  setTimeout(() => {
    input.focus();
    input.select();
  }, 40);
}
function closeRenameModal() {
  const overlay = byId("renameModal");
  overlay.classList.remove("open");
  overlay.setAttribute("aria-hidden", "true");
  state.renameTargetId = null;
}
async function submitRename() {
  const id = state.renameTargetId;
  if (!id) return;
  const input = byId("renameInput");
  const trimmed = input.value.trim();
  if (!trimmed) {
    input.focus();
    return;
  }
  closeRenameModal();
  try {
    await api("PATCH", `/console/conversations/${encodeURIComponent(id)}`, { title: trimmed });
    if (state.activeConversationId === id) {
      byId("convTitle").textContent = trimmed;
    }
    await loadConversations();
    showToast("Conversation renamed");
  } catch (err) {
    showToast("Failed to rename: " + String(err));
  }
}
function initConversations() {
  byId("convCtxMenu").querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = state.convMenuTargetId;
      const title = state.convMenuTargetTitle;
      const action = btn.dataset.action;
      hideConvCtxMenu();
      if (!id) return;
      if (action === "rename") openRenameModal(id, title);
      else if (action === "delete") void deleteConversation(id);
    });
  });
  document.addEventListener("mousedown", (e) => {
    const menu = byId("convCtxMenu");
    if (!menu.classList.contains("open")) return;
    if (e.target instanceof Node && menu.contains(e.target)) return;
    hideConvCtxMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideConvCtxMenu();
      if (byId("renameModal").classList.contains("open")) closeRenameModal();
    }
  });
  window.addEventListener("resize", hideConvCtxMenu);
  window.addEventListener("scroll", hideConvCtxMenu, true);
  byId("renameCancel").addEventListener("click", closeRenameModal);
  byId("renameSave").addEventListener("click", () => void submitRename());
  byId("renameInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void submitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeRenameModal();
    }
  });
  byId("renameModal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeRenameModal();
  });
  byId("newChatBtn").addEventListener("click", createNewConversation);
  document.getElementById("convSearch")?.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    byId("convList").querySelectorAll(".conv-item-wrap").forEach((wrap) => {
      const text = wrap.querySelector(".conv-item")?.textContent?.toLowerCase() || "";
      wrap.style.display = text.includes(q) ? "" : "none";
    });
  });
}

// src/streaming.ts
function buildQueryBody(queryText) {
  const s = getSettings();
  return {
    query: queryText,
    search_limit: parseInt(String(s.searchLimit ?? "10"), 10),
    rerank_top_k: parseInt(String(s.rerankTopK ?? "5"), 10),
    memory_enabled: s.memory_enabled !== false,
    conversation_id: state.activeConversationId ?? void 0
  };
}
async function streamQuery(queryText) {
  if (state.isStreaming) {
    state.streamAbortCtrl?.abort();
  }
  state.isStreaming = true;
  state.streamAbortCtrl = new AbortController();
  appendUserMsg(queryText);
  const { bubbleEl, typingEl, citationsEl, actionsEl, metaEl } = appendPendingAssistant();
  const url = apiBase() + "/query/stream";
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(buildQueryBody(queryText)),
      signal: state.streamAbortCtrl.signal
    });
  } catch (err) {
    typingEl.remove();
    bubbleEl.innerHTML = "&#9888; Network error: " + escHtml(String(err));
    bubbleEl.classList.add("error-bubble");
    bubbleEl.style.display = "block";
    state.isStreaming = false;
    return;
  }
  if (!response.ok || !response.body) {
    typingEl.remove();
    bubbleEl.innerHTML = `&#9888; Stream error (HTTP ${response.status})`;
    bubbleEl.classList.add("error-bubble");
    bubbleEl.style.display = "block";
    state.isStreaming = false;
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let started = false;
  let errorShown = false;
  let pendingClarification = "";
  let renderRaf = 0;
  const flushRender = () => {
    renderRaf = 0;
    bubbleEl.innerHTML = parseMarkdown(answer);
  };
  const scheduleRender = () => {
    if (renderRaf) return;
    renderRaf = requestAnimationFrame(flushRender);
  };
  const cancelRender = () => {
    if (renderRaf) {
      cancelAnimationFrame(renderRaf);
      renderRaf = 0;
    }
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const evt of events) {
        const lines = evt.split("\n");
        const evtType = (lines.find((l) => l.startsWith("event: ")) ?? "").slice(7);
        const dataRaw = (lines.find((l) => l.startsWith("data: ")) ?? "data: {}").slice(6);
        let data;
        try {
          data = JSON.parse(dataRaw);
        } catch {
          data = {};
        }
        if (evtType === "token") {
          if (!started) {
            typingEl.style.display = "none";
            bubbleEl.style.display = "block";
            bubbleEl.classList.add("streaming");
            started = true;
          }
          answer += data.token || "";
          scheduleRender();
          scrollToBottom();
        } else if (evtType === "retrieval") {
          const cid = String(data.conversation_id ?? "").trim();
          if (cid) setActiveConversation(cid);
          const clar = String(data.clarification_message ?? "").trim();
          if (clar) pendingClarification = clar;
          const tb = data.token_budget;
          if (tb?.usage_percent !== void 0) {
            const bd = tb.breakdown ?? {};
            updateContextIndicator(tb.usage_percent * 100, {
              system: Number(bd.system_tokens ?? bd.system ?? 0),
              memory: Number(bd.memory_tokens ?? bd.memory ?? 0),
              chunks: Number(bd.chunk_tokens ?? bd.chunks ?? 0),
              query: Number(bd.query_tokens ?? bd.query ?? 0)
            });
          }
          const results = data.results ?? [];
          const showCitations = byId("citationsToggle").checked;
          if (showCitations && results.length) {
            citationsEl.innerHTML = buildCitationsHtml(results);
          }
        } else if (evtType === "error") {
          errorShown = true;
          cancelRender();
          bubbleEl.classList.remove("streaming");
          typingEl.style.display = "none";
          bubbleEl.innerHTML = "&#9888; " + escHtml(String(data.message ?? "Unknown error"));
          bubbleEl.classList.add("error-bubble");
          bubbleEl.style.display = "block";
          scrollToBottom();
        } else if (evtType === "done") {
          const cid = String(data.conversation_id ?? "").trim();
          if (cid) setActiveConversation(cid);
          cancelRender();
          bubbleEl.classList.remove("streaming");
          typingEl.style.display = "none";
          if (!errorShown) {
            if (!started) {
              const msg = pendingClarification || "I couldn't find relevant information for that query. Could you rephrase your question or provide more details?";
              bubbleEl.innerHTML = parseMarkdown(msg);
              bubbleEl.style.display = "block";
            } else {
              bubbleEl.innerHTML = parseMarkdown(answer);
              bubbleEl.style.display = "block";
            }
          }
          const showCitations = byId("citationsToggle").checked;
          if (showCitations && citationsEl.innerHTML) {
            revealCitations(citationsEl);
          }
          actionsEl.style.display = "flex";
          metaEl.textContent = fmtTime(Date.now());
          metaEl.style.display = "block";
          scrollToBottom();
          await loadConversations();
          updateConvTitle();
        }
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      appendErrorMsg("Stream interrupted: " + String(err));
    }
  } finally {
    cancelRender();
    bubbleEl.classList.remove("streaming");
  }
  state.isStreaming = false;
}
async function nonStreamQuery(queryText) {
  appendUserMsg(queryText);
  const { bubbleEl, typingEl, citationsEl, actionsEl, metaEl } = appendPendingAssistant();
  try {
    const data = await api("POST", "/console/query", buildQueryBody(queryText));
    const cid = String(data.conversation_id ?? "").trim();
    if (cid) setActiveConversation(cid);
    typingEl.style.display = "none";
    const answer = data.generated_answer ?? data.clarification_message ?? "No response.";
    bubbleEl.innerHTML = parseMarkdown(answer);
    bubbleEl.style.display = "block";
    const tb = data.token_budget;
    if (tb?.usage_percent !== void 0) {
      const bd = tb.breakdown ?? {};
      updateContextIndicator(tb.usage_percent * 100, {
        system: Number(bd.system_tokens ?? 0),
        memory: Number(bd.memory_tokens ?? 0),
        chunks: Number(bd.chunk_tokens ?? 0),
        query: Number(bd.query_tokens ?? 0)
      });
    }
    const showCitations = byId("citationsToggle").checked;
    const results = data.results ?? [];
    if (showCitations && results.length) {
      citationsEl.innerHTML = buildCitationsHtml(results);
      revealCitations(citationsEl);
    }
    actionsEl.style.display = "flex";
    metaEl.textContent = fmtTime(Date.now());
    metaEl.style.display = "block";
    scrollToBottom();
    await loadConversations();
    updateConvTitle();
  } catch (err) {
    typingEl.style.display = "none";
    bubbleEl.innerHTML = "&#9888; " + escHtml(String(err));
    bubbleEl.classList.add("error-bubble");
    bubbleEl.style.display = "block";
  }
}
async function sendQuery(text) {
  const s = getSettings();
  const useStreaming = s.streaming !== false;
  if (useStreaming) await streamQuery(text);
  else await nonStreamQuery(text);
}

// src/slash.ts
function renderSlashDropdown(cmds) {
  const container = byId("slashItems");
  container.innerHTML = cmds.map(
    (c) => `<div class="slash-item" data-cmd="/${escHtml(c.name)}"><span class="slash-cmd">/${escHtml(c.name)}</span><span class="slash-desc">${escHtml(c.description)}</span></div>`
  ).join("");
  state.allSlashItems = Array.from(container.querySelectorAll(".slash-item"));
  state.allSlashItems.forEach(
    (item) => item.addEventListener("click", () => executeCmd(item.dataset.cmd || ""))
  );
}
function renderCmdPicker(cmds) {
  const container = byId("cmdPickerBody");
  const grouped = {};
  cmds.forEach((c) => {
    const cat = c.category || "General";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(c);
  });
  let html = "";
  for (const [cat, items] of Object.entries(grouped)) {
    html += `<div class="cmd-group-label">${escHtml(cat)}</div>`;
    items.forEach((c) => {
      html += `<div class="cmd-picker-item" data-cmd="/${escHtml(c.name)}"><span class="cmd-picker-icon">&#47;</span><span class="cmd-picker-name">/${escHtml(c.name)}</span><span class="cmd-picker-desc">${escHtml(c.description)}</span></div>`;
    });
  }
  container.innerHTML = html;
  state.allPickerItems = Array.from(container.querySelectorAll(".cmd-picker-item"));
  state.allPickerItems.forEach(
    (item) => item.addEventListener("click", () => executePicker(item))
  );
}
async function loadCommands() {
  try {
    const data = await api("GET", "/console/commands?mode=query");
    state.dynamicCmds = data.commands || [];
    renderSlashDropdown(state.dynamicCmds);
    renderCmdPicker(state.dynamicCmds);
  } catch {
  }
}
function closeDropdown() {
  refs.dropdown.classList.remove("open");
}
function setSelected(i) {
  const vis = state.allSlashItems.filter((x) => x.style.display !== "none");
  if (!vis.length) return;
  state.slashSelIdx = (i + vis.length) % vis.length;
  vis.forEach((el, j) => el.classList.toggle("selected", j === state.slashSelIdx));
}
function executeCmd(cmd) {
  refs.ta.value = cmd + " ";
  refs.ta.focus();
  refs.ta.style.height = "auto";
  closeDropdown();
}
function handleSlashInput() {
  const val = refs.ta.value;
  if (!val.startsWith("/")) {
    closeDropdown();
    return;
  }
  const q = val.slice(1).toLowerCase();
  let vis = 0;
  state.allSlashItems.forEach((item) => {
    const cmdAttr = (item.dataset.cmd || "").toLowerCase();
    const descEl = item.querySelector(".slash-desc");
    const descText = descEl ? descEl.textContent?.toLowerCase() || "" : "";
    const match = cmdAttr.includes(q) || descText.includes(q);
    item.style.display = match ? "" : "none";
    if (match) vis++;
  });
  if (!vis) {
    closeDropdown();
    return;
  }
  refs.dropdown.classList.add("open");
  setSelected(0);
}
function setPickerSelected(idx) {
  if (!state.allPickerItems.length) return;
  state.pickerIdx = (idx + state.allPickerItems.length) % state.allPickerItems.length;
  state.allPickerItems.forEach((el, i) => el.classList.toggle("selected", i === state.pickerIdx));
  state.allPickerItems[state.pickerIdx]?.scrollIntoView({ block: "nearest" });
}
function executePicker(item) {
  const cmd = item.dataset.cmd || "";
  closeCmdPicker();
  refs.ta.value = cmd + " ";
  refs.ta.focus();
  refs.ta.style.height = "auto";
  closeDropdown();
}
function closeCmdPicker() {
  refs.cmdPicker.classList.remove("open");
  refs.cmdBtn.classList.remove("active");
}
async function submitSlashCommand(text) {
  const trimmed = text.trim();
  const spaceIdx = trimmed.indexOf(" ");
  const commandName = (spaceIdx === -1 ? trimmed.slice(1) : trimmed.slice(1, spaceIdx)).toLowerCase();
  const arg = spaceIdx === -1 ? "" : trimmed.slice(spaceIdx + 1).trim();
  appendUserMsg(trimmed);
  try {
    const result = await api("POST", "/console/command", {
      mode: "query",
      command: commandName,
      arg: arg || void 0,
      state: { conversation_id: state.activeConversationId ?? void 0 }
    });
    const action = String(result.action ?? "noop");
    if (action === "run_stream_query") {
      await streamQuery(arg || commandName);
    } else if (action === "run_non_stream_query") {
      await nonStreamQuery(arg || commandName);
    } else if (action === "new_conversation") {
      const conv = result.data?.conversation;
      if (conv?.conversation_id) setActiveConversation(conv.conversation_id);
      else createNewConversation();
      await loadConversations();
    } else if (action === "switch_conversation") {
      const cid = String(result.data?.conversation_id ?? arg).trim();
      if (cid) await selectConversation(cid);
    } else if (action === "list_conversations") {
      await loadConversations();
      appendSystemMsg("Conversation list refreshed.");
    } else if (action === "show_history") {
      await loadConversationHistory();
    } else if (action === "compact_conversation") {
      const summary = String(result.data?.summary ?? "").trim();
      appendSystemMsg(summary ? `Compacted. Summary:

${summary}` : "Conversation compacted.");
      await loadConversations();
    } else if (action === "delete_conversation") {
      const cid = String(result.data?.conversation_id ?? "").trim();
      if (cid) await deleteConversation(cid);
    } else if (action === "clear_view") {
      refs.thread.innerHTML = "";
      setEmptyState(true);
    } else if (action === "refresh_health") {
      const h = result.data?.health;
      const status = h ? JSON.stringify(h, null, 2) : "Health data unavailable";
      appendSystemMsg("Health:\n```json\n" + status + "\n```");
    } else if (action === "render_help") {
      const cmds = result.data?.commands;
      if (cmds?.length) {
        const lines = cmds.map((c) => `**/${c.name}** \u2014 ${c.description}`).join("\n");
        appendSystemMsg("Available commands:\n\n" + lines);
      }
    } else {
      const msg = String(result.message ?? "Command executed.");
      if (msg) appendSystemMsg(msg);
    }
  } catch (err) {
    appendErrorMsg("Command failed: " + String(err));
  }
}

// src/attachments.ts
function renderChips() {
  const container = byId("attachChips");
  container.innerHTML = "";
  state.attachments.forEach((a) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    chip.innerHTML = `<span class="attach-chip-icon">${a.icon}</span><span class="attach-chip-label">${escHtml(a.label)}</span><button class="attach-chip-remove" title="Remove">&#215;</button>`;
    chip.querySelector(".attach-chip-remove")?.addEventListener(
      "click",
      () => removeChip(a.id)
    );
    container.appendChild(chip);
  });
}
function addChip(icon, label, id) {
  if (state.attachments.find((a) => a.id === id)) return;
  state.attachments.push({ id, icon, label });
  renderChips();
}
function removeChip(id) {
  state.attachments = state.attachments.filter((a) => a.id !== id);
  renderChips();
}
function closeAllPopovers() {
  refs.attachPopover.classList.remove("open");
  refs.webInputPanel.classList.remove("open");
  refs.kbPanel.classList.remove("open");
  refs.attachBtn.classList.remove("active");
}
function toggleAttachPopover() {
  const isOpen = refs.attachPopover.classList.contains("open");
  closeAllPopovers();
  closeCmdPickerExternal();
  if (!isOpen) {
    refs.attachPopover.classList.add("open");
    refs.attachBtn.classList.add("active");
  }
}
var closeCmdPickerExternal = () => {
};
function setCloseCmdPicker(fn) {
  closeCmdPickerExternal = fn;
}
function openWebInput() {
  closeAllPopovers();
  refs.webInputPanel.classList.add("open");
  setTimeout(() => document.getElementById("webUrlInput")?.focus(), 50);
}
function openKBSelect() {
  closeAllPopovers();
  refs.kbPanel.classList.add("open");
}
function triggerFileUpload() {
  closeAllPopovers();
  byId("fileInput").click();
}
function handleFileSelect(input) {
  if (!input.files) return;
  Array.from(input.files).forEach((file) => addChip("&#128196;", file.name, "file:" + file.name));
  input.value = "";
  showToast("File added to context");
}
function attachWebUrl() {
  const input = byId("webUrlInput");
  const url = input.value.trim();
  if (!url) return;
  try {
    new URL(url);
  } catch {
    showToast("Invalid URL");
    return;
  }
  addChip("&#127760;", new URL(url).hostname.replace("www.", ""), "web:" + url);
  input.value = "";
  refs.webInputPanel.classList.remove("open");
  showToast("Web page added to context");
}
function filterKB(q) {
  document.querySelectorAll(".kb-item").forEach((el) => {
    const name = el.querySelector(".kb-item-name")?.textContent?.toLowerCase() || "";
    el.style.display = name.includes(q.toLowerCase()) ? "" : "none";
  });
}
function attachKBDocs() {
  document.querySelectorAll("#kbList input[type=checkbox]:checked").forEach((cb) => {
    addChip("&#128218;", cb.value, "kb:" + cb.value);
    cb.checked = false;
  });
  refs.kbPanel.classList.remove("open");
  showToast("Documents added to context");
}
function initAttachments() {
  refs.attachBtn.addEventListener("click", toggleAttachPopover);
  document.getElementById("attachOptFile")?.addEventListener("click", triggerFileUpload);
  document.getElementById("attachOptWeb")?.addEventListener("click", openWebInput);
  document.getElementById("attachOptKB")?.addEventListener("click", openKBSelect);
  document.getElementById("fileInput")?.addEventListener("change", (e) => {
    handleFileSelect(e.target);
  });
  document.getElementById("webUrlInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attachWebUrl();
    if (e.key === "Escape") refs.webInputPanel.classList.remove("open");
  });
  document.getElementById("webAddBtn")?.addEventListener("click", attachWebUrl);
  document.getElementById("kbSearch")?.addEventListener(
    "input",
    (e) => filterKB(e.target.value)
  );
  document.getElementById("kbAddBtn")?.addEventListener("click", attachKBDocs);
  document.getElementById("kbPanelClose")?.addEventListener("click", closeAllPopovers);
  const win = window;
  win["removeChip"] = removeChip;
  win["openWebInput"] = openWebInput;
  win["openKBSelect"] = openKBSelect;
  win["triggerFileUpload"] = triggerFileUpload;
  win["filterKB"] = filterKB;
  win["attachKBDocs"] = attachKBDocs;
  win["attachWebUrl"] = attachWebUrl;
  win["handleFileSelect"] = handleFileSelect;
}

// src/input.ts
function toggleCmdPicker() {
  const isOpen = refs.cmdPicker.classList.contains("open");
  closeAllPopovers();
  if (isOpen) {
    closeCmdPicker();
  } else {
    refs.cmdPicker.classList.add("open");
    refs.cmdBtn.classList.add("active");
    setPickerSelected(0);
  }
}
function triggerSend() {
  const text = refs.ta.value.trim();
  if (!text || state.isStreaming) return;
  closeDropdown();
  refs.ta.value = "";
  refs.ta.style.height = "auto";
  if (text.startsWith("/")) {
    void submitSlashCommand(text);
  } else {
    void sendQuery(text);
  }
}
function initInput() {
  setCloseCmdPicker(closeCmdPicker);
  refs.ta.addEventListener("input", () => {
    refs.ta.style.height = "auto";
    refs.ta.style.height = Math.min(refs.ta.scrollHeight, 120) + "px";
    handleSlashInput();
  });
  refs.ta.addEventListener("keydown", (e) => {
    if (!refs.dropdown.classList.contains("open")) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        triggerSend();
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected(state.slashSelIdx + 1);
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected(state.slashSelIdx - 1);
    }
    if (e.key === "Tab" || e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const vis = state.allSlashItems.filter((x) => x.style.display !== "none");
      if (vis[state.slashSelIdx]) executeCmd(vis[state.slashSelIdx].dataset.cmd || "");
    }
    if (e.key === "Escape") closeDropdown();
  });
  byId("sendBtn").addEventListener("click", triggerSend);
  refs.cmdBtn.addEventListener("click", toggleCmdPicker);
  document.getElementById("cmdPickerClose")?.addEventListener("click", closeCmdPicker);
  document.addEventListener("keydown", (e) => {
    if (!refs.cmdPicker.classList.contains("open")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setPickerSelected(state.pickerIdx + 1);
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setPickerSelected(state.pickerIdx - 1);
    }
    if (e.key === "Enter") {
      e.preventDefault();
      executePicker(state.allPickerItems[state.pickerIdx]);
    }
    if (e.key === "Escape") closeCmdPicker();
  });
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!target.closest(".input-bar")) {
      closeAllPopovers();
      closeCmdPicker();
      closeDropdown();
      document.getElementById("ctxChip")?.classList.remove("tooltip-open");
    }
  });
}

// src/user-console.ts
document.addEventListener("DOMContentLoaded", () => {
  populateRefs();
  initToast();
  initCitations();
  initContextIndicator();
  initScrollFab();
  initSidebar();
  initSettings();
  initConversations();
  initAttachments();
  initInput();
  loadSettings();
  void Promise.all([loadCommands(), loadConversations()]).then(() => {
    if (state.activeConversationId) {
      void loadConversationHistory(state.activeConversationId);
    }
  });
  setTimeout(() => {
    refs.thread.scrollTop = refs.thread.scrollHeight;
  }, 100);
});
//# sourceMappingURL=user-console.js.map

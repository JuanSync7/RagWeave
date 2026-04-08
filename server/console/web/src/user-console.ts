// @summary
// User Console application logic for RagWeave.
// Handles sidebar navigation, chat thread interaction, real SSE streaming,
// conversation management, dynamic slash commands, settings, and context indicator.
// Deps: marked (ES module import), DOMPurify (ES module import), /query/stream, /console/* API endpoints
// @end-summary

import { marked } from "marked";
import DOMPurify from "dompurify";

/**
 * User Console — vanilla TypeScript DOM application.
 *
 * Drives the RagWeave user-facing console at /console.
 * No framework dependencies; external libs (marked, DOMPurify) as ES module imports.
 */

// ──────────────────────────────────────────────
//  Types
// ──────────────────────────────────────────────

type ThemeValue = "dark" | "light" | "system";

interface PresetConfig { searchLimit: number; rerankTopK: number; }

interface ContextBreakdown { system: number; memory: number; chunks: number; query: number; }

interface AttachmentChip { id: string; icon: string; label: string; }

interface SlashCommand {
    name: string;
    description: string;
    args_hint?: string;
    category?: string;
}

interface ConversationMeta {
    conversation_id: string;
    title?: string;
    updated_at_ms?: number;
    message_count?: number;
}

interface ChunkResult {
    text: string;
    score: number;
    metadata: Record<string, unknown>;
}

interface SourceRef {
    source?: string;
    source_uri?: string;
    section?: string;
    score?: number;
    text?: string;
    original_char_start?: number;
    original_char_end?: number;
}

function sourceRefToChunkResult(ref: SourceRef): ChunkResult {
    return {
        text: ref.text ?? "",
        score: ref.score ?? 0,
        metadata: {
            source: ref.source ?? "",
            source_uri: ref.source_uri ?? "",
            section: ref.section ?? "",
            original_char_start: ref.original_char_start,
            original_char_end: ref.original_char_end,
        },
    };
}

interface TokenBudget {
    usage_percent?: number;
    breakdown?: Record<string, unknown>;
    input_tokens?: number;
    context_length?: number;
}

interface StreamEventData {
    token?: string;
    message?: string;
    results?: ChunkResult[];
    conversation_id?: string;
    token_budget?: TokenBudget;
    summary?: string;
    [key: string]: unknown;
}

interface CommandResult {
    action?: string;
    message?: string;
    data?: Record<string, unknown>;
}

export {};

// ──────────────────────────────────────────────
//  Helpers
// ──────────────────────────────────────────────

const byId = <T extends HTMLElement = HTMLElement>(id: string): T => {
    const el = document.getElementById(id);
    if (!el) throw new Error(`Missing required element #${id}`);
    return el as T;
};

function escHtml(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtTime(ms: number): string {
    return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtRelative(ms: number): string {
    const now = Date.now();
    const diff = now - ms;
    if (diff < 86400000) return "Today";
    if (diff < 172800000) return "Yesterday";
    return new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" });
}

// ──────────────────────────────────────────────
//  Markdown configuration
// ──────────────────────────────────────────────

// Custom code-block renderer: wraps <pre><code> in a copy-button UI.
// Clicks are handled via event delegation on #thread — no inline onclick needed,
// which also means DOMPurify does not need to allow event attributes.
marked.use({
    gfm: true,   // tables, task lists, strikethrough, autolinks
    breaks: false,
    renderer: {
        code({ text, lang }: { text: string; lang?: string }): string {
            const langLabel = escHtml(lang ?? "code");
            const escaped = text
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
            return [
                `<div class="code-block-wrap">`,
                `<div class="code-block-header">`,
                `<span>${langLabel}</span>`,
                `<button class="copy-code-btn">&#128203; Copy</button>`,
                `</div>`,
                `<div class="code-block">${escaped}</div>`,
                `</div>`,
            ].join("");
        },
    },
});

// ──────────────────────────────────────────────
//  Markdown normalizer + renderer
// ──────────────────────────────────────────────

/** Returns true if a word looks like a numbered list marker: "1.", "2.", "10.", etc. */
function isListMarker(word: string): boolean {
    if (!word.endsWith(".")) return false;
    const n = Number(word.slice(0, -1));
    return Number.isInteger(n) && n > 0;
}

/**
 * If a line packs multiple list items inline (e.g. "1. Foo 2. Bar" or "- A - B"),
 * splits each item onto its own line. Bullet splitting is guarded: only fires when
 * the line already starts with "- "/"* " so standalone dashes in prose are unaffected.
 */
function splitInlineList(line: string): string {
    const words = line.split(" ");
    if (words.length < 3) return line;

    const lineStartsWithBullet = words[0] === "-" || words[0] === "*";
    const subLines: string[] = [];
    let current: string[] = [];

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

/**
 * Pre-process LLM output so list items always start on their own line.
 * Code fences are split out first so their content is never modified.
 */
function normalizeMarkdown(raw: string): string {
    // Split on complete fences only — partial fences during streaming are left as-is
    const segments = raw.split(/(```[\s\S]*?```)/);
    return segments.map((seg, i) => {
        if (i % 2 === 1) return seg; // inside a fence — leave unchanged
        return seg.split("\n").map(splitInlineList).join("\n");
    }).join("");
}

/**
 * Render markdown to sanitized HTML.
 * marked handles the full CommonMark + GFM spec (tables, task lists, strikethrough,
 * autolinks, block quotes, nested lists, footnotes, etc.).
 * DOMPurify strips any unsafe HTML before the result is set as innerHTML.
 * marked.parse is synchronous when no async hooks are configured.
 */
function parseMarkdown(raw: string): string {
    return DOMPurify.sanitize(marked.parse(normalizeMarkdown(raw)) as string);
}

// ──────────────────────────────────────────────
//  Main entry point
// ──────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {

    // ── Core layout refs ──
    const sidebar = byId("sidebar");
    const backdrop = byId("sidebarBackdrop");
    const settingsOverlay = byId("settingsOverlay");
    const settingsPanel = byId("settingsPanel");
    const thread = byId("thread");
    const fab = byId("scrollFab");
    const dropdown = byId("slashDropdown");
    const ta = byId<HTMLTextAreaElement>("inputArea");
    const attachPopover = byId("attachPopover");
    const webInputPanel = byId("webInputPanel");
    const kbPanel = byId("kbPanel");
    const cmdPicker = byId("cmdPicker");
    const attachBtn = byId("attachBtn");
    const cmdBtn = byId("cmdBtn");

    // ── Application state ──
    let activeConversationId: string | null =
        localStorage.getItem("nc_active_conv") || null;
    let isStreaming = false;
    let dynamicCmds: SlashCommand[] = [];
    let allSlashItems: HTMLElement[] = [];
    let slashSelIdx = 0;
    let allPickerItems: HTMLElement[] = [];
    let pickerIdx = 0;
    let attachments: AttachmentChip[] = [];
    let userScrolledUp = false;
    let streamAbortCtrl: AbortController | null = null;

    // ──────────────────────────────────────────
    //  Auth & API layer
    // ──────────────────────────────────────────

    function getSettings(): Record<string, unknown> {
        const raw = localStorage.getItem("nc_settings");
        return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    }

    function authHeaders(): Record<string, string> {
        const s = getSettings();
        const token = (s.auth_token as string | undefined) || "";
        const h: Record<string, string> = { "Content-Type": "application/json" };
        if (token) {
            h["Authorization"] = `Bearer ${token}`;
            h["x-api-key"] = token;
        }
        return h;
    }

    function apiBase(): string {
        const s = getSettings();
        const ep = ((s.api_endpoint as string | undefined) || "").trim();
        return ep ? ep.replace(/\/$/, "") : "";
    }

    async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
        const url = apiBase() + path;
        const opts: RequestInit = { method, headers: authHeaders() };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        const json = (await res.json()) as { ok: boolean; data?: T; error?: { message: string } };
        if (!res.ok || !json.ok) {
            throw new Error(json.error?.message || `HTTP ${res.status}`);
        }
        return json.data as T;
    }

    // ──────────────────────────────────────────
    //  Sidebar logic
    // ──────────────────────────────────────────

    function isDesktop(): boolean { return window.innerWidth > 1024; }

    function showPanel(panelId: string | undefined): void {
        document.querySelectorAll<HTMLElement>(".sidebar-panel").forEach((p) => p.classList.remove("active"));
        if (panelId) document.getElementById(panelId)?.classList.add("active");
    }

    function setNavActive(el: HTMLElement): void {
        document.querySelectorAll<HTMLElement>(".sidebar-nav-item").forEach((n) => n.classList.remove("active"));
        el.classList.add("active");
        if (!sidebar.classList.contains("collapsed")) showPanel(el.dataset.panel);
        if (!isDesktop()) closeSidebar();
    }

    function toggleSidebarCollapse(): void {
        sidebar.classList.toggle("collapsed");
        byId("sidebarCollapseBtn").innerHTML = sidebar.classList.contains("collapsed") ? "&#8250;" : "&#8249;";
        if (sidebar.classList.contains("collapsed")) {
            document.querySelectorAll<HTMLElement>(".sidebar-panel").forEach((p) => p.classList.remove("active"));
        } else {
            const activeNav = sidebar.querySelector<HTMLElement>(".sidebar-nav-item.active");
            if (activeNav) showPanel(activeNav.dataset.panel);
        }
    }

    function openSidebar(): void {
        if (isDesktop()) {
            sidebar.classList.remove("collapsed");
            byId("sidebarCollapseBtn").innerHTML = "&#8249;";
            const activeNav = sidebar.querySelector<HTMLElement>(".sidebar-nav-item.active");
            if (activeNav) showPanel(activeNav.dataset.panel);
        } else {
            sidebar.classList.add("open");
            backdrop.classList.add("active");
        }
    }

    function closeSidebar(): void {
        if (isDesktop()) {
            sidebar.classList.add("collapsed");
            byId("sidebarCollapseBtn").innerHTML = "&#8250;";
        } else {
            sidebar.classList.remove("open");
            backdrop.classList.remove("active");
        }
    }

    byId("toggleBtn").addEventListener("click", () => sidebar.classList.contains("open") ? closeSidebar() : openSidebar());
    document.querySelectorAll<HTMLElement>(".sidebar-nav-item").forEach((item) => item.addEventListener("click", () => setNavActive(item)));
    document.getElementById("sidebarCollapseBtn")?.addEventListener("click", toggleSidebarCollapse);

    window.addEventListener("resize", () => {
        if (isDesktop()) { sidebar.classList.remove("open"); backdrop.classList.remove("active"); }
    });

    let touchStartX = 0;
    document.addEventListener("touchstart", (e: TouchEvent) => { touchStartX = e.touches[0].clientX; }, { passive: true });
    document.addEventListener("touchend", (e: TouchEvent) => {
        const dx = e.changedTouches[0].clientX - touchStartX;
        if (!isDesktop()) {
            if (dx > 60 && touchStartX < 30) openSidebar();
            if (dx < -60 && sidebar.classList.contains("open")) closeSidebar();
        }
    }, { passive: true });

    // ──────────────────────────────────────────
    //  Settings panel
    // ──────────────────────────────────────────

    const mq: MediaQueryList = window.matchMedia("(prefers-color-scheme: light)");

    function applyThemeToDOM(val: ThemeValue | string): void {
        const resolved = val === "system" ? (mq.matches ? "light" : "dark") : val;
        document.documentElement.dataset.theme = resolved;
        document.querySelectorAll<HTMLElement>(".theme-opt").forEach((el) => {
            el.classList.toggle("active", el.dataset.themeVal === val);
        });
    }

    function setTheme(val: ThemeValue | string): void {
        applyThemeToDOM(val);
        localStorage.setItem("nc_theme", val);
    }

    mq.addEventListener("change", () => {
        if (localStorage.getItem("nc_theme") === "system") applyThemeToDOM("system");
    });

    document.querySelectorAll<HTMLElement>(".theme-opt").forEach((el) => {
        el.addEventListener("click", () => setTheme(el.dataset.themeVal || "dark"));
    });

    const PRESETS: Record<string, PresetConfig> = {
        balanced: { searchLimit: 10, rerankTopK: 5 },
        precise:  { searchLimit: 8,  rerankTopK: 3 },
        broad:    { searchLimit: 25, rerankTopK: 10 },
        fast:     { searchLimit: 5,  rerankTopK: 2 },
    };

    function applyPreset(name: string): void {
        const p = PRESETS[name];
        if (!p) return;
        byId<HTMLInputElement>("searchLimit").value = String(p.searchLimit);
        byId("searchLimitVal").textContent = String(p.searchLimit);
        byId<HTMLInputElement>("rerankTopK").value = String(p.rerankTopK);
        byId("rerankVal").textContent = String(p.rerankTopK);
    }

    document.getElementById("presetSelect")?.addEventListener("change", (e: Event) => {
        applyPreset((e.target as HTMLSelectElement).value);
    });

    // Sync slider display values in real-time
    document.getElementById("searchLimit")?.addEventListener("input", (e: Event) => {
        byId("searchLimitVal").textContent = (e.target as HTMLInputElement).value;
    });
    document.getElementById("rerankTopK")?.addEventListener("input", (e: Event) => {
        byId("rerankVal").textContent = (e.target as HTMLInputElement).value;
    });

    function openSettings(): void {
        settingsOverlay.classList.add("open");
        settingsPanel.classList.add("open");
        loadSettings();
    }

    function closeSettings(): void {
        settingsOverlay.classList.remove("open");
        settingsPanel.classList.remove("open");
    }

    function saveSettings(): void {
        const s = {
            theme: localStorage.getItem("nc_theme") || "dark",
            preset: byId<HTMLSelectElement>("presetSelect").value,
            searchLimit: byId<HTMLInputElement>("searchLimit").value,
            rerankTopK: byId<HTMLInputElement>("rerankTopK").value,
            streaming: byId<HTMLInputElement>("streamingToggle").checked,
            memory_enabled: byId<HTMLInputElement>("memoryToggle").checked,
            citations: byId<HTMLInputElement>("citationsToggle").checked,
            api_endpoint: byId<HTMLInputElement>("apiEndpoint").value.trim(),
            auth_token: byId<HTMLInputElement>("apiToken").value.trim(),
        };
        localStorage.setItem("nc_settings", JSON.stringify(s));
        closeSettings();
        showToast("Settings saved");
    }

    function loadSettings(): void {
        const s = getSettings();
        const theme = localStorage.getItem("nc_theme") || (s.theme as string) || "dark";
        applyThemeToDOM(theme);
        if (s.preset) byId<HTMLSelectElement>("presetSelect").value = s.preset as string;
        if (s.searchLimit) {
            byId<HTMLInputElement>("searchLimit").value = s.searchLimit as string;
            byId("searchLimitVal").textContent = s.searchLimit as string;
        }
        if (s.rerankTopK) {
            byId<HTMLInputElement>("rerankTopK").value = s.rerankTopK as string;
            byId("rerankVal").textContent = s.rerankTopK as string;
        }
        if (s.streaming !== undefined) byId<HTMLInputElement>("streamingToggle").checked = s.streaming as boolean;
        if (s.memory_enabled !== undefined) byId<HTMLInputElement>("memoryToggle").checked = s.memory_enabled as boolean;
        if (s.citations !== undefined) byId<HTMLInputElement>("citationsToggle").checked = s.citations as boolean;
        if (s.api_endpoint) byId<HTMLInputElement>("apiEndpoint").value = s.api_endpoint as string;
        if (s.auth_token) byId<HTMLInputElement>("apiToken").value = s.auth_token as string;
    }

    function resetSettings(): void {
        localStorage.removeItem("nc_settings");
        localStorage.removeItem("nc_theme");
        applyThemeToDOM("dark");
        byId<HTMLSelectElement>("presetSelect").value = "balanced";
        applyPreset("balanced");
        byId<HTMLInputElement>("streamingToggle").checked = true;
        byId<HTMLInputElement>("memoryToggle").checked = true;
        byId<HTMLInputElement>("citationsToggle").checked = true;
        byId<HTMLInputElement>("apiEndpoint").value = "";
        byId<HTMLInputElement>("apiToken").value = "";
        showToast("Settings reset to defaults");
    }

    document.getElementById("settingsBtn")?.addEventListener("click", openSettings);
    document.getElementById("customizeOpenSettings")?.addEventListener("click", openSettings);
    settingsOverlay.addEventListener("click", closeSettings);
    document.getElementById("settingsClose")?.addEventListener("click", closeSettings);
    document.getElementById("settingsSaveBtn")?.addEventListener("click", saveSettings);
    document.getElementById("settingsResetBtn")?.addEventListener("click", resetSettings);

    applyThemeToDOM(localStorage.getItem("nc_theme") || "dark");

    // ──────────────────────────────────────────
    //  Scroll FAB
    // ──────────────────────────────────────────

    thread.addEventListener("scroll", () => {
        const atBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
        userScrolledUp = !atBottom;
        fab.classList.toggle("visible", userScrolledUp);
    });

    fab.addEventListener("click", () => { thread.scrollTop = thread.scrollHeight; });

    function scrollToBottom(): void {
        if (!userScrolledUp) thread.scrollTop = thread.scrollHeight;
    }

    // ──────────────────────────────────────────
    //  Toast & copy helpers
    // ──────────────────────────────────────────

    function showToast(msg: string): void {
        const t = byId("toast");
        t.textContent = msg;
        t.classList.add("show");
        setTimeout(() => t.classList.remove("show"), 2200);
    }

    function copyMsg(btn: HTMLElement, text: string): void {
        navigator.clipboard.writeText(text).then(() => {
            btn.classList.add("copied");
            btn.textContent = "\u2713 Copied";
            setTimeout(() => { btn.classList.remove("copied"); btn.innerHTML = "&#128203; Copy"; }, 2000);
        });
        showToast("Copied to clipboard");
    }

    function copyBubble(btn: HTMLElement, id: string): void {
        copyMsg(btn, document.getElementById(id)?.innerText || "");
    }

    (window as unknown as Record<string, unknown>)["copyMsg"] = copyMsg;
    (window as unknown as Record<string, unknown>)["copyBubble"] = copyBubble;
    (window as unknown as Record<string, unknown>)["showToast"] = showToast;

    // Single delegated handler for all code-block copy buttons in the thread.
    // marked's custom renderer emits <button class="copy-code-btn"> with no
    // onclick; this handler picks it up regardless of when the bubble was rendered.
    thread.addEventListener("click", (e) => {
        const btn = (e.target as HTMLElement).closest<HTMLElement>(".copy-code-btn");
        if (!btn) return;
        const codeDiv = btn.closest(".code-block-wrap")?.querySelector<HTMLElement>(".code-block");
        if (codeDiv) {
            navigator.clipboard.writeText(codeDiv.textContent ?? "");
            showToast("Code copied");
        }
    });

    // ──────────────────────────────────────────
    //  Citation helpers
    // ──────────────────────────────────────────

    function toggleCitation(card: HTMLElement): void { card.classList.toggle("expanded"); }

    function toggleChunk(e: Event, id: string): void {
        e.stopPropagation();
        const el = byId(id);
        el.classList.toggle("show-all");
        (e.target as HTMLElement).textContent = el.classList.contains("show-all") ? "Show less" : "Show more";
    }

    (window as unknown as Record<string, unknown>)["toggleCitation"] = toggleCitation;
    (window as unknown as Record<string, unknown>)["toggleChunk"] = toggleChunk;

    // ──────────────────────────────────────────
    //  Context window indicator
    // ──────────────────────────────────────────

    function updateContextIndicator(pct: number, bd?: Partial<ContextBreakdown>): void {
        const breakdown: ContextBreakdown = {
            system: bd?.system ?? 0,
            memory: bd?.memory ?? 0,
            chunks: bd?.chunks ?? 0,
            query:  bd?.query  ?? 0,
        };
        const chip = byId("ctxChip");
        byId("ctxBarFill").style.width = Math.min(pct, 100) + "%";
        byId("ctxPct").textContent = "~" + Math.round(pct) + "%";
        chip.classList.remove("warn", "crit");
        if (pct >= 95) chip.classList.add("crit");
        else if (pct >= 80) chip.classList.add("warn");
        const fmt = (n: number) => n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
        byId("ttSystem").textContent = fmt(breakdown.system) + " tok";
        byId("ttMemory").textContent = fmt(breakdown.memory) + " tok";
        byId("ttChunks").textContent = fmt(breakdown.chunks) + " tok";
        byId("ttQuery").textContent  = fmt(breakdown.query)  + " tok";
        const total = breakdown.system + breakdown.memory + breakdown.chunks + breakdown.query;
        byId("ttTotal").textContent = fmt(total) + " tok";
        byId("ctxCompactBtn").style.display = pct >= 95 ? "block" : "none";
    }

    byId("ctxCompactBtn").addEventListener("click", async () => {
        if (!activeConversationId) return;
        try {
            await api("POST", `/console/conversations/${activeConversationId}/compact`);
            showToast("Conversation compacted");
            updateContextIndicator(0);
        } catch (err) {
            showToast("Compact failed: " + String(err));
        }
    });

    byId("ctxChip").addEventListener("click", () => {
        byId("ctxChip").classList.toggle("tooltip-open");
    });

    // ──────────────────────────────────────────
    //  Message thread rendering
    // ──────────────────────────────────────────

    function setEmptyState(visible: boolean): void {
        const el = document.getElementById("threadEmpty");
        if (el) el.style.display = visible ? "" : "none";
    }

    function appendUserMsg(text: string): void {
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
        thread.appendChild(group);
        scrollToBottom();
    }

    /** Creates a pending assistant bubble with typing indicator. Returns the bubble element. */
    function appendPendingAssistant(): {
        group: HTMLElement;
        bubbleEl: HTMLElement;
        typingEl: HTMLElement;
        citationsEl: HTMLElement;
        actionsEl: HTMLElement;
        metaEl: HTMLElement;
    } {
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
        thread.appendChild(group);
        scrollToBottom();
        const bw = group.querySelector(".bubble-wrap")!;
        const bubbleEl   = bw.querySelector<HTMLElement>(".bubble")!;
        const typingEl   = bw.querySelector<HTMLElement>(".typing-indicator")!;
        const citationsEl = bw.querySelector<HTMLElement>(".citations")!;
        const actionsEl  = bw.querySelector<HTMLElement>(".msg-actions")!;
        const metaEl     = bw.querySelector<HTMLElement>(".msg-meta")!;
        const copyBtn    = actionsEl.querySelector<HTMLButtonElement>("button");
        if (copyBtn) {
            copyBtn.addEventListener("click", () => copyMsg(copyBtn, bubbleEl.innerText));
        }
        return { group, bubbleEl, typingEl, citationsEl, actionsEl, metaEl };
    }

    function buildCitationsHtml(results: ChunkResult[]): string {
        if (!results.length) return "";
        let html = `<div class="citation-label">&#128206; ${results.length} source${results.length > 1 ? "s" : ""} cited</div>`;
        results.forEach((r, i) => {
            const meta = r.metadata || {};
            const filename = escHtml(String(meta.source ?? meta.filename ?? "Unknown source"));
            const section  = escHtml(String(meta.section ?? meta.heading ?? ""));
            const score    = Math.round(r.score * 100);
            const scoreClass = score >= 80 ? "high" : score >= 50 ? "mid" : "low";
            const chunkText = escHtml(r.text || "").slice(0, 400);
            const chunkId = `chunk-${i}-${Date.now()}`;
            const sourceUri = String(meta.source_uri ?? "").trim();
            const source    = String(meta.source ?? "").trim();
            const start = meta.original_char_start;
            const end   = meta.original_char_end;
            let viewHref = "";
            if (sourceUri || source) {
                const p = new URLSearchParams();
                if (sourceUri) p.set("source_uri", sourceUri);
                else p.set("source", source);
                if (start !== undefined && end !== undefined) {
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
                  <div class="citation-chunk" id="${chunkId}">"${chunkText}${r.text.length > 400 ? "…" : ""}"</div>
                  <button class="citation-show-more" onclick="event.stopPropagation();toggleChunk(event,'${chunkId}')">Show more</button>
                </div>
              </div>`;
        });
        return html;
    }

    function appendSystemMsg(text: string): void {
        const div = document.createElement("div");
        div.className = "msg-group";
        div.innerHTML = `<div class="msg-row assistant"><div class="avatar ai-av">&#9432;</div><div class="bubble-wrap"><div class="bubble">${escHtml(text)}</div></div></div>`;
        thread.appendChild(div);
        scrollToBottom();
    }

    function appendErrorMsg(text: string): void {
        const div = document.createElement("div");
        div.className = "msg-group";
        div.innerHTML = `<div class="msg-row assistant"><div class="avatar ai-av">!</div><div class="bubble-wrap"><div class="bubble error-bubble">&#9888; ${escHtml(text)}</div></div></div>`;
        thread.appendChild(div);
        scrollToBottom();
    }

    // ──────────────────────────────────────────
    //  Conversation list
    // ──────────────────────────────────────────

    function setActiveConversation(id: string | null): void {
        activeConversationId = id;
        if (id) localStorage.setItem("nc_active_conv", id);
        else localStorage.removeItem("nc_active_conv");
    }

    function renderConversationList(convs: ConversationMeta[]): void {
        const container = byId("convList");
        if (!convs.length) {
            container.innerHTML = `<div class="conv-list-empty">No conversations yet.<br>Start one below!</div>`;
            return;
        }
        // Group by date
        const groups: Record<string, ConversationMeta[]> = {};
        convs.forEach((c) => {
            const label = fmtRelative(c.updated_at_ms ?? Date.now());
            if (!groups[label]) groups[label] = [];
            groups[label].push(c);
        });
        let html = "";
        for (const [label, items] of Object.entries(groups)) {
            html += `<div class="conv-section-label">${escHtml(label)}</div>`;
            items.forEach((c) => {
                const isActive = c.conversation_id === activeConversationId;
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

        // Wire click handlers
        container.querySelectorAll<HTMLElement>(".conv-item").forEach((el) => {
            el.addEventListener("click", () => {
                const id = el.dataset.convId;
                if (id) selectConversation(id);
            });
        });
        container.querySelectorAll<HTMLElement>(".conv-item-del").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const id = btn.dataset.convId;
                if (id) deleteConversation(id);
            });
        });
    }

    async function loadConversations(): Promise<void> {
        try {
            const data = await api<{ conversations: ConversationMeta[] }>("GET", "/console/conversations?limit=50");
            renderConversationList(data.conversations || []);
        } catch {
            // Non-fatal — sidebar just stays empty
        }
    }

    async function selectConversation(id: string): Promise<void> {
        // Abort any in-progress stream before switching
        if (isStreaming) {
            streamAbortCtrl?.abort();
            isStreaming = false;
        }
        setActiveConversation(id);
        // Update active class
        byId("convList").querySelectorAll<HTMLElement>(".conv-item").forEach((el) => {
            el.classList.toggle("active", el.dataset.convId === id);
        });
        await loadConversationHistory(id);
    }

    async function loadConversationHistory(id?: string): Promise<void> {
        const convId = id ?? activeConversationId;
        if (!convId) return;
        try {
            const data = await api<{ conversation_id: string; turns: Array<{ role: string; content: string; timestamp_ms?: number; sources?: SourceRef[] }> }>(
                "GET", `/console/conversations/${convId}/history?limit=100`
            );
            thread.innerHTML = "";
            if (!data.turns || !data.turns.length) {
                thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#128172;</div><div class="thread-empty-title">Empty conversation</div><div class="thread-empty-sub">Send a message to start the conversation.</div></div>`;
                return;
            }
            data.turns.forEach((turn) => {
                if (turn.role === "user") {
                    appendUserMsg(turn.content);
                } else {
                    // Render assistant turns as completed messages
                    setEmptyState(false);
                    const group = document.createElement("div");
                    group.className = "msg-group";
                    const ts = fmtTime(turn.timestamp_ms ?? Date.now());
                    const sources = turn.sources ?? [];
                    const citationsHtml = sources.length
                        ? `<div class="citations">${buildCitationsHtml(sources.map(sourceRefToChunkResult))}</div>`
                        : "";
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
                    const copyBtn = group.querySelector<HTMLElement>(".msg-action-btn");
                    if (copyBtn) {
                        const bubbleEl = group.querySelector<HTMLElement>(".bubble")!;
                        copyBtn.addEventListener("click", () => copyMsg(copyBtn, bubbleEl.innerText));
                    }
                    thread.appendChild(group);
                }
            });
            // Update title
            const activeConv = document.querySelector<HTMLElement>(`.conv-item[data-conv-id="${convId}"]`);
            if (activeConv) byId("convTitle").textContent = activeConv.title ?? activeConv.textContent?.trim() ?? "Conversation";
            setTimeout(() => { thread.scrollTop = thread.scrollHeight; }, 50);
        } catch (err) {
            appendErrorMsg("Failed to load conversation history: " + String(err));
        }
    }

    async function createNewConversation(): Promise<void> {
        try {
            const data = await api<{ conversation: ConversationMeta }>("POST", "/console/conversations/new", {
                title: "New conversation",
            });
            const conv = data.conversation;
            setActiveConversation(conv.conversation_id);
            thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#128172;</div><div class="thread-empty-title">New conversation</div><div class="thread-empty-sub">Send a message to get started.</div></div>`;
            byId("convTitle").textContent = conv.title || "New conversation";
            await loadConversations();
            showToast("New conversation started");
        } catch (err) {
            showToast("Failed to create conversation: " + String(err));
        }
    }

    async function deleteConversation(id: string): Promise<void> {
        try {
            await api("DELETE", `/console/conversations/${id}`);
            if (activeConversationId === id) {
                setActiveConversation(null);
                thread.innerHTML = `<div class="thread-empty" id="threadEmpty"><div class="thread-empty-icon">&#9670;</div><div class="thread-empty-title">RagWeave</div><div class="thread-empty-sub">Ask anything — I'll search your knowledge base and generate a response with sources.</div></div>`;
                byId("convTitle").textContent = "RagWeave";
            }
            await loadConversations();
            showToast("Conversation deleted");
        } catch {
            showToast("Failed to delete conversation");
        }
    }

    byId("newChatBtn").addEventListener("click", createNewConversation);

    // ──────────────────────────────────────────
    //  Dynamic slash commands
    // ──────────────────────────────────────────

    function renderSlashDropdown(cmds: SlashCommand[]): void {
        const container = byId("slashItems");
        container.innerHTML = cmds.map((c) =>
            `<div class="slash-item" data-cmd="/${escHtml(c.name)}">` +
            `<span class="slash-cmd">/${escHtml(c.name)}</span>` +
            `<span class="slash-desc">${escHtml(c.description)}</span>` +
            `</div>`
        ).join("");
        allSlashItems = Array.from(container.querySelectorAll<HTMLElement>(".slash-item"));
        allSlashItems.forEach((item) => item.addEventListener("click", () => executeCmd(item.dataset.cmd || "")));
    }

    function renderCmdPicker(cmds: SlashCommand[]): void {
        const container = byId("cmdPickerBody");
        // Group by category
        const grouped: Record<string, SlashCommand[]> = {};
        cmds.forEach((c) => {
            const cat = c.category || "General";
            if (!grouped[cat]) grouped[cat] = [];
            grouped[cat].push(c);
        });
        let html = "";
        for (const [cat, items] of Object.entries(grouped)) {
            html += `<div class="cmd-group-label">${escHtml(cat)}</div>`;
            items.forEach((c) => {
                html += `<div class="cmd-picker-item" data-cmd="/${escHtml(c.name)}">` +
                    `<span class="cmd-picker-icon">&#47;</span>` +
                    `<span class="cmd-picker-name">/${escHtml(c.name)}</span>` +
                    `<span class="cmd-picker-desc">${escHtml(c.description)}</span>` +
                    `</div>`;
            });
        }
        container.innerHTML = html;
        allPickerItems = Array.from(container.querySelectorAll<HTMLElement>(".cmd-picker-item"));
        allPickerItems.forEach((item) => item.addEventListener("click", () => executePicker(item)));
    }

    async function loadCommands(): Promise<void> {
        try {
            const data = await api<{ commands: SlashCommand[] }>("GET", "/console/commands?mode=query");
            dynamicCmds = data.commands || [];
            renderSlashDropdown(dynamicCmds);
            renderCmdPicker(dynamicCmds);
        } catch {
            // Non-fatal: commands just stay empty
        }
    }

    // ──────────────────────────────────────────
    //  Slash autocomplete UI
    // ──────────────────────────────────────────

    function closeDropdown(): void { dropdown.classList.remove("open"); }

    function setSelected(i: number): void {
        const vis = allSlashItems.filter((x) => x.style.display !== "none");
        if (!vis.length) return;
        slashSelIdx = (i + vis.length) % vis.length;
        vis.forEach((el, j) => el.classList.toggle("selected", j === slashSelIdx));
    }

    function executeCmd(cmd: string): void {
        ta.value = cmd + " ";
        ta.focus();
        ta.style.height = "auto";
        closeDropdown();
    }

    function handleSlashInput(): void {
        const val = ta.value;
        if (!val.startsWith("/")) { closeDropdown(); return; }
        const q = val.slice(1).toLowerCase();
        let vis = 0;
        allSlashItems.forEach((item) => {
            const cmdAttr = (item.dataset.cmd || "").toLowerCase();
            const descEl = item.querySelector<HTMLElement>(".slash-desc");
            const descText = descEl ? descEl.textContent?.toLowerCase() || "" : "";
            const match = cmdAttr.includes(q) || descText.includes(q);
            item.style.display = match ? "" : "none";
            if (match) vis++;
        });
        if (!vis) { closeDropdown(); return; }
        dropdown.classList.add("open");
        setSelected(0);
    }

    // ──────────────────────────────────────────
    //  Query execution (streaming + non-stream)
    // ──────────────────────────────────────────

    function buildQueryBody(queryText: string): Record<string, unknown> {
        const s = getSettings();
        return {
            query: queryText,
            search_limit: parseInt(String(s.searchLimit ?? "10"), 10),
            rerank_top_k: parseInt(String(s.rerankTopK ?? "5"), 10),
            memory_enabled: s.memory_enabled !== false,
            conversation_id: activeConversationId ?? undefined,
        };
    }

    async function streamQuery(queryText: string): Promise<void> {
        if (isStreaming) {
            streamAbortCtrl?.abort();
        }
        isStreaming = true;
        streamAbortCtrl = new AbortController();

        appendUserMsg(queryText);
        const { bubbleEl, typingEl, citationsEl, actionsEl, metaEl } = appendPendingAssistant();

        const url = apiBase() + "/query/stream";
        let response: Response;
        try {
            response = await fetch(url, {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify(buildQueryBody(queryText)),
                signal: streamAbortCtrl.signal,
            });
        } catch (err) {
            typingEl.remove();
            bubbleEl.innerHTML = "&#9888; Network error: " + escHtml(String(err));
            bubbleEl.classList.add("error-bubble");
            bubbleEl.style.display = "block";
            isStreaming = false;
            return;
        }

        if (!response.ok || !response.body) {
            typingEl.remove();
            bubbleEl.innerHTML = `&#9888; Stream error (HTTP ${response.status})`;
            bubbleEl.classList.add("error-bubble");
            bubbleEl.style.display = "block";
            isStreaming = false;
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let answer = "";
        let started = false;
        let errorShown = false;
        let pendingClarification = "";

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
                    let data: StreamEventData;
                    try { data = JSON.parse(dataRaw) as StreamEventData; }
                    catch { data = {}; }

                    if (evtType === "token") {
                        if (!started) {
                            typingEl.style.display = "none";
                            bubbleEl.style.display = "block";
                            started = true;
                        }
                        answer += data.token || "";
                        bubbleEl.innerHTML = parseMarkdown(answer) + '<span class="cursor"></span>';
                        scrollToBottom();

                    } else if (evtType === "retrieval") {
                        const cid = String(data.conversation_id ?? "").trim();
                        if (cid) setActiveConversation(cid);

                        // Capture clarification message from retrieval (no-results path)
                        const clar = String(data.clarification_message ?? "").trim();
                        if (clar) pendingClarification = clar;

                        // Update context indicator from token_budget
                        const tb = data.token_budget;
                        if (tb?.usage_percent !== undefined) {
                            const bd = tb.breakdown ?? {};
                            updateContextIndicator(tb.usage_percent * 100, {
                                system: Number(bd.system_tokens ?? bd.system ?? 0),
                                memory: Number(bd.memory_tokens ?? bd.memory ?? 0),
                                chunks: Number(bd.chunk_tokens ?? bd.chunks ?? 0),
                                query:  Number(bd.query_tokens  ?? bd.query  ?? 0),
                            });
                        }

                        // Render citations (shown after streaming finishes)
                        const results = (data.results ?? []) as ChunkResult[];
                        const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
                        if (showCitations && results.length) {
                            citationsEl.innerHTML = buildCitationsHtml(results);
                        }

                    } else if (evtType === "error") {
                        errorShown = true;
                        typingEl.style.display = "none";
                        bubbleEl.innerHTML = "&#9888; " + escHtml(String(data.message ?? "Unknown error"));
                        bubbleEl.classList.add("error-bubble");
                        bubbleEl.style.display = "block";
                        scrollToBottom();

                    } else if (evtType === "done") {
                        const cid = String(data.conversation_id ?? "").trim();
                        if (cid) setActiveConversation(cid);

                        typingEl.style.display = "none";
                        if (!errorShown) {
                            if (!started) {
                                // No tokens: show clarification or fallback ask
                                const msg = pendingClarification ||
                                    "I couldn't find relevant information for that query. " +
                                    "Could you rephrase your question or provide more details?";
                                bubbleEl.innerHTML = parseMarkdown(msg);
                                bubbleEl.style.display = "block";
                            } else {
                                // Tokens streamed: finalize (remove cursor)
                                bubbleEl.innerHTML = parseMarkdown(answer);
                                bubbleEl.style.display = "block";
                            }
                        }

                        const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
                        if (showCitations && citationsEl.innerHTML) citationsEl.style.display = "block";
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
            if ((err as Error).name !== "AbortError") {
                appendErrorMsg("Stream interrupted: " + String(err));
            }
        }

        isStreaming = false;
    }

    async function nonStreamQuery(queryText: string): Promise<void> {
        appendUserMsg(queryText);
        const { bubbleEl, typingEl, citationsEl, actionsEl, metaEl } = appendPendingAssistant();
        try {
            const data = await api<{
                generated_answer?: string;
                clarification_message?: string;
                results?: ChunkResult[];
                conversation_id?: string;
                token_budget?: TokenBudget;
            }>("POST", "/console/query", buildQueryBody(queryText));

            const cid = String(data.conversation_id ?? "").trim();
            if (cid) setActiveConversation(cid);

            typingEl.style.display = "none";
            const answer = data.generated_answer ?? data.clarification_message ?? "No response.";
            bubbleEl.innerHTML = parseMarkdown(answer);
            bubbleEl.style.display = "block";

            const tb = data.token_budget;
            if (tb?.usage_percent !== undefined) {
                const bd = tb.breakdown ?? {};
                updateContextIndicator(tb.usage_percent * 100, {
                    system: Number(bd.system_tokens ?? 0),
                    memory: Number(bd.memory_tokens ?? 0),
                    chunks: Number(bd.chunk_tokens  ?? 0),
                    query:  Number(bd.query_tokens   ?? 0),
                });
            }

            const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
            const results = data.results ?? [];
            if (showCitations && results.length) {
                citationsEl.innerHTML = buildCitationsHtml(results);
                citationsEl.style.display = "block";
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

    function updateConvTitle(): void {
        if (!activeConversationId) return;
        const item = byId("convList").querySelector<HTMLElement>(`.conv-item[data-conv-id="${activeConversationId}"]`);
        if (item) byId("convTitle").textContent = item.textContent?.trim().replace(/^●/, "").trim() ?? "Conversation";
    }

    async function sendQuery(text: string): Promise<void> {
        const s = getSettings();
        const useStreaming = s.streaming !== false;
        if (useStreaming) {
            await streamQuery(text);
        } else {
            await nonStreamQuery(text);
        }
    }

    // ──────────────────────────────────────────
    //  Slash command submission
    // ──────────────────────────────────────────

    async function submitSlashCommand(text: string): Promise<void> {
        const trimmed = text.trim();
        const spaceIdx = trimmed.indexOf(" ");
        const commandName = (spaceIdx === -1 ? trimmed.slice(1) : trimmed.slice(1, spaceIdx)).toLowerCase();
        const arg = spaceIdx === -1 ? "" : trimmed.slice(spaceIdx + 1).trim();

        appendUserMsg(trimmed);

        try {
            const result = await api<CommandResult>("POST", "/console/command", {
                mode: "query",
                command: commandName,
                arg: arg || undefined,
                state: { conversation_id: activeConversationId ?? undefined },
            });
            const action = String(result.action ?? "noop");

            if (action === "run_stream_query") {
                // The command wants to execute a query — use the arg or command as the query
                const queryText = arg || commandName;
                await streamQuery(queryText);

            } else if (action === "run_non_stream_query") {
                const queryText = arg || commandName;
                await nonStreamQuery(queryText);

            } else if (action === "new_conversation") {
                const conv = result.data?.conversation as ConversationMeta | undefined;
                if (conv?.conversation_id) setActiveConversation(conv.conversation_id);
                else await createNewConversation();
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
                appendSystemMsg(summary ? `Compacted. Summary:\n\n${summary}` : "Conversation compacted.");
                await loadConversations();

            } else if (action === "delete_conversation") {
                const cid = String(result.data?.conversation_id ?? "").trim();
                if (cid) await deleteConversation(cid);

            } else if (action === "clear_view") {
                thread.innerHTML = "";
                setEmptyState(true);

            } else if (action === "refresh_health") {
                const h = result.data?.health as Record<string, unknown> | undefined;
                const status = h ? JSON.stringify(h, null, 2) : "Health data unavailable";
                appendSystemMsg("Health:\n```json\n" + status + "\n```");

            } else if (action === "render_help") {
                const cmds = result.data?.commands as SlashCommand[] | undefined;
                if (cmds?.length) {
                    const lines = cmds.map((c) => `**/${c.name}** — ${c.description}`).join("\n");
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

    // ──────────────────────────────────────────
    //  Input textarea + send
    // ──────────────────────────────────────────

    ta.addEventListener("input", () => {
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
        handleSlashInput();
    });

    ta.addEventListener("keydown", (e: KeyboardEvent) => {
        if (!dropdown.classList.contains("open")) {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); triggerSend(); }
            return;
        }
        if (e.key === "ArrowDown") { e.preventDefault(); setSelected(slashSelIdx + 1); }
        if (e.key === "ArrowUp")   { e.preventDefault(); setSelected(slashSelIdx - 1); }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
            e.preventDefault();
            const vis = allSlashItems.filter((x) => x.style.display !== "none");
            if (vis[slashSelIdx]) executeCmd(vis[slashSelIdx].dataset.cmd || "");
        }
        if (e.key === "Escape") closeDropdown();
    });

    function triggerSend(): void {
        const text = ta.value.trim();
        if (!text || isStreaming) return;
        closeDropdown();
        ta.value = "";
        ta.style.height = "auto";
        if (text.startsWith("/")) {
            void submitSlashCommand(text);
        } else {
            void sendQuery(text);
        }
    }

    byId("sendBtn").addEventListener("click", triggerSend);

    // ──────────────────────────────────────────
    //  Attachment toolbar
    // ──────────────────────────────────────────

    function renderChips(): void {
        const container = byId("attachChips");
        container.innerHTML = "";
        attachments.forEach((a) => {
            const chip = document.createElement("div");
            chip.className = "attach-chip";
            chip.innerHTML =
                `<span class="attach-chip-icon">${a.icon}</span>` +
                `<span class="attach-chip-label">${escHtml(a.label)}</span>` +
                `<button class="attach-chip-remove" title="Remove">&#215;</button>`;
            chip.querySelector<HTMLButtonElement>(".attach-chip-remove")?.addEventListener("click", () => removeChip(a.id));
            container.appendChild(chip);
        });
    }

    function addChip(icon: string, label: string, id: string): void {
        if (attachments.find((a) => a.id === id)) return;
        attachments.push({ id, icon, label });
        renderChips();
    }

    function removeChip(id: string): void {
        attachments = attachments.filter((a) => a.id !== id);
        renderChips();
    }

    (window as unknown as Record<string, unknown>)["removeChip"] = removeChip;

    function closeAllPopovers(): void {
        attachPopover.classList.remove("open");
        webInputPanel.classList.remove("open");
        kbPanel.classList.remove("open");
        attachBtn.classList.remove("active");
    }

    function closeCmdPicker(): void {
        cmdPicker.classList.remove("open");
        cmdBtn.classList.remove("active");
    }

    function toggleAttachPopover(): void {
        const isOpen = attachPopover.classList.contains("open");
        closeAllPopovers(); closeCmdPicker();
        if (!isOpen) { attachPopover.classList.add("open"); attachBtn.classList.add("active"); }
    }

    function openWebInput(): void {
        closeAllPopovers();
        webInputPanel.classList.add("open");
        setTimeout(() => document.getElementById("webUrlInput")?.focus(), 50);
    }

    function openKBSelect(): void { closeAllPopovers(); kbPanel.classList.add("open"); }

    attachBtn.addEventListener("click", toggleAttachPopover);
    document.getElementById("attachOptFile")?.addEventListener("click", triggerFileUpload);
    document.getElementById("attachOptWeb")?.addEventListener("click", openWebInput);
    document.getElementById("attachOptKB")?.addEventListener("click", openKBSelect);

    function triggerFileUpload(): void {
        closeAllPopovers();
        byId<HTMLInputElement>("fileInput").click();
    }

    function handleFileSelect(input: HTMLInputElement): void {
        if (!input.files) return;
        Array.from(input.files).forEach((file) => addChip("&#128196;", file.name, "file:" + file.name));
        input.value = "";
        showToast("File added to context");
    }

    document.getElementById("fileInput")?.addEventListener("change", (e: Event) => {
        handleFileSelect(e.target as HTMLInputElement);
    });

    (window as unknown as Record<string, unknown>)["handleFileSelect"] = handleFileSelect;

    function attachWebUrl(): void {
        const input = byId<HTMLInputElement>("webUrlInput");
        const url = input.value.trim();
        if (!url) return;
        try { new URL(url); } catch { showToast("Invalid URL"); return; }
        addChip("&#127760;", new URL(url).hostname.replace("www.", ""), "web:" + url);
        input.value = "";
        webInputPanel.classList.remove("open");
        showToast("Web page added to context");
    }

    document.getElementById("webUrlInput")?.addEventListener("keydown", (e: KeyboardEvent) => {
        if (e.key === "Enter") attachWebUrl();
        if (e.key === "Escape") webInputPanel.classList.remove("open");
    });
    document.getElementById("webAddBtn")?.addEventListener("click", attachWebUrl);

    function filterKB(q: string): void {
        document.querySelectorAll<HTMLElement>(".kb-item").forEach((el) => {
            const name = el.querySelector<HTMLElement>(".kb-item-name")?.textContent?.toLowerCase() || "";
            el.style.display = name.includes(q.toLowerCase()) ? "" : "none";
        });
    }

    function attachKBDocs(): void {
        document.querySelectorAll<HTMLInputElement>("#kbList input[type=checkbox]:checked").forEach((cb) => {
            addChip("&#128218;", cb.value, "kb:" + cb.value);
            cb.checked = false;
        });
        kbPanel.classList.remove("open");
        showToast("Documents added to context");
    }

    document.getElementById("kbSearch")?.addEventListener("input", (e: Event) => filterKB((e.target as HTMLInputElement).value));
    document.getElementById("kbAddBtn")?.addEventListener("click", attachKBDocs);

    (window as unknown as Record<string, unknown>)["openWebInput"] = openWebInput;
    (window as unknown as Record<string, unknown>)["openKBSelect"] = openKBSelect;
    (window as unknown as Record<string, unknown>)["triggerFileUpload"] = triggerFileUpload;
    (window as unknown as Record<string, unknown>)["filterKB"] = filterKB;
    (window as unknown as Record<string, unknown>)["attachKBDocs"] = attachKBDocs;
    (window as unknown as Record<string, unknown>)["attachWebUrl"] = attachWebUrl;

    // ──────────────────────────────────────────
    //  Command picker
    // ──────────────────────────────────────────

    function setPickerSelected(idx: number): void {
        if (!allPickerItems.length) return;
        pickerIdx = (idx + allPickerItems.length) % allPickerItems.length;
        allPickerItems.forEach((el, i) => el.classList.toggle("selected", i === pickerIdx));
        allPickerItems[pickerIdx]?.scrollIntoView({ block: "nearest" });
    }

    function executePicker(item: HTMLElement): void {
        const cmd = item.dataset.cmd || "";
        closeCmdPicker();
        ta.value = cmd + " ";
        ta.focus();
        ta.style.height = "auto";
        closeDropdown();
    }

    function toggleCmdPicker(): void {
        const isOpen = cmdPicker.classList.contains("open");
        closeAllPopovers();
        if (isOpen) { closeCmdPicker(); }
        else { cmdPicker.classList.add("open"); cmdBtn.classList.add("active"); setPickerSelected(0); }
    }

    cmdBtn.addEventListener("click", toggleCmdPicker);
    document.getElementById("cmdPickerClose")?.addEventListener("click", closeCmdPicker);
    document.getElementById("kbPanelClose")?.addEventListener("click", closeAllPopovers);

    document.addEventListener("keydown", (e: KeyboardEvent) => {
        if (!cmdPicker.classList.contains("open")) return;
        if (e.key === "ArrowDown") { e.preventDefault(); setPickerSelected(pickerIdx + 1); }
        if (e.key === "ArrowUp")   { e.preventDefault(); setPickerSelected(pickerIdx - 1); }
        if (e.key === "Enter")     { e.preventDefault(); executePicker(allPickerItems[pickerIdx]); }
        if (e.key === "Escape")    { closeCmdPicker(); }
    });

    // ──────────────────────────────────────────
    //  Outside click handler
    // ──────────────────────────────────────────

    document.addEventListener("click", (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        if (!target.closest(".input-bar")) {
            closeAllPopovers(); closeCmdPicker(); closeDropdown();
            document.getElementById("ctxChip")?.classList.remove("tooltip-open");
        }
    });

    // Conversation search
    document.getElementById("convSearch")?.addEventListener("input", (e: Event) => {
        const q = (e.target as HTMLInputElement).value.toLowerCase();
        byId("convList").querySelectorAll<HTMLElement>(".conv-item-wrap").forEach((wrap) => {
            const text = wrap.querySelector<HTMLElement>(".conv-item")?.textContent?.toLowerCase() || "";
            wrap.style.display = text.includes(q) ? "" : "none";
        });
    });

    // ──────────────────────────────────────────
    //  Initialization
    // ──────────────────────────────────────────

    // Load settings & theme
    loadSettings();

    // Kick off parallel data loads
    void Promise.all([loadCommands(), loadConversations()]).then(() => {
        // After conversations load, restore last active conversation
        if (activeConversationId) {
            void loadConversationHistory(activeConversationId);
        }
    });

    // Scroll to bottom on load
    setTimeout(() => { thread.scrollTop = thread.scrollHeight; }, 100);
});

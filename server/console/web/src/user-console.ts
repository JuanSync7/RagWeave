// @summary
// User Console application logic for Aion Chat.
// Handles sidebar navigation, chat thread interaction, streaming display,
// settings management, theme system, slash commands, and context attachments.
// Deps: marked.js (CDN), DOMPurify (CDN)
// @end-summary

/**
 * User Console — vanilla TypeScript DOM application.
 *
 * This module drives the Aion Chat user-facing console served at /console.
 * It is structured as a self-contained DOMContentLoaded entry point with no
 * framework dependencies.  External libraries (marked, DOMPurify) are loaded
 * from CDN and accessed through window globals.
 */

// ──────────────────────────────────────────────
//  Types and interfaces
// ──────────────────────────────────────────────

type ThemeValue = "dark" | "light" | "system";

interface PresetConfig {
    searchLimit: number;
    rerankTopK: number;
}

interface ContextBreakdown {
    system: number;
    memory: number;
    chunks: number;
    query: number;
}

interface ContextState {
    pct: number;
    breakdown: ContextBreakdown;
}

interface AttachmentChip {
    id: string;
    icon: string;
    label: string;
}

interface MarkedLike {
    parse: (markdown: string) => string;
}

interface DomPurifyLike {
    sanitize: (dirty: string) => string;
}

declare global {
    interface Window {
        marked?: MarkedLike;
        DOMPurify?: DomPurifyLike;
    }
}

export {};

// ──────────────────────────────────────────────
//  DOM element references
// ──────────────────────────────────────────────

/**
 * Typed getElementById helper.  Throws if the element is missing so downstream
 * code never has to null-check.
 */
const byId = <T extends HTMLElement = HTMLElement>(id: string): T => {
    const el = document.getElementById(id);
    if (!el) {
        throw new Error(`Missing required element #${id}`);
    }
    return el as T;
};

document.addEventListener("DOMContentLoaded", () => {
    // Core layout elements
    const sidebar = byId("sidebar");
    const backdrop = byId("sidebarBackdrop");
    const settingsOverlay = byId("settingsOverlay");
    const settingsPanel = byId("settingsPanel");
    const thread = byId("thread");
    const fab = byId("scrollFab");
    const dropdown = byId("slashDropdown");
    const ta = byId<HTMLTextAreaElement>("inputArea");

    // Attachment toolbar elements
    const attachPopover = byId("attachPopover");
    const webInputPanel = byId("webInputPanel");
    const kbPanel = byId("kbPanel");
    const cmdPicker = byId("cmdPicker");
    const attachBtn = byId("attachBtn");
    const cmdBtn = byId("cmdBtn");

    // ──────────────────────────────────────────────
    //  Sidebar logic (collapse, navigation, responsive)
    // ──────────────────────────────────────────────

    function isDesktop(): boolean {
        return window.innerWidth > 1024;
    }

    /** Show a specific sidebar panel by id. */
    function showPanel(panelId: string | undefined): void {
        document.querySelectorAll<HTMLElement>(".sidebar-panel").forEach((p) => {
            p.classList.remove("active");
        });
        if (panelId) {
            document.getElementById(panelId)?.classList.add("active");
        }
    }

    /** Mark a nav item as active and reveal its panel. */
    function setNavActive(el: HTMLElement): void {
        document.querySelectorAll<HTMLElement>(".sidebar-nav-item").forEach((n) => {
            n.classList.remove("active");
        });
        el.classList.add("active");
        if (!sidebar.classList.contains("collapsed")) {
            showPanel(el.dataset.panel);
        }
        // On mobile: close sidebar after selection
        if (!isDesktop()) {
            closeSidebar();
        }
    }

    /** Desktop: toggle between expanded (260 px) and icon-rail (56 px). */
    function toggleSidebarCollapse(): void {
        sidebar.classList.toggle("collapsed");
        const btn = byId("sidebarCollapseBtn");
        btn.innerHTML = sidebar.classList.contains("collapsed") ? "&#8250;" : "&#8249;";
        // Hide panels on collapse so icon rail stays clean
        if (sidebar.classList.contains("collapsed")) {
            document.querySelectorAll<HTMLElement>(".sidebar-panel").forEach((p) => {
                p.classList.remove("active");
            });
        } else {
            // Restore the active nav panel
            const activeNav = sidebar.querySelector<HTMLElement>(".sidebar-nav-item.active");
            if (activeNav) {
                showPanel(activeNav.dataset.panel);
            }
        }
    }

    /** Mobile: overlay open. */
    function openSidebar(): void {
        if (isDesktop()) {
            sidebar.classList.remove("collapsed");
            byId("sidebarCollapseBtn").innerHTML = "&#8249;";
            const activeNav = sidebar.querySelector<HTMLElement>(".sidebar-nav-item.active");
            if (activeNav) {
                showPanel(activeNav.dataset.panel);
            }
        } else {
            sidebar.classList.add("open");
            backdrop.classList.add("active");
        }
    }

    /** Mobile: overlay close. */
    function closeSidebar(): void {
        if (isDesktop()) {
            sidebar.classList.add("collapsed");
            byId("sidebarCollapseBtn").innerHTML = "&#8250;";
        } else {
            sidebar.classList.remove("open");
            backdrop.classList.remove("active");
        }
    }

    // External header button — only visible on mobile (CSS hides on desktop)
    byId("toggleBtn").addEventListener("click", () => {
        sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
    });

    // Wire up sidebar nav items
    document.querySelectorAll<HTMLElement>(".sidebar-nav-item").forEach((item) => {
        item.addEventListener("click", () => setNavActive(item));
    });

    // Wire up sidebar collapse button
    document.getElementById("sidebarCollapseBtn")?.addEventListener("click", toggleSidebarCollapse);

    // On resize: if going to desktop, close mobile overlay
    window.addEventListener("resize", () => {
        if (isDesktop()) {
            sidebar.classList.remove("open");
            backdrop.classList.remove("active");
        }
    });

    // Touch swipe-to-open (mobile)
    let touchStartX = 0;
    document.addEventListener(
        "touchstart",
        (e: TouchEvent) => {
            touchStartX = e.touches[0].clientX;
        },
        { passive: true },
    );
    document.addEventListener(
        "touchend",
        (e: TouchEvent) => {
            const dx = e.changedTouches[0].clientX - touchStartX;
            if (!isDesktop()) {
                if (dx > 60 && touchStartX < 30) openSidebar();
                if (dx < -60 && sidebar.classList.contains("open")) closeSidebar();
            }
        },
        { passive: true },
    );

    // ──────────────────────────────────────────────
    //  Settings panel (theme, presets, save/load/reset)
    // ──────────────────────────────────────────────

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
        if (localStorage.getItem("nc_theme") === "system") {
            applyThemeToDOM("system");
        }
    });

    // Wire up theme option buttons
    document.querySelectorAll<HTMLElement>(".theme-opt").forEach((el) => {
        el.addEventListener("click", () => {
            const val = el.dataset.themeVal || "dark";
            setTheme(val);
        });
    });

    /** Preset definitions for retrieval tuning. */
    const PRESETS: Record<string, PresetConfig> = {
        balanced: { searchLimit: 10, rerankTopK: 5 },
        precise: { searchLimit: 8, rerankTopK: 3 },
        broad: { searchLimit: 25, rerankTopK: 10 },
        fast: { searchLimit: 5, rerankTopK: 2 },
    };

    function applyPreset(name: string): void {
        const p = PRESETS[name];
        if (!p) return;
        const searchLimitEl = byId<HTMLInputElement>("searchLimit");
        const rerankTopKEl = byId<HTMLInputElement>("rerankTopK");
        searchLimitEl.value = String(p.searchLimit);
        byId("searchLimitVal").textContent = String(p.searchLimit);
        rerankTopKEl.value = String(p.rerankTopK);
        byId("rerankVal").textContent = String(p.rerankTopK);
    }

    // Wire up preset selector
    document.getElementById("presetSelect")?.addEventListener("change", (e: Event) => {
        const target = e.target as HTMLSelectElement;
        applyPreset(target.value);
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
            citations: byId<HTMLInputElement>("citationsToggle").checked,
        };
        localStorage.setItem("nc_settings", JSON.stringify(s));
        closeSettings();
        showToast("Settings saved");
    }

    function loadSettings(): void {
        const raw = localStorage.getItem("nc_settings");
        const s: Record<string, unknown> = raw ? JSON.parse(raw) : {};
        const theme = (localStorage.getItem("nc_theme") || (s.theme as string) || "dark");
        applyThemeToDOM(theme);
        if (s.preset) {
            byId<HTMLSelectElement>("presetSelect").value = s.preset as string;
        }
        if (s.searchLimit) {
            byId<HTMLInputElement>("searchLimit").value = s.searchLimit as string;
            byId("searchLimitVal").textContent = s.searchLimit as string;
        }
        if (s.rerankTopK) {
            byId<HTMLInputElement>("rerankTopK").value = s.rerankTopK as string;
            byId("rerankVal").textContent = s.rerankTopK as string;
        }
        if (s.streaming !== undefined) {
            byId<HTMLInputElement>("streamingToggle").checked = s.streaming as boolean;
        }
        if (s.citations !== undefined) {
            byId<HTMLInputElement>("citationsToggle").checked = s.citations as boolean;
        }
    }

    function resetSettings(): void {
        localStorage.removeItem("nc_settings");
        localStorage.removeItem("nc_theme");
        applyThemeToDOM("dark");
        byId<HTMLSelectElement>("presetSelect").value = "balanced";
        applyPreset("balanced");
        byId<HTMLInputElement>("streamingToggle").checked = true;
        byId<HTMLInputElement>("citationsToggle").checked = true;
        showToast("Settings reset to defaults");
    }

    // Wire up settings buttons
    document.getElementById("settingsBtn")?.addEventListener("click", openSettings);
    document.getElementById("customizeOpenSettings")?.addEventListener("click", openSettings);
    settingsOverlay.addEventListener("click", closeSettings);
    document.getElementById("settingsClose")?.addEventListener("click", closeSettings);
    document.getElementById("settingsSaveBtn")?.addEventListener("click", saveSettings);
    document.getElementById("settingsResetBtn")?.addEventListener("click", resetSettings);

    // Apply saved theme on load
    applyThemeToDOM(localStorage.getItem("nc_theme") || "dark");

    // ──────────────────────────────────────────────
    //  Scroll-to-bottom FAB
    // ──────────────────────────────────────────────

    let userScrolledUp = false;

    thread.addEventListener("scroll", () => {
        const atBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
        userScrolledUp = !atBottom;
        fab.classList.toggle("visible", userScrolledUp);
    });

    fab.addEventListener("click", () => {
        thread.scrollTop = thread.scrollHeight;
    });

    function scrollToBottom(): void {
        if (!userScrolledUp) {
            thread.scrollTop = thread.scrollHeight;
        }
    }

    // ──────────────────────────────────────────────
    //  Copy helpers and toast
    // ──────────────────────────────────────────────

    function showToast(msg: string): void {
        const t = byId("toast");
        t.textContent = msg;
        t.classList.add("show");
        setTimeout(() => t.classList.remove("show"), 2000);
    }

    function copyMsg(btn: HTMLElement, text: string): void {
        navigator.clipboard.writeText(text).then(() => {
            btn.classList.add("copied");
            btn.textContent = "\u2713 Copied";
            setTimeout(() => {
                btn.classList.remove("copied");
                btn.innerHTML = "&#128203; Copy";
            }, 2000);
        });
        showToast("Copied to clipboard");
    }

    function copyBubble(btn: HTMLElement, id: string): void {
        copyMsg(btn, document.getElementById(id)?.innerText || "");
    }

    // Expose copy helpers to inline onclick handlers in HTML
    (window as unknown as Record<string, unknown>)["copyMsg"] = copyMsg;
    (window as unknown as Record<string, unknown>)["copyBubble"] = copyBubble;
    (window as unknown as Record<string, unknown>)["showToast"] = showToast;

    // ──────────────────────────────────────────────
    //  Citation helpers
    // ──────────────────────────────────────────────

    function toggleCitation(card: HTMLElement): void {
        card.classList.toggle("expanded");
    }

    function toggleChunk(e: Event, id: string): void {
        e.stopPropagation();
        const el = byId(id);
        el.classList.toggle("show-all");
        const target = e.target as HTMLElement;
        target.textContent = el.classList.contains("show-all") ? "Show less" : "Show more";
    }

    // Expose citation helpers to inline onclick handlers in HTML
    (window as unknown as Record<string, unknown>)["toggleCitation"] = toggleCitation;
    (window as unknown as Record<string, unknown>)["toggleChunk"] = toggleChunk;

    // ──────────────────────────────────────────────
    //  Slash-command autocomplete
    // ──────────────────────────────────────────────

    const allCmds: HTMLElement[] = Array.from(dropdown.querySelectorAll<HTMLElement>(".slash-item"));
    let selIdx = 0;

    function closeDropdown(): void {
        dropdown.classList.remove("open");
    }

    function setSelected(i: number): void {
        const vis = allCmds.filter((x) => x.style.display !== "none");
        selIdx = (i + vis.length) % vis.length;
        vis.forEach((el, j) => el.classList.toggle("selected", j === selIdx));
    }

    function executeCmd(cmd: string): void {
        ta.value = cmd + " ";
        ta.focus();
        ta.style.height = "auto";
        closeDropdown();
    }

    function handleSlashInput(): void {
        const val = ta.value;
        if (!val.startsWith("/")) {
            closeDropdown();
            return;
        }
        const q = val.slice(1).toLowerCase();
        let vis = 0;
        allCmds.forEach((item) => {
            const cmdAttr = item.dataset.cmd || "";
            const descEl = item.querySelector<HTMLElement>(".slash-desc");
            const descText = descEl ? descEl.textContent?.toLowerCase() || "" : "";
            const match = cmdAttr.includes("/" + q) || descText.includes(q);
            item.style.display = match ? "" : "none";
            if (match) vis++;
        });
        if (!vis) {
            closeDropdown();
            return;
        }
        dropdown.classList.add("open");
        setSelected(0);
    }

    allCmds.forEach((item) => {
        item.addEventListener("click", () => executeCmd(item.dataset.cmd || ""));
    });

    // ──────────────────────────────────────────────
    //  Input textarea handling
    // ──────────────────────────────────────────────

    ta.addEventListener("input", () => {
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
        handleSlashInput();
    });

    ta.addEventListener("keydown", (e: KeyboardEvent) => {
        if (!dropdown.classList.contains("open")) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                triggerSend();
            }
            return;
        }
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setSelected(selIdx + 1);
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            setSelected(selIdx - 1);
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
            e.preventDefault();
            const vis = allCmds.filter((x) => x.style.display !== "none");
            if (vis[selIdx]) {
                executeCmd(vis[selIdx].dataset.cmd || "");
            }
        }
        if (e.key === "Escape") {
            closeDropdown();
        }
    });

    function triggerSend(): void {
        if (!ta.value.trim()) return;
        closeDropdown();
        ta.value = "";
        ta.style.height = "auto";
        startStream();
    }

    byId("sendBtn").addEventListener("click", triggerSend);

    // ──────────────────────────────────────────────
    //  Streaming simulation
    //  (will be replaced with real SSE/fetch API calls)
    // ──────────────────────────────────────────────

    const STREAM_TEXT =
        '512 tokens with 50-overlap is solid. Add a **cross-encoder reranker** after retrieval \u2014 it dramatically improves precision:\n\n' +
        "```python\n" +
        "from sentence_transformers import CrossEncoder\n\n" +
        'reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")\n' +
        "pairs = [(query, chunk.text) for chunk in retrieved]\n" +
        "scores = reranker.predict(pairs)\n" +
        "top5 = sorted(zip(scores, retrieved), reverse=True)[:5]\n" +
        "```\n\n" +
        "This keeps top-10 recall but cuts the noise sent to the LLM. Give it a try and let me know!";

    /** Minimal markdown-to-HTML converter for streaming preview. */
    function parseMarkdown(raw: string): string {
        const lines = raw.split("\n");
        let html = "";
        let inCode = false;
        let codeLines: string[] = [];
        let lang = "";
        for (const line of lines) {
            if (line.startsWith("```")) {
                if (!inCode) {
                    inCode = true;
                    codeLines = [];
                    lang = line.slice(3) || "code";
                } else {
                    const esc = codeLines
                        .join("\n")
                        .replace(/</g, "&lt;")
                        .replace(/>/g, "&gt;");
                    html +=
                        '<div class="code-block-wrap">' +
                        '<div class="code-block-header">' +
                        `<span>${lang}</span>` +
                        '<button class="copy-code-btn" onclick="navigator.clipboard.writeText(this.closest(\'.code-block-wrap\').querySelector(\'.code-block\').innerText);showToast(\'Code copied\')">Copy</button>' +
                        "</div>" +
                        `<div class="code-block">${esc}</div>` +
                        "</div>";
                    inCode = false;
                }
                continue;
            }
            if (inCode) {
                codeLines.push(line);
                continue;
            }
            if (line === "") {
                html += "<br>";
                continue;
            }
            html +=
                "<p>" +
                line
                    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                    .replace(/\*(.+?)\*/g, "<em>$1</em>")
                    .replace(/`([^`]+)`/g, "<code>$1</code>") +
                "</p>";
        }
        return html;
    }

    let streamTimer: ReturnType<typeof setInterval> | null = null;

    function startStream(): void {
        const bubble = byId("streaming-bubble");
        const typing = byId("typingIndicator");
        const actions = byId("streaming-actions");
        const meta = byId("streaming-meta");
        const cits = byId("streaming-citations");

        bubble.style.display = "none";
        bubble.innerHTML = "";
        typing.style.display = "flex";
        actions.style.display = "none";
        meta.style.display = "none";
        cits.style.display = "none";

        let idx = 0;
        let acc = "";
        let started = false;
        if (streamTimer) clearInterval(streamTimer);

        streamTimer = setInterval(() => {
            if (idx >= STREAM_TEXT.length) {
                clearInterval(streamTimer!);
                bubble.innerHTML = parseMarkdown(acc);
                const useCitations =
                    (document.getElementById("citationsToggle") as HTMLInputElement | null)
                        ?.checked !== false;
                if (useCitations) cits.style.display = "flex";
                actions.style.display = "flex";
                meta.style.display = "block";
                scrollToBottom();

                // After stream ends, advance context indicator
                setTimeout(() => {
                    const state = CTX_STATES[ctxTurn % CTX_STATES.length];
                    updateContextIndicator(state.pct, state.breakdown);
                    ctxTurn++;
                }, 2800);

                return;
            }
            if (!started) {
                typing.style.display = "none";
                bubble.style.display = "block";
                started = true;
            }
            acc += STREAM_TEXT.slice(idx, idx + 3);
            idx += 3;
            bubble.innerHTML = parseMarkdown(acc) + '<span class="cursor"></span>';
            scrollToBottom();
        }, 28);
    }

    // ──────────────────────────────────────────────
    //  Context window indicator
    // ──────────────────────────────────────────────

    const CTX_WINDOW = 200000; // Claude Sonnet 4.5 context window (tokens)

    function updateContextIndicator(pct: number, breakdown: ContextBreakdown): void {
        const chip = byId("ctxChip");
        const fill = byId("ctxBarFill");
        const label = byId("ctxPct");
        const compact = byId("ctxCompactBtn");

        // Update bar
        fill.style.width = Math.min(pct, 100) + "%";
        label.textContent = "~" + Math.round(pct) + "%";

        // State class
        chip.classList.remove("warn", "crit");
        if (pct >= 95) chip.classList.add("crit");
        else if (pct >= 80) chip.classList.add("warn");

        // Tooltip breakdown
        const fmt = (n: number): string => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n));
        byId("ttSystem").textContent = fmt(breakdown.system) + " tok";
        byId("ttMemory").textContent = fmt(breakdown.memory) + " tok";
        byId("ttChunks").textContent = fmt(breakdown.chunks) + " tok";
        byId("ttQuery").textContent = fmt(breakdown.query) + " tok";
        byId("ttTotal").textContent =
            fmt(breakdown.system + breakdown.memory + breakdown.chunks + breakdown.query) +
            " / " +
            fmt(CTX_WINDOW);

        // Show compact button only at critical
        compact.style.display = pct >= 95 ? "block" : "none";
    }

    // Simulate increasing context usage across turns
    const CTX_STATES: ContextState[] = [
        { pct: 18, breakdown: { system: 1200, memory: 800, chunks: 4200, query: 30 } },
        { pct: 34, breakdown: { system: 1200, memory: 2400, chunks: 8800, query: 45 } },
        { pct: 51, breakdown: { system: 1200, memory: 4100, chunks: 13600, query: 62 } },
        { pct: 83, breakdown: { system: 1200, memory: 7200, chunks: 22400, query: 80 } }, // warn
        { pct: 97, breakdown: { system: 1200, memory: 9800, chunks: 32000, query: 95 } }, // crit
    ];
    let ctxTurn = 0;

    // ──────────────────────────────────────────────
    //  Attachment toolbar helpers
    // ──────────────────────────────────────────────

    let attachments: AttachmentChip[] = [];

    function renderChips(): void {
        const container = byId("attachChips");
        container.innerHTML = "";
        attachments.forEach((a) => {
            const chip = document.createElement("div");
            chip.className = "attach-chip";
            chip.innerHTML =
                `<span class="attach-chip-icon">${a.icon}</span>` +
                `<span class="attach-chip-label">${a.label}</span>` +
                `<button class="attach-chip-remove" title="Remove">&#215;</button>`;
            const removeBtn = chip.querySelector<HTMLButtonElement>(".attach-chip-remove");
            removeBtn?.addEventListener("click", () => removeChip(a.id));
            container.appendChild(chip);
        });
    }

    function addChip(icon: string, label: string, id: string): void {
        if (attachments.find((a) => a.id === id)) return; // dedupe
        attachments.push({ id, icon, label });
        renderChips();
    }

    function removeChip(id: string): void {
        attachments = attachments.filter((a) => a.id !== id);
        renderChips();
    }

    // Expose removeChip for any inline onclick references
    (window as unknown as Record<string, unknown>)["removeChip"] = removeChip;

    /** Close all attachment / web / KB popovers. */
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
        closeAllPopovers();
        closeCmdPicker();
        if (!isOpen) {
            attachPopover.classList.add("open");
            attachBtn.classList.add("active");
        }
    }

    function openWebInput(): void {
        closeAllPopovers();
        webInputPanel.classList.add("open");
        setTimeout(() => document.getElementById("webUrlInput")?.focus(), 50);
    }

    function openKBSelect(): void {
        closeAllPopovers();
        kbPanel.classList.add("open");
    }

    // Wire up attachment button
    attachBtn.addEventListener("click", toggleAttachPopover);

    // Wire up popover action items (file, web, KB)
    document.getElementById("attachOptFile")?.addEventListener("click", triggerFileUpload);
    document.getElementById("attachOptWeb")?.addEventListener("click", openWebInput);
    document.getElementById("attachOptKB")?.addEventListener("click", openKBSelect);

    /** File upload. */
    function triggerFileUpload(): void {
        closeAllPopovers();
        byId<HTMLInputElement>("fileInput").click();
    }

    function handleFileSelect(input: HTMLInputElement): void {
        if (!input.files) return;
        Array.from(input.files).forEach((file) => {
            addChip("&#128196;", file.name, "file:" + file.name);
        });
        input.value = "";
        showToast("File added to context");
    }

    // Wire up file input change
    document.getElementById("fileInput")?.addEventListener("change", (e: Event) => {
        handleFileSelect(e.target as HTMLInputElement);
    });

    // Expose handleFileSelect for inline onchange
    (window as unknown as Record<string, unknown>)["handleFileSelect"] = handleFileSelect;

    /** Web URL attach. */
    function attachWebUrl(): void {
        const input = byId<HTMLInputElement>("webUrlInput");
        const url = input.value.trim();
        if (!url) return;
        try {
            new URL(url);
        } catch {
            showToast("Invalid URL");
            return;
        }
        const hostname = new URL(url).hostname.replace("www.", "");
        addChip("&#127760;", hostname, "web:" + url);
        input.value = "";
        webInputPanel.classList.remove("open");
        showToast("Web page added to context");
    }

    document.getElementById("webUrlInput")?.addEventListener("keydown", (e: KeyboardEvent) => {
        if (e.key === "Enter") attachWebUrl();
        if (e.key === "Escape") webInputPanel.classList.remove("open");
    });

    document.getElementById("webAddBtn")?.addEventListener("click", attachWebUrl);

    /** KB panel filter + attach. */
    function filterKB(q: string): void {
        document.querySelectorAll<HTMLElement>(".kb-item").forEach((el) => {
            const nameEl = el.querySelector<HTMLElement>(".kb-item-name");
            const name = nameEl ? nameEl.textContent?.toLowerCase() || "" : "";
            el.style.display = name.includes(q.toLowerCase()) ? "" : "none";
        });
    }

    function attachKBDocs(): void {
        document
            .querySelectorAll<HTMLInputElement>("#kbList input[type=checkbox]:checked")
            .forEach((cb) => {
                addChip("&#128218;", cb.value, "kb:" + cb.value);
                cb.checked = false;
            });
        kbPanel.classList.remove("open");
        showToast("Documents added to context");
    }

    // Wire up KB search and attach
    document.getElementById("kbSearch")?.addEventListener("input", (e: Event) => {
        filterKB((e.target as HTMLInputElement).value);
    });
    document.getElementById("kbAddBtn")?.addEventListener("click", attachKBDocs);

    // Expose helpers for inline handlers
    (window as unknown as Record<string, unknown>)["openWebInput"] = openWebInput;
    (window as unknown as Record<string, unknown>)["openKBSelect"] = openKBSelect;
    (window as unknown as Record<string, unknown>)["triggerFileUpload"] = triggerFileUpload;
    (window as unknown as Record<string, unknown>)["filterKB"] = filterKB;
    (window as unknown as Record<string, unknown>)["attachKBDocs"] = attachKBDocs;
    (window as unknown as Record<string, unknown>)["attachWebUrl"] = attachWebUrl;

    // ──────────────────────────────────────────────
    //  Command picker (REQ-216)
    // ──────────────────────────────────────────────

    const allPickerItems: HTMLElement[] = Array.from(
        document.querySelectorAll<HTMLElement>(".cmd-picker-item"),
    );
    let pickerIdx = 0;

    function setPickerSelected(idx: number): void {
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
        if (isOpen) {
            closeCmdPicker();
        } else {
            cmdPicker.classList.add("open");
            cmdBtn.classList.add("active");
            setPickerSelected(0);
        }
    }

    cmdBtn.addEventListener("click", toggleCmdPicker);
    document.getElementById("cmdPickerClose")?.addEventListener("click", closeCmdPicker);
    document.getElementById("kbPanelClose")?.addEventListener("click", closeAllPopovers);
    allPickerItems.forEach((item) => {
        item.addEventListener("click", () => executePicker(item));
    });

    // Keyboard nav for cmd picker
    document.addEventListener("keydown", (e: KeyboardEvent) => {
        if (!cmdPicker.classList.contains("open")) return;
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setPickerSelected(pickerIdx + 1);
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            setPickerSelected(pickerIdx - 1);
        }
        if (e.key === "Enter") {
            e.preventDefault();
            executePicker(allPickerItems[pickerIdx]);
        }
        if (e.key === "Escape") {
            closeCmdPicker();
        }
    });

    // ──────────────────────────────────────────────
    //  Outside click handler
    // ──────────────────────────────────────────────

    document.addEventListener("click", (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        if (!target.closest(".input-bar")) {
            closeAllPopovers();
            closeCmdPicker();
            closeDropdown();
            document.getElementById("ctxChip")?.classList.remove("tooltip-open");
        }
    });

    // ──────────────────────────────────────────────
    //  Initialization
    // ──────────────────────────────────────────────

    // Initial context indicator state
    updateContextIndicator(CTX_STATES[0].pct, CTX_STATES[0].breakdown);

    // Scroll thread to bottom on load
    setTimeout(() => {
        thread.scrollTop = thread.scrollHeight;
    }, 100);

    // Kick off initial streaming demo after a short delay
    setTimeout(startStream, 700);
});

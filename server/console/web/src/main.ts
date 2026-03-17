/**
 * @summary
 * TypeScript UI logic for the operator console. Replaces inline browser script
 * with typed request helpers and DOM adapters.
 * Exports: none (module side effects initialize UI)
 * Deps: browser fetch API, marked, DOMPurify
 * @end-summary
 */

type JsonObject = Record<string, unknown>;

type QueryResult = {
    score?: number;
    text?: string;
    metadata?: Record<string, unknown>;
};

type StreamEventData = {
    token?: string;
    message?: string;
    results?: QueryResult[];
    [key: string]: unknown;
};

type TokenBudgetPayload = {
    input_tokens?: number;
    context_length?: number;
    usage_percent?: number;
    model_name?: string;
    breakdown?: Record<string, number>;
    actual_prompt_tokens?: number;
    actual_completion_tokens?: number;
    cost_usd?: number;
};

type TimingPayload = {
    latency_ms?: number;
    retrieval_ms?: number;
    generation_ms?: number;
    token_count?: number;
    stage_timings?: Array<Record<string, unknown>>;
    timing_totals?: Record<string, unknown>;
    token_budget?: TokenBudgetPayload;
};

type ConsoleCommandSpec = {
    name: string;
    description: string;
    args_hint?: string;
    intent?: string;
};

type CommandExecution = {
    mode?: string;
    command?: string;
    intent?: string;
    action?: string;
    message?: string;
    data?: JsonObject;
};

type ConversationMeta = {
    conversation_id: string;
    title?: string;
    updated_at_ms?: number;
    message_count?: number;
};

type ConversationTurn = {
    role: string;
    content: string;
    timestamp_ms?: number;
};

type MarkedLike = {
    parse: (markdown: string) => string;
};

type DomPurifyLike = {
    sanitize: (dirty: string) => string;
};

declare global {
    interface Window {
        marked?: MarkedLike;
        DOMPurify?: DomPurifyLike;
    }
}

export {};

const byId = <T extends HTMLElement = HTMLElement>(id: string): T => {
    const el = document.getElementById(id);
    if (!el) {
        throw new Error(`Missing required element #${id}`);
    }
    return el as T;
};

let activeConversationId: string | null = null;
let conversationCache: ConversationMeta[] = [];
let convContextMenuTarget: string | null = null;
let _convMenuCloseHandler: ((e: MouseEvent) => void) | null = null;
let _convMenuEscapeHandler: ((e: KeyboardEvent) => void) | null = null;

const tabMap: Record<string, string> = {
    query: "tab-query",
    ingest: "tab-ingest",
    health: "tab-health",
    admin: "tab-admin",
};

function initTabs(): void {
    const tabs = document.querySelectorAll<HTMLButtonElement>(".tabs button");
    tabs.forEach((btn) => {
        btn.addEventListener("click", () => {
            tabs.forEach((t) => t.classList.remove("active"));
            btn.classList.add("active");
            Object.values(tabMap).forEach((id) => byId(id).classList.add("hidden"));
            const tabName = btn.dataset.tab || "";
            const targetId = tabMap[tabName];
            if (targetId) {
                byId(targetId).classList.remove("hidden");
            }
        });
    });
}

function authHeaders(): Record<string, string> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const apiKey = byId<HTMLInputElement>("apiKey").value.trim();
    const bearer = byId<HTMLInputElement>("bearerToken").value.trim();
    if (apiKey) {
        headers["x-api-key"] = apiKey;
    }
    if (bearer) {
        headers["Authorization"] = `Bearer ${bearer}`;
    }
    return headers;
}

async function api(method: string, path: string, body?: JsonObject): Promise<JsonObject> {
    const response = await fetch(path, {
        method,
        headers: authHeaders(),
        body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let payload: JsonObject;
    try {
        payload = text ? (JSON.parse(text) as JsonObject) : {};
    } catch {
        payload = { raw: text };
    }
    if (!response.ok) {
        const err = payload.error as JsonObject | undefined;
        const rawDetail = (payload as JsonObject).detail;
        const detailStr = typeof rawDetail === "string" ? rawDetail : undefined;
        const message: string =
            typeof err?.message === "string"
                ? err.message
                : detailStr ?? `HTTP ${response.status}`;
        throw new Error(message);
    }
    return payload;
}

function write(id: string, value: unknown): void {
    const out = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    byId(id).textContent = out;
}

function asNumber(value: unknown): number | null {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function asOptionalNumber(value: unknown): number | undefined {
    const n = asNumber(value);
    return n === null ? undefined : n;
}

function normalizeGeneratedAnswer(markdown: string): string {
    let text = markdown || "";
    if (!text) {
        return "";
    }

    // Some model outputs carry escaped newlines as literal characters.
    if (!text.includes("\n") && text.includes("\\n")) {
        text = text.replace(/\\n/g, "\n");
    }

    // Keep source previews in the dedicated rerank table instead of mixed into answer body.
    const rerankSectionIdx = text.search(/\n#{1,6}\s*Top reranked original documents\b/i);
    if (rerankSectionIdx >= 0) {
        text = text.slice(0, rerankSectionIdx).trimEnd();
    }

    // Remove wrapper headings that make the answer feel like a template.
    text = text.replace(/^\s*#{0,6}\s*Output(?:s)?\s*:?\s*$/gim, "");
    text = text.replace(/^\s*#{0,6}\s*Comprehensive Overview of the Entire System\s*:?\s*$/gim, "");
    text = text.replace(/^\s*Inputs?\s*:\s*$/gim, "");
    text = text.replace(/^\s*Outputs?\s*:\s*$/gim, "");

    // If a rigid template starts, keep only the answer lead.
    const templateCutCandidates = [
        text.search(/\n\s*Inputs?\s*:/i),
        text.search(/\n\s*Outputs?\s*:/i),
        text.search(/\n\s*Comprehensive Overview of the Entire System/i),
    ].filter((idx) => idx >= 0);
    if (templateCutCandidates.length > 0) {
        const cutIdx = Math.min(...templateCutCandidates);
        if (cutIdx > 0) {
            text = text.slice(0, cutIdx).trimEnd();
        }
    }

    // Remove noisy runtime placeholder lines if they appear in answer text.
    text = text.replace(
        /^<original source file unavailable in API runtime; showing reranked chunk excerpts>\s*$/gim,
        "",
    );
    return text.trim();
}

function renderMarkdown(id: string, markdown: string): void {
    const raw = normalizeGeneratedAnswer(markdown);
    const parsed = window.marked ? window.marked.parse(raw) : raw;
    const safe = window.DOMPurify ? window.DOMPurify.sanitize(parsed) : parsed;
    byId(id).innerHTML = safe || "<em>No answer generated yet.</em>";
}

const commandCache: Record<string, ConsoleCommandSpec[]> = {};

async function fetchConsoleCommands(mode: "query" | "ingest"): Promise<ConsoleCommandSpec[]> {
    if (commandCache[mode]) {
        return commandCache[mode];
    }
    const payload = await api("GET", `/console/commands?mode=${mode}`);
    const data = (payload.data as JsonObject | undefined) || {};
    const commands = Array.isArray(data.commands) ? (data.commands as ConsoleCommandSpec[]) : [];
    commandCache[mode] = commands;
    return commands;
}

function commandSummary(commands: ConsoleCommandSpec[]): string {
    if (!commands.length) {
        return "No commands available.";
    }
    return commands
        .map((cmd) => {
            const args = cmd.args_hint ? ` ${cmd.args_hint}` : "";
            return `/${cmd.name}${args} - ${cmd.description}`;
        })
        .join("\n");
}

function setSuggestions(elementId: string, commands: ConsoleCommandSpec[]): void {
    const out = byId(elementId);
    out.textContent = commands.map((cmd) => `/${cmd.name}`).join("  ");
}

function setActiveConversation(id: string | null): void {
    activeConversationId = id;
    byId("activeConversationLabel").textContent = `Active: ${id || "(auto/new on query)"}`;
    renderConversationList();
}

function parseSlash(raw: string): { name: string; arg: string } {
    const text = raw.trim();
    const normalized = (text.startsWith("/") ? text.slice(1) : text).trim();
    const [name, ...rest] = normalized.split(/\s+/);
    return {
        name: (name || "").toLowerCase(),
        arg: rest.join(" ").trim(),
    };
}

async function executeConsoleCommand(
    mode: "query" | "ingest",
    command: string,
    arg: string,
    state: JsonObject,
): Promise<CommandExecution> {
    const payload = await api("POST", "/console/command", {
        mode,
        command,
        arg,
        state,
    });
    const data = (payload.data as JsonObject | undefined) || {};
    return data as CommandExecution;
}

function queryStatusSnapshot(): JsonObject {
    return {
        query: byId<HTMLTextAreaElement>("queryText").value,
        search_limit: Number(byId<HTMLInputElement>("searchLimit").value || 10),
        rerank_top_k: Number(byId<HTMLInputElement>("rerankTopK").value || 5),
        conversation_id: activeConversationId,
        memory_enabled: byId<HTMLInputElement>("memoryEnabled").checked,
    };
}

function ingestStatusSnapshot(): JsonObject {
    return {
        mode: byId<HTMLSelectElement>("ingestMode").value,
        target_path: byId<HTMLInputElement>("targetPath").value.trim() || null,
        update_mode: byId<HTMLInputElement>("updateMode").checked,
        build_kg: byId<HTMLInputElement>("buildKg").checked,
        verbose_stages: byId<HTMLInputElement>("verboseStages").checked,
        docling_enabled: byId<HTMLInputElement>("doclingEnabled").checked,
        docling_model: byId<HTMLInputElement>("doclingModel").value.trim() || null,
        vision_enabled: byId<HTMLInputElement>("visionEnabled").checked,
        vision_provider: byId<HTMLSelectElement>("visionProvider").value,
        vision_model: byId<HTMLInputElement>("visionModel").value.trim() || null,
    };
}

function renderConversationList(): void {
    const out = byId("conversationList");
    if (!conversationCache.length) {
        out.innerHTML = '<div class="muted">No conversations yet.</div>';
        return;
    }
    const rows = conversationCache.map((item) => {
        const cid = item.conversation_id;
        const title = item.title || "New conversation";
        const msgCount = Number(item.message_count ?? 0);
        const klass = cid === activeConversationId ? "conversation-item active" : "conversation-item";
        return `<button class="${klass}" data-conv-id="${escapeHtml(cid)}"><div>${escapeHtml(title)}</div><div class="muted">${escapeHtml(cid)} • ${msgCount} turns</div></button>`;
    });
    out.innerHTML = rows.join("");
    out.querySelectorAll<HTMLButtonElement>("[data-conv-id]").forEach((btn) => {
        const cid = btn.dataset.convId || "";
        btn.addEventListener("click", async () => {
            if (!cid) return;
            setActiveConversation(cid);
            await loadConversationHistory();
        });
        btn.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            if (!cid) return;
            hideConvContextMenu();
            convContextMenuTarget = cid;
            const menu = byId("convContextMenu");
            menu.classList.add("visible");
            menu.style.left = `${e.clientX}px`;
            menu.style.top = `${e.clientY}px`;
            _convMenuCloseHandler = (ev: MouseEvent) => {
                const target = ev.target as Node;
                if (target && menu.contains(target)) return;
                hideConvContextMenu();
            };
            _convMenuEscapeHandler = (ev: KeyboardEvent) => {
                if (ev.key === "Escape") hideConvContextMenu();
            };
            document.addEventListener("mousedown", _convMenuCloseHandler);
            document.addEventListener("keydown", _convMenuEscapeHandler);
        });
    });
}

async function loadConversations(): Promise<void> {
    const out = await api("GET", "/console/conversations?limit=50");
    const data = (out.data as JsonObject | undefined) || {};
    const items = Array.isArray(data.conversations) ? (data.conversations as ConversationMeta[]) : [];
    conversationCache = items;
    if (!activeConversationId && items.length) {
        setActiveConversation(items[0].conversation_id);
    }
    renderConversationList();
}

async function createConversation(title = "New conversation"): Promise<void> {
    const out = await api("POST", "/console/conversations/new", { title });
    const data = (out.data as JsonObject | undefined) || {};
    const conv = (data.conversation as ConversationMeta | undefined) || null;
    if (conv && conv.conversation_id) {
        setActiveConversation(conv.conversation_id);
    }
    await loadConversations();
    await loadConversationHistory();
}

async function loadConversationHistory(): Promise<void> {
    const pane = byId("chatHistoryPane");
    if (!activeConversationId) {
        pane.textContent = "No history yet.";
        return;
    }
    const out = await api("GET", `/console/conversations/${encodeURIComponent(activeConversationId)}/history?limit=60`);
    const data = (out.data as JsonObject | undefined) || {};
    const turns = Array.isArray(data.turns) ? (data.turns as ConversationTurn[]) : [];
    if (!turns.length) {
        pane.textContent = "No history yet.";
        return;
    }
    pane.textContent = turns
        .map((turn) => `${turn.role.toUpperCase()}: ${turn.content}`)
        .join("\n\n");
    pane.scrollTop = pane.scrollHeight;
}

async function compactConversation(conversationId: string): Promise<void> {
    try {
        const payload = await api("POST", `/console/conversations/${encodeURIComponent(conversationId)}/compact`, {
            conversation_id: conversationId,
        });
        const data = (payload.data as JsonObject | undefined) || {};
        const summary = String(data.summary ?? "").trim();
        if (summary) {
            renderMarkdown("queryMarkdown", `### Compacted summary\n\n${summary}`);
        }
        await loadConversations();
        await loadConversationHistory();
    } catch (err) {
        renderMarkdown("queryMarkdown", `**Compact error:** ${escapeHtml(String(err))}`);
    }
}

async function compactActiveConversation(): Promise<void> {
    if (!activeConversationId) {
        renderMarkdown("queryMarkdown", "**/compact:** Select or create a conversation first.");
        return;
    }
    await compactConversation(activeConversationId);
}

async function deleteConversation(conversationId: string): Promise<boolean> {
    const payload = await api("DELETE", `/console/conversations/${encodeURIComponent(conversationId)}`);
    const data = (payload.data as JsonObject | undefined) || {};
    return Boolean(data.deleted);
}

async function deleteConversationWithFeedback(conversationId: string): Promise<void> {
    try {
        const deleted = await deleteConversation(conversationId);
        if (deleted && activeConversationId === conversationId) {
            setActiveConversation(null);
        }
        await loadConversations();
        await loadConversationHistory();
        if (deleted) {
            renderMarkdown("queryMarkdown", `**Deleted** conversation \`${escapeHtml(conversationId)}\`.`);
        } else {
            renderMarkdown("queryMarkdown", "**Delete:** Conversation not found (may already be deleted).");
        }
    } catch (err) {
        renderMarkdown("queryMarkdown", `**Delete error:** ${escapeHtml(String(err))}`);
    }
}

async function deleteActiveConversation(): Promise<void> {
    if (!activeConversationId) {
        renderMarkdown("queryMarkdown", "**/delete:** Select a conversation to delete first.");
        return;
    }
    await deleteConversationWithFeedback(activeConversationId);
}

function renderTiming(timing: TimingPayload | null): void {
    const el = byId("timingOut");
    if (!timing) {
        el.innerHTML = '<div class="muted">No timing yet.</div>';
        return;
    }

    const latency = asNumber(timing.latency_ms);
    const retrieval = asNumber(timing.retrieval_ms);
    const generation = asNumber(timing.generation_ms);
    const tokens = asNumber(timing.token_count);
    const totals = (timing.timing_totals || {}) as Record<string, unknown>;
    const stageTimings = Array.isArray(timing.stage_timings) ? timing.stage_timings : [];

    const metric = (key: string, value: string): string =>
        `<div class="timing-item"><div class="timing-key">${escapeHtml(key)}</div><div class="timing-val">${escapeHtml(value)}</div></div>`;

    const topGrid = [
        metric("Total", latency !== null ? `${latency.toFixed(1)} ms` : "n/a"),
        metric("Retrieval", retrieval !== null ? `${retrieval.toFixed(1)} ms` : "n/a"),
        metric("Generation", generation !== null ? `${generation.toFixed(1)} ms` : "n/a"),
        metric("Tokens", tokens !== null ? `${Math.round(tokens)}` : "n/a"),
    ].join("");

    const totalRows = Object.entries(totals)
        .map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`)
        .join("");
    const totalsTable = totalRows
        ? `<div style="margin-top:10px;"><div class="muted" style="margin-bottom:6px;">Bucket totals</div><table class="rerank-table"><thead><tr><th>Bucket</th><th>ms</th></tr></thead><tbody>${totalRows}</tbody></table></div>`
        : "";

    const stageRows = stageTimings
        .map((stage) => {
            const name = String(stage.stage ?? "unknown");
            const bucket = String(stage.bucket ?? "other");
            const ms = asNumber(stage.ms);
            return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(bucket)}</td><td>${escapeHtml(ms !== null ? ms.toFixed(1) : "n/a")}</td></tr>`;
        })
        .join("");
    const stageTable = stageRows
        ? `<div style="margin-top:10px;"><div class="muted" style="margin-bottom:6px;">Stage timings</div><table class="rerank-table"><thead><tr><th>Stage</th><th>Bucket</th><th>ms</th></tr></thead><tbody>${stageRows}</tbody></table></div>`
        : "";

    // Token budget / context window usage
    let budgetHtml = "";
    const tb = timing.token_budget;
    if (tb && typeof tb === "object") {
        const pct = tb.usage_percent ?? 0;
        const inp = tb.input_tokens ?? 0;
        const ctx = tb.context_length ?? 0;
        const mdl = tb.model_name ?? "";
        const pctColor = pct >= 90 ? "#f87171" : pct >= 70 ? "#facc15" : "#4ade80";
        let budgetRows = `<tr><td>Context usage</td><td style="color:${pctColor};font-weight:700">${pct.toFixed(0)}%</td><td>${inp} / ${ctx} tokens</td><td>${escapeHtml(mdl)}</td></tr>`;
        const bd = tb.breakdown;
        if (bd && typeof bd === "object") {
            budgetRows += `<tr><td colspan="4" style="color:var(--muted);font-size:12px">system:${bd.system_prompt ?? 0}  memory:${bd.memory_context ?? 0}  chunks:${bd.retrieval_chunks ?? 0}  query:${bd.user_query ?? 0}  overhead:${bd.template_overhead ?? 0}</td></tr>`;
        }
        const apt = tb.actual_prompt_tokens ?? 0;
        const act = tb.actual_completion_tokens ?? 0;
        if (apt) {
            budgetRows += `<tr><td>Actual tokens</td><td colspan="3">${apt} in + ${act} out = ${apt + act} total</td></tr>`;
        }
        if (tb.cost_usd && tb.cost_usd > 0) {
            budgetRows += `<tr><td>Cost</td><td colspan="3">$${tb.cost_usd.toFixed(4)}</td></tr>`;
        }
        budgetHtml = `<div style="margin-top:10px;"><div class="muted" style="margin-bottom:6px;">Context window</div><table class="rerank-table"><tbody>${budgetRows}</tbody></table></div>`;
    }

    el.innerHTML = `<div class="timing-grid">${topGrid}</div>${budgetHtml}${totalsTable}${stageTable}`;
}

function escapeHtml(value: unknown): string {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function rerankSourceLink(metadata: Record<string, unknown>): { label: string; href: string } {
    const source = String(metadata.source ?? "").trim();
    const sourceUri = String(metadata.source_uri ?? "").trim();
    const chunkIdxRaw = Number(metadata.chunk_index);
    const chunkIdx = Number.isFinite(chunkIdxRaw) ? chunkIdxRaw : null;
    const start = Number(metadata.original_char_start);
    const end = Number(metadata.original_char_end);
    const params = new URLSearchParams();
    if (sourceUri) {
        params.set("source_uri", sourceUri);
    } else if (source) {
        params.set("source", source);
    } else {
        return { label: "unknown", href: "" };
    }
    if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
        params.set("start", String(start));
        params.set("end", String(end));
    }
    if (chunkIdx !== null && chunkIdx >= 0) {
        params.set("chunk", String(chunkIdx + 1));
    }
    const display = sourceUri || source;
    return {
        label: display,
        href: `/console/source-document/view?${params.toString()}`,
    };
}

function formatChunkNumber(metadata: Record<string, unknown>): string {
    const idx = Number(metadata.chunk_index);
    if (!Number.isFinite(idx) || idx < 0) {
        return "n/a";
    }
    return String(idx + 1);
}

function compactExcerpt(text: string, maxLen = 220): string {
    const flat = text.replace(/\s+/g, " ").trim();
    if (!flat) {
        return "<no excerpt>";
    }
    if (flat.length <= maxLen) {
        return flat;
    }
    return `${flat.slice(0, maxLen)}...`;
}

async function renderRerankedOriginalDocs(results: QueryResult[]): Promise<void> {
    const out = byId("rerankDocsOut");
    if (!Array.isArray(results) || results.length === 0) {
        out.innerHTML = '<div class="muted">No reranked results.</div>';
        return;
    }
    const rows = results.map((r, i) => {
        const metadata = (r.metadata || {}) as Record<string, unknown>;
        const link = rerankSourceLink(metadata);
        const score = Number(r.score);
        const scoreText = Number.isFinite(score) ? score.toFixed(4) : "n/a";
        const chunkNo = formatChunkNumber(metadata);
        const excerpt = compactExcerpt(String(r.text || ""));
        const sourceCell = link.href
            ? `<a class="source-link" target="_blank" rel="noopener noreferrer" href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`
            : `<span>${escapeHtml(link.label)}</span>`;
        return (
            "<tr>" +
            `<td>${i + 1}</td>` +
            `<td>${sourceCell}</td>` +
            `<td><code>${escapeHtml(chunkNo)}</code></td>` +
            `<td><code>${escapeHtml(scoreText)}</code></td>` +
            `<td>${escapeHtml(excerpt)}</td>` +
            "</tr>"
        );
    });
    out.innerHTML =
        '<table class="rerank-table">' +
        "<thead><tr><th>#</th><th>Document</th><th>Chunk</th><th>Score</th><th>Excerpt</th></tr></thead>" +
        `<tbody>${rows.join("")}</tbody>` +
        "</table>";
}

async function refreshHealth(): Promise<void> {
    try {
        const data = await api("GET", "/console/health");
        write("healthOut", data);
        const status = String(((data.data as JsonObject | undefined)?.status as string | undefined) || "unknown");
        const pill = byId("healthPill");
        pill.textContent = status;
        pill.className = `pill ${status === "healthy" ? "ok" : "warn"}`;
    } catch (err) {
        const pill = byId("healthPill");
        pill.textContent = "error";
        pill.className = "pill err";
        write("healthOut", String(err));
    }
}

async function initSlashCommandHints(): Promise<void> {
    try {
        const [queryCmds, ingestCmds] = await Promise.all([
            fetchConsoleCommands("query"),
            fetchConsoleCommands("ingest"),
        ]);
        setSuggestions("querySlashSuggestions", queryCmds);
        setSuggestions("ingestSlashSuggestions", ingestCmds);
    } catch {
        setSuggestions("querySlashSuggestions", []);
        setSuggestions("ingestSlashSuggestions", []);
    }
}

function bindQueryActions(): void {
    byId("runQueryBtn").addEventListener("click", async () => {
        try {
            const payload = {
                query: byId<HTMLTextAreaElement>("queryText").value,
                search_limit: Number(byId<HTMLInputElement>("searchLimit").value || 10),
                rerank_top_k: Number(byId<HTMLInputElement>("rerankTopK").value || 5),
                stream: false,
                conversation_id: activeConversationId,
                memory_enabled: byId<HTMLInputElement>("memoryEnabled").checked,
            };
            const out = await api("POST", "/console/query", payload);
            const data = (out.data as JsonObject | undefined) || out;
            if (typeof data.conversation_id === "string" && data.conversation_id) {
                setActiveConversation(data.conversation_id);
            }
            renderMarkdown("queryMarkdown", String((data.generated_answer as string | undefined) || ""));
            await renderRerankedOriginalDocs((data.results as QueryResult[] | undefined) || []);
            renderTiming({
                latency_ms: asOptionalNumber(data.latency_ms),
                stage_timings: (data.stage_timings as Array<Record<string, unknown>> | undefined) || [],
                timing_totals: (data.timing_totals as Record<string, unknown> | undefined) || {},
            });
            await loadConversations();
            await loadConversationHistory();
        } catch (err) {
            renderMarkdown("queryMarkdown", `**Query error:** ${String(err)}`);
            byId("rerankDocsOut").innerHTML = '<div class="muted">No reranked results.</div>';
            renderTiming(null);
        }
    });

    byId("runStreamBtn").addEventListener("click", async () => {
        byId("rerankDocsOut").innerHTML = "";
        renderTiming(null);
        const body = {
            query: byId<HTMLTextAreaElement>("queryText").value,
            search_limit: Number(byId<HTMLInputElement>("searchLimit").value || 10),
            rerank_top_k: Number(byId<HTMLInputElement>("rerankTopK").value || 5),
            conversation_id: activeConversationId,
            memory_enabled: byId<HTMLInputElement>("memoryEnabled").checked,
        };
        const response = await fetch("/query/stream", {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify(body),
        });
        if (!response.ok || !response.body) {
            renderMarkdown("queryMarkdown", `**Stream error:** Failed to open stream (HTTP ${response.status}).`);
            return;
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let chunkBuffer = "";
        let answer = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                break;
            }
            chunkBuffer += decoder.decode(value, { stream: true });
            const events = chunkBuffer.split("\n\n");
            chunkBuffer = events.pop() || "";
            for (const evt of events) {
                const lines = evt.split("\n");
                const eventLine = lines.find((line) => line.startsWith("event: "));
                const dataLine = lines.find((line) => line.startsWith("data: "));
                const eventType = eventLine ? eventLine.slice(7) : "";
                const dataRaw = dataLine ? dataLine.slice(6) : "{}";
                let data: StreamEventData;
                try {
                    data = JSON.parse(dataRaw) as StreamEventData;
                } catch {
                    data = { raw: dataRaw };
                }

                if (eventType === "token") {
                    answer += data.token || "";
                    renderMarkdown("queryMarkdown", answer);
                } else if (eventType === "retrieval") {
                    const cid = typeof data.conversation_id === "string" ? data.conversation_id : "";
                    if (cid) {
                        setActiveConversation(cid);
                    }
                    await renderRerankedOriginalDocs(data.results || []);
                } else if (eventType === "error") {
                    renderMarkdown("queryMarkdown", `**Stream error:** ${String(data.message || JSON.stringify(data))}`);
                } else if (eventType === "done") {
                    const cid = typeof data.conversation_id === "string" ? data.conversation_id : "";
                    if (cid) {
                        setActiveConversation(cid);
                    }
                    renderMarkdown("queryMarkdown", answer);
                    renderTiming({
                        latency_ms: asOptionalNumber(data.latency_ms),
                        retrieval_ms: asOptionalNumber(data.retrieval_ms),
                        generation_ms: asOptionalNumber(data.generation_ms),
                        token_count: asOptionalNumber(data.token_count),
                        stage_timings: (data.stage_timings as Array<Record<string, unknown>> | undefined) || [],
                        timing_totals: (data.timing_totals as Record<string, unknown> | undefined) || {},
                        token_budget: (data.token_budget as TokenBudgetPayload | undefined) || undefined,
                    });
                    await loadConversations();
                    await loadConversationHistory();
                }
            }
        }
    });

    byId("querySlashRunBtn").addEventListener("click", async () => {
        const input = byId<HTMLInputElement>("querySlashInput");
        const { name, arg } = parseSlash(input.value);
        if (!name) {
            return;
        }
        try {
            const result = await executeConsoleCommand("query", name, arg, queryStatusSnapshot());
            const action = String(result.action || "noop");
            if (action === "run_stream_query") {
                byId("runStreamBtn").click();
            } else if (action === "run_non_stream_query") {
                byId("runQueryBtn").click();
            } else if (action === "list_conversations") {
                await loadConversations();
                await loadConversationHistory();
            } else if (action === "new_conversation") {
                const conversation = (result.data?.conversation as ConversationMeta | undefined) || null;
                if (conversation?.conversation_id) {
                    setActiveConversation(conversation.conversation_id);
                } else {
                    await createConversation("New conversation");
                }
                await loadConversations();
                await loadConversationHistory();
            } else if (action === "switch_conversation") {
                const cid = String(result.data?.conversation_id || arg || "").trim();
                if (cid) {
                    setActiveConversation(cid);
                    await loadConversationHistory();
                }
            } else if (action === "show_history") {
                await loadConversationHistory();
            } else if (action === "compact_conversation") {
                const summary = String(result.data?.summary ?? "").trim();
                if (summary) {
                    renderMarkdown("queryMarkdown", `### Compacted summary\n\n${summary}`);
                }
                await loadConversations();
                await loadConversationHistory();
            } else if (action === "delete_conversation") {
                const deleted = Boolean(result.data?.deleted);
                const cid = String(result.data?.conversation_id ?? "").trim();
                if (deleted && cid && activeConversationId === cid) {
                    setActiveConversation(null);
                }
                await loadConversations();
                if (deleted) {
                    renderMarkdown("queryMarkdown", `**Deleted** conversation \`${escapeHtml(cid)}\`.`);
                } else {
                    renderMarkdown("queryMarkdown", "**/delete:** Conversation not found (may already be deleted).");
                }
            } else if (action === "clear_view") {
                renderMarkdown("queryMarkdown", "");
                byId("rerankDocsOut").innerHTML = "";
                renderTiming(null);
            } else if (action === "refresh_health") {
                await refreshHealth();
                renderMarkdown(
                    "queryMarkdown",
                    `\`\`\`json\n${JSON.stringify(queryStatusSnapshot(), null, 2)}\n\`\`\``,
                );
            } else if (action === "render_help") {
                const cmds = Array.isArray(result.data?.commands)
                    ? (result.data?.commands as ConsoleCommandSpec[])
                    : [];
                renderMarkdown(
                    "queryMarkdown",
                    `### Query Slash Commands\n\n\`\`\`\n${commandSummary(cmds)}\n\`\`\``,
                );
            } else if (action === "render_status") {
                const state = (result.data?.state as JsonObject | undefined) || queryStatusSnapshot();
                renderMarkdown("queryMarkdown", `\`\`\`json\n${JSON.stringify(state, null, 2)}\n\`\`\``);
            } else {
                renderMarkdown("queryMarkdown", result.message || `No action mapped for /${name}`);
            }
        } catch (err) {
            renderMarkdown("queryMarkdown", `**Command error:** ${String(err)}`);
        }
        input.value = "";
    });

    byId("querySlashInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            byId("querySlashRunBtn").click();
        }
    });
}

function hideConvContextMenu(): void {
    const menu = byId("convContextMenu");
    menu.classList.remove("visible");
    convContextMenuTarget = null;
    if (_convMenuCloseHandler) {
        document.removeEventListener("mousedown", _convMenuCloseHandler);
        _convMenuCloseHandler = null;
    }
    if (_convMenuEscapeHandler) {
        document.removeEventListener("keydown", _convMenuEscapeHandler);
        _convMenuEscapeHandler = null;
    }
}

function bindConversationActions(): void {
    byId("newConversationBtn").addEventListener("click", async () => {
        await createConversation("New conversation");
    });
    byId("refreshConversationsBtn").addEventListener("click", async () => {
        await loadConversations();
        await loadConversationHistory();
    });
    byId("compactConversationBtn").addEventListener("click", async () => {
        await compactActiveConversation();
    });
    byId("deleteConversationBtn").addEventListener("click", async () => {
        await deleteActiveConversation();
    });

    const menu = byId("convContextMenu");
    menu.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const cid = convContextMenuTarget;
            hideConvContextMenu();
            if (!cid) return;
            if (btn.dataset.action === "compact") {
                await compactConversation(cid);
            } else if (btn.dataset.action === "delete") {
                await deleteConversationWithFeedback(cid);
            }
        });
    });
}

function bindIngestionActions(): void {
    byId("runIngestBtn").addEventListener("click", async () => {
        try {
            const payload = {
                mode: byId<HTMLSelectElement>("ingestMode").value,
                target_path: byId<HTMLInputElement>("targetPath").value.trim() || null,
                update_mode: byId<HTMLInputElement>("updateMode").checked,
                build_kg: byId<HTMLInputElement>("buildKg").checked,
                verbose_stages: byId<HTMLInputElement>("verboseStages").checked,
                docling_enabled: byId<HTMLInputElement>("doclingEnabled").checked,
                docling_model: byId<HTMLInputElement>("doclingModel").value.trim() || null,
                docling_artifacts_path: byId<HTMLInputElement>("doclingArtifactsPath").value.trim() || null,
                docling_strict: byId<HTMLInputElement>("doclingStrict").checked,
                docling_auto_download: byId<HTMLInputElement>("doclingAutoDownload").checked,
                vision_enabled: byId<HTMLInputElement>("visionEnabled").checked,
                vision_provider: byId<HTMLSelectElement>("visionProvider").value,
                vision_model: byId<HTMLInputElement>("visionModel").value.trim() || null,
                vision_api_base_url: byId<HTMLInputElement>("visionApiBaseUrl").value.trim() || null,
                vision_max_figures: Number(byId<HTMLInputElement>("visionMaxFigures").value || 4),
                vision_timeout_seconds: Number(byId<HTMLInputElement>("visionTimeoutSeconds").value || 60),
                vision_auto_pull: byId<HTMLInputElement>("visionAutoPull").checked,
                vision_strict: byId<HTMLInputElement>("visionStrict").checked,
            };
            const out = await api("POST", "/console/ingest", payload);
            write("ingestOut", out);
        } catch (err) {
            write("ingestOut", String(err));
        }
    });

    byId("ingestSlashRunBtn").addEventListener("click", async () => {
        const input = byId<HTMLInputElement>("ingestSlashInput");
        const { name, arg } = parseSlash(input.value);
        if (!name) {
            return;
        }
        try {
            const result = await executeConsoleCommand("ingest", name, arg, ingestStatusSnapshot());
            const action = String(result.action || "noop");
            if (action === "run_ingest") {
                byId("runIngestBtn").click();
            } else if (action === "clear_view") {
                write("ingestOut", "");
            } else if (action === "render_status") {
                write("ingestOut", (result.data?.state as JsonObject | undefined) || ingestStatusSnapshot());
            } else if (action === "render_help") {
                const cmds = Array.isArray(result.data?.commands)
                    ? (result.data?.commands as ConsoleCommandSpec[])
                    : [];
                write("ingestOut", commandSummary(cmds));
            } else {
                write("ingestOut", result.message || `No action mapped for /${name}`);
            }
        } catch (err) {
            write("ingestOut", `Command error: ${String(err)}`);
        }
        input.value = "";
    });

    byId("ingestSlashInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            byId("ingestSlashRunBtn").click();
        }
    });
}

function bindHealthActions(): void {
    byId("refreshHealthBtn").addEventListener("click", refreshHealth);
    byId("pingBtn").addEventListener("click", refreshHealth);
    byId("refreshLogsBtn").addEventListener("click", async () => {
        try {
            const out = await api("GET", "/console/logs?lines=200");
            write("logsOut", out);
        } catch (err) {
            write("logsOut", String(err));
        }
    });
}

function bindAdminActions(): void {
    byId("listKeysBtn").addEventListener("click", async () => {
        try {
            write("adminOut", await api("GET", "/console/admin/api-keys"));
        } catch (err) {
            write("adminOut", String(err));
        }
    });
    byId("listQuotasBtn").addEventListener("click", async () => {
        try {
            write("adminOut", await api("GET", "/console/admin/quotas"));
        } catch (err) {
            write("adminOut", String(err));
        }
    });
    byId("createKeyBtn").addEventListener("click", async () => {
        try {
            const out = await api("POST", "/console/admin/api-keys", {
                subject: byId<HTMLInputElement>("newKeySubject").value.trim(),
                tenant_id: byId<HTMLInputElement>("newKeyTenant").value.trim() || null,
                roles: ["query"],
                description: "Created from operator console",
            });
            write("adminOut", out);
        } catch (err) {
            write("adminOut", String(err));
        }
    });
}

function initializeConsoleUi(): void {
    initTabs();
    bindQueryActions();
    bindConversationActions();
    bindIngestionActions();
    bindHealthActions();
    bindAdminActions();
    renderMarkdown("queryMarkdown", "");
    renderTiming(null);
    void initSlashCommandHints();
    void loadConversations().then(loadConversationHistory).catch(() => undefined);
    void refreshHealth();
}

initializeConsoleUi();

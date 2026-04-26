/**
 * @summary
 * Query tab handlers, SSE stream consumer, and slash-command dispatcher for the
 * admin/operator console.
 * Exports: queryStatusSnapshot, bindQuery
 * Deps: admin-types, admin-state, admin-api, admin-render, admin-conversations,
 *   admin-health
 * @end-summary
 */
import { getActiveConversationId } from "./admin-state.js";
import { api, authHeaders, byId, executeConsoleCommand, parseSlash, } from "./admin-api.js";
import { asOptionalNumber, commandSummary, escapeHtml, renderMarkdown, renderRerankedOriginalDocs, renderTiming, } from "./admin-render.js";
import { createConversation, loadConversationHistory, loadConversations, setActiveConversation, } from "./admin-conversations.js";
import { refreshHealth } from "./admin-health.js";
export function queryStatusSnapshot() {
    return {
        query: byId("queryText").value,
        search_limit: Number(byId("searchLimit").value || 10),
        rerank_top_k: Number(byId("rerankTopK").value || 5),
        conversation_id: getActiveConversationId(),
        memory_enabled: byId("memoryEnabled").checked,
    };
}
export function bindQuery() {
    byId("runQueryBtn").addEventListener("click", async () => {
        try {
            const payload = {
                query: byId("queryText").value,
                search_limit: Number(byId("searchLimit").value || 10),
                rerank_top_k: Number(byId("rerankTopK").value || 5),
                stream: false,
                conversation_id: getActiveConversationId(),
                memory_enabled: byId("memoryEnabled").checked,
            };
            const out = await api("POST", "/console/query", payload);
            const data = out.data || out;
            if (typeof data.conversation_id === "string" && data.conversation_id) {
                setActiveConversation(data.conversation_id);
            }
            renderMarkdown("queryMarkdown", String(data.generated_answer || ""));
            await renderRerankedOriginalDocs(data.results || []);
            renderTiming({
                latency_ms: asOptionalNumber(data.latency_ms),
                stage_timings: data.stage_timings || [],
                timing_totals: data.timing_totals || {},
            });
            await loadConversations();
            await loadConversationHistory();
        }
        catch (err) {
            renderMarkdown("queryMarkdown", `**Query error:** ${String(err)}`);
            byId("rerankDocsOut").innerHTML = '<div class="muted">No reranked results.</div>';
            renderTiming(null);
        }
    });
    byId("runStreamBtn").addEventListener("click", async () => {
        byId("rerankDocsOut").innerHTML = "";
        renderTiming(null);
        const body = {
            query: byId("queryText").value,
            search_limit: Number(byId("searchLimit").value || 10),
            rerank_top_k: Number(byId("rerankTopK").value || 5),
            conversation_id: getActiveConversationId(),
            memory_enabled: byId("memoryEnabled").checked,
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
                let data;
                try {
                    data = JSON.parse(dataRaw);
                }
                catch {
                    data = { raw: dataRaw };
                }
                if (eventType === "token") {
                    answer += data.token || "";
                    renderMarkdown("queryMarkdown", answer);
                }
                else if (eventType === "retrieval") {
                    const cid = typeof data.conversation_id === "string" ? data.conversation_id : "";
                    if (cid) {
                        setActiveConversation(cid);
                    }
                    await renderRerankedOriginalDocs(data.results || []);
                }
                else if (eventType === "error") {
                    renderMarkdown("queryMarkdown", `**Stream error:** ${String(data.message || JSON.stringify(data))}`);
                }
                else if (eventType === "done") {
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
                        stage_timings: data.stage_timings || [],
                        timing_totals: data.timing_totals || {},
                        token_budget: data.token_budget || undefined,
                    });
                    await loadConversations();
                    await loadConversationHistory();
                }
            }
        }
    });
    byId("querySlashRunBtn").addEventListener("click", async () => {
        const input = byId("querySlashInput");
        const { name, arg } = parseSlash(input.value);
        if (!name) {
            return;
        }
        try {
            const result = await executeConsoleCommand("query", name, arg, queryStatusSnapshot());
            const action = String(result.action || "noop");
            if (action === "run_stream_query") {
                byId("runStreamBtn").click();
            }
            else if (action === "run_non_stream_query") {
                byId("runQueryBtn").click();
            }
            else if (action === "list_conversations") {
                await loadConversations();
                await loadConversationHistory();
            }
            else if (action === "new_conversation") {
                const conversation = result.data?.conversation || null;
                if (conversation?.conversation_id) {
                    setActiveConversation(conversation.conversation_id);
                }
                else {
                    await createConversation("New conversation");
                }
                await loadConversations();
                await loadConversationHistory();
            }
            else if (action === "switch_conversation") {
                const cid = String(result.data?.conversation_id || arg || "").trim();
                if (cid) {
                    setActiveConversation(cid);
                    await loadConversationHistory();
                }
            }
            else if (action === "show_history") {
                await loadConversationHistory();
            }
            else if (action === "compact_conversation") {
                const summary = String(result.data?.summary ?? "").trim();
                if (summary) {
                    renderMarkdown("queryMarkdown", `### Compacted summary\n\n${summary}`);
                }
                await loadConversations();
                await loadConversationHistory();
            }
            else if (action === "delete_conversation") {
                const deleted = Boolean(result.data?.deleted);
                const cid = String(result.data?.conversation_id ?? "").trim();
                if (deleted && cid && getActiveConversationId() === cid) {
                    setActiveConversation(null);
                }
                await loadConversations();
                if (deleted) {
                    renderMarkdown("queryMarkdown", `**Deleted** conversation \`${escapeHtml(cid)}\`.`);
                }
                else {
                    renderMarkdown("queryMarkdown", "**/delete:** Conversation not found (may already be deleted).");
                }
            }
            else if (action === "clear_view") {
                renderMarkdown("queryMarkdown", "");
                byId("rerankDocsOut").innerHTML = "";
                renderTiming(null);
            }
            else if (action === "refresh_health") {
                await refreshHealth();
                renderMarkdown("queryMarkdown", `\`\`\`json\n${JSON.stringify(queryStatusSnapshot(), null, 2)}\n\`\`\``);
            }
            else if (action === "render_help") {
                const cmds = Array.isArray(result.data?.commands)
                    ? result.data?.commands
                    : [];
                renderMarkdown("queryMarkdown", `### Query Slash Commands\n\n\`\`\`\n${commandSummary(cmds)}\n\`\`\``);
            }
            else if (action === "render_status") {
                const state = result.data?.state || queryStatusSnapshot();
                renderMarkdown("queryMarkdown", `\`\`\`json\n${JSON.stringify(state, null, 2)}\n\`\`\``);
            }
            else {
                renderMarkdown("queryMarkdown", result.message || `No action mapped for /${name}`);
            }
        }
        catch (err) {
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

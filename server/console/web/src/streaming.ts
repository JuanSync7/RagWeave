// @summary
// Query execution: SSE streaming + non-stream fallback. Owns sendQuery as the
// canonical entry point for any plain-text user message; slash-command flows
// reuse streamQuery/nonStreamQuery directly.
// @end-summary

import { byId, escHtml, fmtTime } from "./dom";
import { api, apiBase, authHeaders, getSettings } from "./api";
import { parseMarkdown } from "./markdown";
import { state, setActiveConversation } from "./state";
import { appendUserMsg, appendErrorMsg, appendPendingAssistant } from "./thread";
import { scrollToBottom } from "./scrollFab";
import { buildCitationsHtml, revealCitations } from "./citations";
import { updateContextIndicator } from "./contextWindow";
import { loadConversations, updateConvTitle } from "./conversations";
import type { ChunkResult, StreamEventData, TokenBudget } from "./user-types";

function buildQueryBody(queryText: string): Record<string, unknown> {
    const s = getSettings();
    return {
        query: queryText,
        search_limit: parseInt(String(s.searchLimit ?? "10"), 10),
        rerank_top_k: parseInt(String(s.rerankTopK ?? "5"), 10),
        memory_enabled: s.memory_enabled !== false,
        conversation_id: state.activeConversationId ?? undefined,
    };
}

export async function streamQuery(queryText: string): Promise<void> {
    if (state.isStreaming) {
        state.streamAbortCtrl?.abort();
    }
    state.isStreaming = true;
    state.streamAbortCtrl = new AbortController();

    appendUserMsg(queryText);
    const { bubbleEl, typingEl, citationsEl, actionsEl, metaEl } = appendPendingAssistant();

    const url = apiBase() + "/query/stream";
    let response: Response;
    try {
        response = await fetch(url, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify(buildQueryBody(queryText)),
            signal: state.streamAbortCtrl.signal,
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
                let data: StreamEventData;
                try {
                    data = JSON.parse(dataRaw) as StreamEventData;
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
                    if (tb?.usage_percent !== undefined) {
                        const bd = tb.breakdown ?? {};
                        updateContextIndicator(tb.usage_percent * 100, {
                            system: Number(bd.system_tokens ?? bd.system ?? 0),
                            memory: Number(bd.memory_tokens ?? bd.memory ?? 0),
                            chunks: Number(bd.chunk_tokens ?? bd.chunks ?? 0),
                            query: Number(bd.query_tokens ?? bd.query ?? 0),
                        });
                    }

                    const results = (data.results ?? []) as ChunkResult[];
                    const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
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
                            const msg =
                                pendingClarification ||
                                "I couldn't find relevant information for that query. " +
                                    "Could you rephrase your question or provide more details?";
                            bubbleEl.innerHTML = parseMarkdown(msg);
                            bubbleEl.style.display = "block";
                        } else {
                            bubbleEl.innerHTML = parseMarkdown(answer);
                            bubbleEl.style.display = "block";
                        }
                    }

                    const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
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
        if ((err as Error).name !== "AbortError") {
            appendErrorMsg("Stream interrupted: " + String(err));
        }
    } finally {
        cancelRender();
        bubbleEl.classList.remove("streaming");
    }

    state.isStreaming = false;
}

export async function nonStreamQuery(queryText: string): Promise<void> {
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
                chunks: Number(bd.chunk_tokens ?? 0),
                query: Number(bd.query_tokens ?? 0),
            });
        }

        const showCitations = byId<HTMLInputElement>("citationsToggle").checked;
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

export async function sendQuery(text: string): Promise<void> {
    const s = getSettings();
    const useStreaming = s.streaming !== false;
    if (useStreaming) await streamQuery(text);
    else await nonStreamQuery(text);
}

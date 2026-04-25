// @summary
// Context-window usage indicator (chip + tooltip + breakdown) and compact button.
// Consumed by streaming.ts on each retrieval/done event.
// @end-summary

import { byId } from "./dom";
import { api } from "./api";
import { state } from "./state";
import { showToast } from "./toast";
import type { ContextBreakdown } from "./user-types";

export function updateContextIndicator(pct: number, bd?: Partial<ContextBreakdown>): void {
    const breakdown: ContextBreakdown = {
        system: bd?.system ?? 0,
        memory: bd?.memory ?? 0,
        chunks: bd?.chunks ?? 0,
        query: bd?.query ?? 0,
    };
    const chip = byId("ctxChip");
    byId("ctxBarFill").style.width = Math.min(pct, 100) + "%";
    byId("ctxPct").textContent = "~" + Math.round(pct) + "%";
    chip.classList.remove("warn", "crit");
    if (pct >= 95) chip.classList.add("crit");
    else if (pct >= 80) chip.classList.add("warn");
    const fmt = (n: number) => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n));
    byId("ttSystem").textContent = fmt(breakdown.system) + " tok";
    byId("ttMemory").textContent = fmt(breakdown.memory) + " tok";
    byId("ttChunks").textContent = fmt(breakdown.chunks) + " tok";
    byId("ttQuery").textContent = fmt(breakdown.query) + " tok";
    const total = breakdown.system + breakdown.memory + breakdown.chunks + breakdown.query;
    byId("ttTotal").textContent = fmt(total) + " tok";
    byId("ctxCompactBtn").style.display = pct >= 95 ? "block" : "none";
}

export function initContextIndicator(): void {
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

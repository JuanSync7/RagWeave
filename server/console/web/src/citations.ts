// @summary
// Citation rendering + expand/collapse handlers for the user console.
// `buildCitationsHtml` is consumed by both the streaming and non-stream code
// paths plus the conversation-history replay in conversations.ts.
// @end-summary

import { byId, escHtml } from "./dom";
import type { ChunkResult } from "./user-types";

export function buildCitationsHtml(results: ChunkResult[]): string {
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

function toggleCitation(card: HTMLElement): void {
    card.classList.toggle("expanded");
}

function toggleChunk(e: Event, id: string): void {
    e.stopPropagation();
    const el = byId(id);
    el.classList.toggle("show-all");
    (e.target as HTMLElement).textContent = el.classList.contains("show-all") ? "Show less" : "Show more";
}

export function revealCitations(citationsEl: HTMLElement): void {
    citationsEl.style.display = "block";
    citationsEl.classList.remove("reveal");
    // Force reflow so the animation re-fires on subsequent reveals.
    void citationsEl.offsetWidth;
    citationsEl.classList.add("reveal");
}

export function initCitations(): void {
    (window as unknown as Record<string, unknown>)["toggleCitation"] = toggleCitation;
    (window as unknown as Record<string, unknown>)["toggleChunk"] = toggleChunk;
}

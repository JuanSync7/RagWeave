// @summary
// Markdown rendering pipeline for streamed assistant output.
// Configures marked with a custom code-block renderer (copy-button UI),
// normalizes inline-list markers, and sanitizes the final HTML with DOMPurify.
// Exports: parseMarkdown, normalizeMarkdown
// Deps: marked, dompurify
// @end-summary

import { marked } from "marked";
import DOMPurify from "dompurify";
import { escHtml } from "./dom";

// Custom code-block renderer: wraps <pre><code> in a copy-button UI.
// Clicks are handled via event delegation on #thread — no inline onclick needed,
// which also means DOMPurify does not need to allow event attributes.
marked.use({
    gfm: true,
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
export function normalizeMarkdown(raw: string): string {
    const segments = raw.split(/(```[\s\S]*?```)/);
    return segments.map((seg, i) => {
        if (i % 2 === 1) return seg;
        return seg.split("\n").map(splitInlineList).join("\n");
    }).join("");
}

/**
 * Render markdown to sanitized HTML.
 * marked.parse is synchronous when no async hooks are configured.
 */
export function parseMarkdown(raw: string): string {
    return DOMPurify.sanitize(marked.parse(normalizeMarkdown(raw)) as string);
}

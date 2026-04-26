/**
 * @summary
 * HTTP + slash-command client helpers for the admin/operator console.
 * Wraps fetch with auth headers, JSON parsing, and error normalization. Also
 * provides slash-command cache lookups and parsing.
 * Exports: byId, authHeaders, api, fetchConsoleCommands, executeConsoleCommand, parseSlash
 * Deps: admin-types, admin-state
 * @end-summary
 */
import { getCommandCache } from "./admin-state.js";
export function byId(id) {
    const el = document.getElementById(id);
    if (!el) {
        throw new Error(`Missing required element #${id}`);
    }
    return el;
}
export function authHeaders() {
    const headers = { "Content-Type": "application/json" };
    const apiKey = byId("apiKey").value.trim();
    const bearer = byId("bearerToken").value.trim();
    if (apiKey) {
        headers["x-api-key"] = apiKey;
    }
    if (bearer) {
        headers["Authorization"] = `Bearer ${bearer}`;
    }
    return headers;
}
export async function api(method, path, body) {
    const response = await fetch(path, {
        method,
        headers: authHeaders(),
        body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    let payload;
    try {
        payload = text ? JSON.parse(text) : {};
    }
    catch {
        payload = { raw: text };
    }
    if (!response.ok) {
        const err = payload.error;
        const rawDetail = payload.detail;
        const detailStr = typeof rawDetail === "string" ? rawDetail : undefined;
        const message = typeof err?.message === "string"
            ? err.message
            : detailStr ?? `HTTP ${response.status}`;
        throw new Error(message);
    }
    return payload;
}
export async function fetchConsoleCommands(mode) {
    const cache = getCommandCache();
    if (cache[mode]) {
        return cache[mode];
    }
    const payload = await api("GET", `/console/commands?mode=${mode}`);
    const data = payload.data || {};
    const commands = Array.isArray(data.commands) ? data.commands : [];
    cache[mode] = commands;
    return commands;
}
export async function executeConsoleCommand(mode, command, arg, state) {
    const payload = await api("POST", "/console/command", {
        mode,
        command,
        arg,
        state,
    });
    const data = payload.data || {};
    return data;
}
export function parseSlash(raw) {
    const text = raw.trim();
    const normalized = (text.startsWith("/") ? text.slice(1) : text).trim();
    const [name, ...rest] = normalized.split(/\s+/);
    return {
        name: (name || "").toLowerCase(),
        arg: rest.join(" ").trim(),
    };
}

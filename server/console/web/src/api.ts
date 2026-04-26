// @summary
// Auth + JSON API layer for the user console.
// Reads the saved settings from localStorage to construct authenticated fetch calls.
// Exports: getSettings, authHeaders, apiBase, api
// Deps: (none)
// @end-summary

export function getSettings(): Record<string, unknown> {
    const raw = localStorage.getItem("nc_settings");
    return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
}

export function authHeaders(): Record<string, string> {
    const s = getSettings();
    const token = (s.auth_token as string | undefined) || "";
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (token) {
        h["Authorization"] = `Bearer ${token}`;
        h["x-api-key"] = token;
    }
    return h;
}

export function apiBase(): string {
    const s = getSettings();
    const ep = ((s.api_endpoint as string | undefined) || "").trim();
    return ep ? ep.replace(/\/$/, "") : "";
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
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

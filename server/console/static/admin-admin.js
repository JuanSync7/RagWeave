/**
 * @summary
 * Admin tab handlers for the operator console: list/create API keys and quotas.
 * Exports: bindAdmin
 * Deps: admin-api, admin-render
 * @end-summary
 */
import { api, byId } from "./admin-api.js";
import { write } from "./admin-render.js";
export function bindAdmin() {
    byId("listKeysBtn").addEventListener("click", async () => {
        try {
            write("adminOut", await api("GET", "/console/admin/api-keys"));
        }
        catch (err) {
            write("adminOut", String(err));
        }
    });
    byId("listQuotasBtn").addEventListener("click", async () => {
        try {
            write("adminOut", await api("GET", "/console/admin/quotas"));
        }
        catch (err) {
            write("adminOut", String(err));
        }
    });
    byId("createKeyBtn").addEventListener("click", async () => {
        try {
            const out = await api("POST", "/console/admin/api-keys", {
                subject: byId("newKeySubject").value.trim(),
                tenant_id: byId("newKeyTenant").value.trim() || null,
                roles: ["query"],
                description: "Created from operator console",
            });
            write("adminOut", out);
        }
        catch (err) {
            write("adminOut", String(err));
        }
    });
}

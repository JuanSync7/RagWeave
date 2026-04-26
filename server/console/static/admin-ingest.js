/**
 * @summary
 * Ingestion tab handlers + slash command dispatcher for the admin/operator console.
 * Exports: ingestStatusSnapshot, bindIngest
 * Deps: admin-types, admin-api, admin-render
 * @end-summary
 */
import { api, byId, executeConsoleCommand, parseSlash } from "./admin-api.js";
import { commandSummary, write } from "./admin-render.js";
export function ingestStatusSnapshot() {
    return {
        mode: byId("ingestMode").value,
        target_path: byId("targetPath").value.trim() || null,
        update_mode: byId("updateMode").checked,
        build_kg: byId("buildKg").checked,
        verbose_stages: byId("verboseStages").checked,
        docling_enabled: byId("doclingEnabled").checked,
        docling_model: byId("doclingModel").value.trim() || null,
        vision_enabled: byId("visionEnabled").checked,
        vision_provider: byId("visionProvider").value,
        vision_model: byId("visionModel").value.trim() || null,
    };
}
export function bindIngest() {
    byId("runIngestBtn").addEventListener("click", async () => {
        try {
            const payload = {
                mode: byId("ingestMode").value,
                target_path: byId("targetPath").value.trim() || null,
                update_mode: byId("updateMode").checked,
                build_kg: byId("buildKg").checked,
                verbose_stages: byId("verboseStages").checked,
                docling_enabled: byId("doclingEnabled").checked,
                docling_model: byId("doclingModel").value.trim() || null,
                docling_artifacts_path: byId("doclingArtifactsPath").value.trim() || null,
                docling_strict: byId("doclingStrict").checked,
                docling_auto_download: byId("doclingAutoDownload").checked,
                vision_enabled: byId("visionEnabled").checked,
                vision_provider: byId("visionProvider").value,
                vision_model: byId("visionModel").value.trim() || null,
                vision_api_base_url: byId("visionApiBaseUrl").value.trim() || null,
                vision_max_figures: Number(byId("visionMaxFigures").value || 4),
                vision_timeout_seconds: Number(byId("visionTimeoutSeconds").value || 60),
                vision_auto_pull: byId("visionAutoPull").checked,
                vision_strict: byId("visionStrict").checked,
            };
            const out = await api("POST", "/console/ingest", payload);
            write("ingestOut", out);
        }
        catch (err) {
            write("ingestOut", String(err));
        }
    });
    byId("ingestSlashRunBtn").addEventListener("click", async () => {
        const input = byId("ingestSlashInput");
        const { name, arg } = parseSlash(input.value);
        if (!name) {
            return;
        }
        try {
            const result = await executeConsoleCommand("ingest", name, arg, ingestStatusSnapshot());
            const action = String(result.action || "noop");
            if (action === "run_ingest") {
                byId("runIngestBtn").click();
            }
            else if (action === "clear_view") {
                write("ingestOut", "");
            }
            else if (action === "render_status") {
                write("ingestOut", result.data?.state || ingestStatusSnapshot());
            }
            else if (action === "render_help") {
                const cmds = Array.isArray(result.data?.commands)
                    ? result.data?.commands
                    : [];
                write("ingestOut", commandSummary(cmds));
            }
            else {
                write("ingestOut", result.message || `No action mapped for /${name}`);
            }
        }
        catch (err) {
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

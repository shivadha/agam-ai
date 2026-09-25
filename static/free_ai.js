/* free_ai.js — Free AI admin tab (background agent providers, credit ledger,
   scout candidates, job queue). Loaded on the Automation page. */

async function freeApi(path, method, body) {
    const r = await fetch(path, {
        method: method || "GET",
        headers: {"Content-Type": "application/json"},
        body: body ? JSON.stringify(body) : undefined,
    });
    return r.json();
}

function freeEsc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

const FTABLE = "width: 100%; border-collapse: collapse; font-size: 0.82rem;";
const FTH = "text-align: left; padding: 8px 10px; color: #94a3b8; border-bottom: 1px solid rgba(255,255,255,0.1); font-weight: 600;";
const FTD = "padding: 8px 10px; color: #e2e8f0; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top;";
const FBTN = "background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); color: #fff; padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 11px; font-weight: 600; margin-right: 4px;";

function freeStatusPill(p) {
    let bg = "rgba(34,197,94,0.15)", fg = "#4ade80", label = "active";
    if (!p.enabled) { bg = "rgba(148,163,184,0.15)"; fg = "#94a3b8"; label = "disabled"; }
    else if (p.status === "exhausted") { bg = "rgba(239,68,68,0.15)"; fg = "#f87171"; label = "exhausted"; }
    return `<span style="background:${bg}; color:${fg}; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700;">${label}</span>`;
}

async function buildFreeAI() {
    const badge = document.getElementById("freeAgentBadge");
    try {
        const [pj, cj, jj] = await Promise.all([
            freeApi("/api/free/providers"),
            freeApi("/api/free/candidates"),
            freeApi("/api/free/jobs?limit=30"),
        ]);

        // Agent badge
        if (jj.agent_alive) {
            badge.textContent = "● agent running";
            badge.style.background = "rgba(34,197,94,0.15)";
            badge.style.color = "#4ade80";
        } else {
            badge.textContent = "○ agent not running — start start_agent.bat";
            badge.style.background = "rgba(239,68,68,0.12)";
            badge.style.color = "#f87171";
        }

        // Providers
        const providers = pj.providers || [];
        let ph = `<table style="${FTABLE}"><tr><th style="${FTH}">Provider</th><th style="${FTH}">Kinds</th><th style="${FTH}">Balance</th><th style="${FTH}">Used</th><th style="${FTH}">Status</th><th style="${FTH}">Actions</th></tr>`;
        for (const p of providers) {
            const bal = p.balance == null ? "<span style='color:#94a3b8'>—</span>" : `<b>${p.balance}</b>`;
            ph += `<tr>
                <td style="${FTD}"><b>${freeEsc(p.name)}</b><br><span style="color:#64748b; font-size:11px;">${freeEsc(p.id)} · ${freeEsc(p.url)}</span></td>
                <td style="${FTD}">${(p.kinds || []).join(", ")}</td>
                <td style="${FTD}">${bal}</td>
                <td style="${FTD}">${p.used_count}</td>
                <td style="${FTD}">${freeStatusPill(p)}</td>
                <td style="${FTD}; white-space: nowrap;">
                    <button style="${FBTN}" onclick="freeToggle('${p.id}', ${p.enabled ? 0 : 1})">${p.enabled ? "Disable" : "Enable"}</button>
                    <button style="${FBTN}" onclick="freeResetBalance('${p.id}')">↻ re-check</button>
                    <button style="${FBTN}; border-color: rgba(239,68,68,0.5); color: #f87171;" onclick="freeDelete('${p.id}')">Delete</button>
                </td></tr>`;
        }
        ph += "</table>";
        document.getElementById("freeProvidersTable").innerHTML = ph;

        // Candidates
        const cands = cj.candidates || [];
        let ch = cands.length ? `<table style="${FTABLE}"><tr><th style="${FTH}">Site</th><th style="${FTH}">Kinds</th><th style="${FTH}">Quota hint</th><th style="${FTH}">Found via</th><th style="${FTH}">Actions</th></tr>` : "<p style='color:#64748b; font-size:0.85rem;'>No pending candidates. Run the scout to discover new free AI sites.</p>";
        for (const c of cands) {
            ch += `<tr>
                <td style="${FTD}"><b>${freeEsc(c.name)}</b><br><a href="${freeEsc(c.url)}" target="_blank" style="color:#60a5fa; font-size:11px;">${freeEsc(c.url)}</a></td>
                <td style="${FTD}">${(c.kinds || []).join(", ")}</td>
                <td style="${FTD}">${freeEsc(c.quota_hint || "—")}</td>
                <td style="${FTD}">${freeEsc(c.source || "")}</td>
                <td style="${FTD}; white-space: nowrap;">
                    <button style="${FBTN}; border-color: rgba(34,197,94,0.5); color: #4ade80;" onclick="freeApprove(${c.id})">✓ Approve</button>
                    <button style="${FBTN}; border-color: rgba(239,68,68,0.5); color: #f87171;" onclick="freeReject(${c.id})">✕ Reject</button>
                </td></tr>`;
        }
        if (cands.length) ch += "</table>";
        document.getElementById("freeCandidatesTable").innerHTML = ch;

        // Jobs
        const jobs = jj.jobs || [];
        const stats = jj.stats || {};
        let jh = `<p style="color:#94a3b8; font-size:0.8rem; margin-bottom:8px;">queued: ${stats.queued || 0} · running: ${stats.running || 0} · done: ${stats.done || 0} · failed: ${stats.failed || 0}</p>`;
        jh += jobs.length ? `<table style="${FTABLE}"><tr><th style="${FTH}">Job</th><th style="${FTH}">Provider / kind</th><th style="${FTH}">Prompt</th><th style="${FTH}">Status</th><th style="${FTH}">Result</th></tr>` : "<p style='color:#64748b; font-size:0.85rem;'>No jobs yet.</p>";
        for (const j of jobs) {
            const res = j.result_path ? `<span style="color:#4ade80; font-size:11px;">${freeEsc(j.result_path.split(/[\\/]/).pop())}</span>`
                : j.result_text ? `<span style="color:#4ade80; font-size:11px;">${freeEsc(j.result_text.slice(0, 60))}…</span>`
                : j.error ? `<span style="color:#f87171; font-size:11px;">${freeEsc(j.error.slice(0, 80))}</span>` : "—";
            jh += `<tr>
                <td style="${FTD}; font-size:11px; color:#64748b;">${j.id}<br>${freeEsc(j.created_at || "")}</td>
                <td style="${FTD}">${freeEsc(j.provider_id)}<br><span style="color:#64748b;">${freeEsc(j.kind)}</span></td>
                <td style="${FTD}; max-width: 280px;">${freeEsc((j.prompt || "").slice(0, 120))}</td>
                <td style="${FTD}">${j.status}${j.balance_after != null ? ` <span style="color:#94a3b8;">(bal ${j.balance_after})</span>` : ""}</td>
                <td style="${FTD}">${res}</td></tr>`;
        }
        if (jobs.length) jh += "</table>";
        document.getElementById("freeJobsTable").innerHTML = jh;
    } catch (e) {
        badge.textContent = "error loading";
        console.error("[free-ai]", e);
    }
}

async function freeToggle(pid, enabled) {
    await freeApi(`/api/free/providers/${encodeURIComponent(pid)}`, "PUT", {enabled: !!enabled});
    buildFreeAI();
}

async function freeDelete(pid) {
    if (!confirm(`Delete provider "${pid}"? This removes it from the ledger.`)) return;
    await freeApi(`/api/free/providers/${encodeURIComponent(pid)}`, "DELETE");
    buildFreeAI();
}

async function freeResetBalance(pid) {
    // Queue a no-op balance probe: a tiny text job reads balance without spending much.
    await freeApi(`/api/free/providers/${encodeURIComponent(pid)}`, "PUT", {status: "active", balance: null});
    buildFreeAI();
}

async function freeApprove(cid) {
    const r = await freeApi(`/api/free/candidates/${cid}/approve`, "POST", {});
    if (r.status === "success") buildFreeAI();
    else alert("Approve failed: " + (r.message || "unknown"));
}

async function freeReject(cid) {
    await freeApi(`/api/free/candidates/${cid}/reject`, "POST", {});
    buildFreeAI();
}

document.addEventListener("DOMContentLoaded", () => {
    const rb = document.getElementById("freeRefreshBtn");
    if (rb) rb.addEventListener("click", buildFreeAI);
    const sb = document.getElementById("freeScoutBtn");
    if (sb) sb.addEventListener("click", async () => {
        sb.textContent = "🔍 scouting…";
        sb.disabled = true;
        try {
            const r = await freeApi("/api/free/scout/run", "POST", {});
            alert(r.status === "success"
                ? `Scout done: ${r.scanned} hits, ${r.added} new candidates.`
                : "Scout failed: " + (r.message || "unknown"));
        } finally {
            sb.textContent = "🔍 Run scout now";
            sb.disabled = false;
        }
        buildFreeAI();
    });
    const jb = document.getElementById("freeJobBtn");
    if (jb) jb.addEventListener("click", async () => {
        const kind = document.getElementById("freeJobKind").value;
        const prompt = document.getElementById("freeJobPrompt").value.trim();
        const msg = document.getElementById("freeJobMsg");
        if (!prompt) { msg.textContent = "Enter a prompt first."; return; }
        msg.textContent = "queueing…";
        const r = await freeApi("/api/free/jobs", "POST", {kind, prompt});
        msg.textContent = r.status === "success"
            ? `Queued as ${r.job_id} → ${r.provider}. Watch the table below.`
            : "Error: " + (r.message || "unknown");
        if (r.status === "success") setTimeout(buildFreeAI, 1500);
    });
});

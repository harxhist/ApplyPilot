import { useEffect, useState } from "react";
import { api } from "../api";

export default function Apply() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [workers, setWorkers] = useState(2);
  const [minScore, setMinScore] = useState(8);
  const [noHitl, setNoHitl] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = async () => {
    const [st, s] = await Promise.all([
      api<Record<string, unknown>>("/api/v1/apply/status"),
      api<Record<string, unknown>>("/api/v1/stats"),
    ]);
    setStatus(st);
    setStats(s);
  };

  useEffect(() => {
    load().catch((e) => setErr(String(e)));
    const t = setInterval(() => load().catch(() => {}), 5000);
    return () => clearInterval(t);
  }, []);

  const start = async () => {
    setMsg("");
    setErr("");
    try {
      const res = await api<Record<string, unknown>>("/api/v1/apply/start", {
        method: "POST",
        body: JSON.stringify({
          workers,
          min_score: minScore,
          no_hitl: noHitl,
          dry_run: dryRun,
        }),
      });
      setMsg(JSON.stringify(res, null, 2));
      await load();
    } catch (e) {
      setErr(String(e));
    }
  };

  const mode = String(status?.mode || "off");
  const disabled = mode === "off" || mode === "disabled";

  return (
    <div>
      <h1>Apply console</h1>
      {err && <p className="error">{err}</p>}
      {disabled && (
        <div className="card">
          <p>
            <strong>APPLY_MODE=off</strong> — browser apply is host-side only in Docker.
          </p>
          <p className="mono">{String(status?.host_command_hint || "applypilot apply")}</p>
          <p className="muted">
            Ready: {String(stats?.ready_to_apply ?? "—")} · Needs human:{" "}
            {String(stats?.needs_human ?? "—")} · Applied: {String(stats?.applied ?? "—")}
          </p>
        </div>
      )}
      <div className="toolbar">
        <label>
          workers{" "}
          <input
            type="number"
            value={workers}
            onChange={(e) => setWorkers(Number(e.target.value))}
            style={{ width: 70 }}
          />
        </label>
        <label>
          min_score{" "}
          <input
            type="number"
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            style={{ width: 70 }}
          />
        </label>
        <label>
          <input type="checkbox" checked={noHitl} onChange={(e) => setNoHitl(e.target.checked)} />{" "}
          no-hitl
        </label>
        <label>
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />{" "}
          dry-run
        </label>
        <button type="button" disabled={disabled} onClick={start}>
          Start apply
        </button>
        <button
          type="button"
          className="secondary"
          disabled={disabled}
          onClick={() => api("/api/v1/apply/stop", { method: "POST" }).then(load)}
        >
          Stop
        </button>
      </div>
      <h2>Status</h2>
      <pre className="mono">{JSON.stringify(status, null, 2)}</pre>
      {msg && (
        <>
          <h2>Last response</h2>
          <pre className="mono">{msg}</pre>
        </>
      )}
    </div>
  );
}

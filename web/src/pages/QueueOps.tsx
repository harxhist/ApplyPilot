import { useState } from "react";
import { api, confirmAction } from "../api";

export default function QueueOps() {
  const [out, setOut] = useState("");
  const [err, setErr] = useState("");

  const run = async (path: string, body: Record<string, unknown>, label: string) => {
    if (!confirmAction(`Run ${label}?`)) return;
    setErr("");
    setOut("Running…");
    try {
      const res = await api(path, { method: "POST", body: JSON.stringify(body) });
      setOut(JSON.stringify(res, null, 2));
    } catch (e) {
      setErr(String(e));
      setOut("");
    }
  };

  return (
    <div>
      <h1>Queue ops</h1>
      <p className="muted">Harsh seed / refilter scripts (same as CLI scripts).</p>
      <div className="toolbar">
        <button
          type="button"
          onClick={() => run("/api/v1/ops/seed", { pool: false, dry_run: true }, "seed dry-run")}
        >
          Seed dry-run
        </button>
        <button
          type="button"
          onClick={() => run("/api/v1/ops/seed", { pool: false, dry_run: false }, "seed live")}
        >
          Seed live
        </button>
        <button
          type="button"
          onClick={() =>
            run("/api/v1/ops/refilter", { dry_run: true, rescore: false }, "refilter dry-run")
          }
        >
          Refilter dry-run
        </button>
        <button
          type="button"
          className="danger"
          onClick={() =>
            run("/api/v1/ops/refilter", { dry_run: false, rescore: true }, "refilter + rescore")
          }
        >
          Refilter + rescore
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => run("/api/v1/ops/export-dashboard", {}, "export dashboard")}
        >
          Export HTML dashboard
        </button>
      </div>
      {err && <p className="error">{err}</p>}
      <pre className="logbox">{out || "—"}</pre>
    </div>
  );
}

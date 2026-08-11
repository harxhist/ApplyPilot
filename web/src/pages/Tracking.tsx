import { useEffect, useState } from "react";
import { api } from "../api";

export default function Tracking() {
  const [data, setData] = useState<{ emails: unknown[]; jobs: unknown[] } | null>(null);
  const [err, setErr] = useState("");
  const [out, setOut] = useState("");

  const load = () =>
    api<{ emails: unknown[]; jobs: unknown[] }>("/api/v1/tracking")
      .then(setData)
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  const run = async () => {
    setOut("");
    try {
      const res = await api("/api/v1/tracking/run", {
        method: "POST",
        body: JSON.stringify({ days: 14, dry_run: false }),
      });
      setOut(JSON.stringify(res, null, 2));
      await load();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <h1>Tracking</h1>
      <div className="toolbar">
        <button type="button" onClick={run}>
          Run Gmail tracking
        </button>
        <button type="button" className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      {err && <p className="error">{err}</p>}
      {out && <pre className="mono">{out}</pre>}
      <h2>Tracked jobs</h2>
      <pre className="mono">{JSON.stringify(data?.jobs || [], null, 2)}</pre>
      <h2>Emails</h2>
      <pre className="mono">{JSON.stringify(data?.emails || [], null, 2)}</pre>
    </div>
  );
}

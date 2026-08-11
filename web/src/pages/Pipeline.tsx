import { useEffect, useRef, useState } from "react";
import { api, getToken } from "../api";

const STAGES = ["discover", "enrich", "score", "tailor", "cover", "pdf"];

export default function Pipeline() {
  const [stages, setStages] = useState<string[]>(["score", "tailor", "cover"]);
  const [minScore, setMinScore] = useState(8);
  const [limit, setLimit] = useState(20);
  const [workers, setWorkers] = useState(1);
  const [dryRun, setDryRun] = useState(false);
  const [stream, setStream] = useState(false);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [runs, setRuns] = useState<Record<string, unknown>[]>([]);
  const [log, setLog] = useState("");
  const [err, setErr] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const refresh = async () => {
    const data = await api<{ items: Record<string, unknown>[] }>("/api/v1/pipeline/runs");
    setRuns(data.items);
  };

  useEffect(() => {
    api<{ sources: Record<string, string> }>("/api/v1/sources")
      .then((d) => setSources(d.sources))
      .catch((e) => setErr(String(e)));
    refresh().catch((e) => setErr(String(e)));
  }, []);

  const toggleStage = (s: string) => {
    setStages((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  };

  const start = async () => {
    setErr("");
    setLog("");
    try {
      const body = {
        stages: stages.length ? stages : ["all"],
        min_score: minScore,
        limit,
        workers,
        dry_run: dryRun,
        stream,
        sources: selectedSources.length ? selectedSources : null,
      };
      const run = await api<{ id: string }>("/api/v1/pipeline/runs", {
        method: "POST",
        body: JSON.stringify(body),
      });
      await refresh();
      esRef.current?.close();
      const token = getToken();
      // EventSource can't set Authorization; use fetch stream fallback via query not available —
      // poll run + log via status; for SSE use fetch ReadableStream
      const res = await fetch(`/api/v1/pipeline/runs/${run.id}/events`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.body) return;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part
            .split("\n")
            .filter((l) => l.startsWith("data: "))
            .map((l) => l.slice(6))
            .join("\n");
          if (line) setLog((prev) => prev + line + "\n");
        }
      }
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <h1>Pipeline</h1>
      {err && <p className="error">{err}</p>}
      <div className="card">
        <div className="toolbar">
          {STAGES.map((s) => (
            <label key={s}>
              <input
                type="checkbox"
                checked={stages.includes(s)}
                onChange={() => toggleStage(s)}
              />{" "}
              {s}
            </label>
          ))}
        </div>
        <div className="toolbar">
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
            limit{" "}
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{ width: 70 }}
            />
          </label>
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
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />{" "}
            dry-run
          </label>
          <label>
            <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} />{" "}
            stream
          </label>
          <button type="button" onClick={start}>
            Start run
          </button>
        </div>
        <details>
          <summary className="muted">Discovery sources (optional)</summary>
          <div className="toolbar">
            {Object.keys(sources).map((s) => (
              <label key={s}>
                <input
                  type="checkbox"
                  checked={selectedSources.includes(s)}
                  onChange={() =>
                    setSelectedSources((prev) =>
                      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
                    )
                  }
                />{" "}
                {s}
              </label>
            ))}
          </div>
        </details>
      </div>
      <h2>Live log</h2>
      <div className="logbox">{log || "—"}</div>
      <h2>History</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Status</th>
            <th>Started</th>
            <th>Finished</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={String(r.id)}>
              <td>{String(r.id)}</td>
              <td>
                <span className="badge">{String(r.status)}</span>
              </td>
              <td className="muted">{String(r.started_at || "")}</td>
              <td className="muted">{String(r.finished_at || "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

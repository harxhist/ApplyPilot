import { useEffect, useState } from "react";
import { api, confirmAction } from "../api";

type Job = {
  id: string;
  url: string;
  title?: string;
  company?: string;
  location?: string;
  site?: string;
  state?: string;
  fit_score?: number;
  apply_status?: string;
  apply_error?: string;
  application_url?: string;
  score_reasoning?: string;
  full_description?: string;
  needs_human_reason?: string;
  transitions?: { from_state?: string; to_state?: string; at?: string; reason?: string }[];
};

export default function Jobs() {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [minScore, setMinScore] = useState("");
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Job | null>(null);
  const [err, setErr] = useState("");
  const limit = 40;

  const load = async (off = offset) => {
    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(off),
        order_by: "fit_score",
        order_dir: "desc",
      });
      if (q) params.set("q", q);
      if (state) params.set("state", state);
      if (minScore) params.set("min_score", minScore);
      const data = await api<{ items: Job[]; total: number }>(`/api/v1/jobs?${params}`);
      setItems(data.items);
      setTotal(data.total);
      setErr("");
    } catch (e) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    load(0);
    setOffset(0);
    const t = setInterval(() => load(offset), 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, state, minScore]);

  const open = async (id: string) => {
    try {
      const job = await api<Job>(`/api/v1/jobs/${id}`);
      setSelected(job);
    } catch (e) {
      setErr(String(e));
    }
  };

  const mark = async (status: "applied" | "failed") => {
    if (!selected) return;
    if (!confirmAction(`Mark as ${status}?`)) return;
    await api("/api/v1/jobs/mark", {
      method: "POST",
      body: JSON.stringify({ url: selected.url, status }),
    });
    await open(selected.id);
    await load();
  };

  return (
    <div>
      <h1>Jobs</h1>
      <div className="toolbar">
        <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <input placeholder="State" value={state} onChange={(e) => setState(e.target.value)} />
        <input
          placeholder="Min score"
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
          style={{ width: 90 }}
        />
        <button type="button" onClick={() => load(0)}>
          Refresh
        </button>
        <span className="muted">
          {total} total · offset {offset}
        </span>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="split">
        <table>
          <thead>
            <tr>
              <th>Score</th>
              <th>Company</th>
              <th>Title</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {items.map((j) => (
              <tr key={j.id} onClick={() => open(j.id)} style={{ cursor: "pointer" }}>
                <td>{j.fit_score ?? "—"}</td>
                <td>{j.company}</td>
                <td>{j.title}</td>
                <td>
                  <span className="badge">{j.state || "—"}</span>
                </td>
              </tr>
            ))}
            {!items.length && (
              <tr>
                <td colSpan={4} className="muted">
                  No jobs
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="drawer">
          {!selected && <p className="muted">Select a job</p>}
          {selected && (
            <>
              <h2 style={{ marginTop: 0 }}>
                {selected.company} — {selected.title}
              </h2>
              <p>
                <span className="badge">{selected.state}</span>{" "}
                <span className="badge">score {selected.fit_score ?? "—"}</span>
              </p>
              <p className="muted">{selected.location}</p>
              <div className="toolbar">
                <a href={selected.application_url || selected.url} target="_blank" rel="noreferrer">
                  Open application
                </a>
                <button type="button" onClick={() => mark("applied")}>
                  Mark applied
                </button>
                <button type="button" className="danger" onClick={() => mark("failed")}>
                  Mark failed
                </button>
              </div>
              {selected.apply_error && <p className="error">{selected.apply_error}</p>}
              {selected.needs_human_reason && (
                <p className="warn">HITL: {selected.needs_human_reason}</p>
              )}
              <h2>Score reasoning</h2>
              <div className="mono">{selected.score_reasoning || "—"}</div>
              <h2>Description</h2>
              <div className="mono">
                {(selected.full_description || "").slice(0, 4000) || "—"}
              </div>
              <h2>Transitions</h2>
              <ul>
                {(selected.transitions || []).slice(0, 20).map((t, i) => (
                  <li key={i} className="muted">
                    {t.at}: {t.from_state} → {t.to_state} {t.reason ? `(${t.reason})` : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      <div className="toolbar" style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          disabled={offset <= 0}
          onClick={() => {
            const n = Math.max(0, offset - limit);
            setOffset(n);
            load(n);
          }}
        >
          Prev
        </button>
        <button
          type="button"
          disabled={offset + limit >= total}
          onClick={() => {
            const n = offset + limit;
            setOffset(n);
            load(n);
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

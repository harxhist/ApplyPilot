import { useEffect, useState } from "react";
import { api, confirmAction } from "../api";

type HitlJob = {
  id: string;
  url: string;
  title?: string;
  company?: string;
  needs_human_reason?: string;
  needs_human_url?: string;
  needs_human_instructions?: string;
  application_url?: string;
};

export default function Hitl() {
  const [items, setItems] = useState<HitlJob[]>([]);
  const [err, setErr] = useState("");

  const load = () =>
    api<{ items: HitlJob[] }>("/api/v1/hitl")
      .then((d) => setItems(d.items))
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  const resolve = async (id: string, action: "done" | "skip") => {
    if (!confirmAction(`${action} this HITL job?`)) return;
    await api(`/api/v1/hitl/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await load();
  };

  return (
    <div>
      <h1>Needs human</h1>
      {err && <p className="error">{err}</p>}
      {!items.length && <p className="muted">Queue empty</p>}
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Reason</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((j) => (
            <tr key={j.id}>
              <td>{j.company}</td>
              <td>{j.title}</td>
              <td>{j.needs_human_reason}</td>
              <td>
                <div className="toolbar">
                  <a href={j.needs_human_url || j.application_url || j.url} target="_blank" rel="noreferrer">
                    Open
                  </a>
                  <button type="button" onClick={() => resolve(j.id, "done")}>
                    Done / requeue
                  </button>
                  <button type="button" className="danger" onClick={() => resolve(j.id, "skip")}>
                    Skip
                  </button>
                </div>
                {j.needs_human_instructions && (
                  <div className="muted mono">{j.needs_human_instructions}</div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

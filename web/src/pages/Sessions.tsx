import { useEffect, useState } from "react";
import { api, confirmAction } from "../api";

type Sess = { slug: string; has_cookies?: boolean; age_hours?: number | null };

export default function Sessions() {
  const [items, setItems] = useState<Sess[]>([]);
  const [err, setErr] = useState("");

  const load = () =>
    api<{ items: Sess[] }>("/api/v1/sessions")
      .then((d) => setItems(d.items))
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  const clear = async (slug: string) => {
    if (!confirmAction(`Clear session ${slug}?`)) return;
    await api(`/api/v1/sessions/${encodeURIComponent(slug)}`, { method: "DELETE" });
    await load();
  };

  return (
    <div>
      <h1>ATS sessions</h1>
      {err && <p className="error">{err}</p>}
      {!items.length && <p className="muted">No saved sessions</p>}
      <table>
        <thead>
          <tr>
            <th>Slug</th>
            <th>Cookies</th>
            <th>Age (h)</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.slug}>
              <td>{s.slug}</td>
              <td>{s.has_cookies ? "yes" : "no"}</td>
              <td>{s.age_hours ?? "—"}</td>
              <td>
                <button type="button" className="danger" onClick={() => clear(s.slug)}>
                  Clear
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

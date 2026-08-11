import { useEffect, useState } from "react";
import { api, confirmAction } from "../api";

type Qa = {
  id: number;
  question_text: string;
  answer_text: string;
  answer_source?: string;
  outcome?: string;
};

export default function Qa() {
  const [items, setItems] = useState<Qa[]>([]);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  const [err, setErr] = useState("");

  const load = () =>
    api<{ items: Qa[] }>("/api/v1/qa")
      .then((d) => setItems(d.items))
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    await api("/api/v1/qa", {
      method: "POST",
      body: JSON.stringify({ question_text: q, answer_text: a }),
    });
    setQ("");
    setA("");
    await load();
  };

  const del = async (id: number) => {
    if (!confirmAction("Delete this Q&A?")) return;
    await api(`/api/v1/qa/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div>
      <h1>Screening Q&A</h1>
      {err && <p className="error">{err}</p>}
      <div className="card">
        <input
          placeholder="Question"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: "100%", marginBottom: 8 }}
        />
        <input
          placeholder="Answer"
          value={a}
          onChange={(e) => setA(e.target.value)}
          style={{ width: "100%", marginBottom: 8 }}
        />
        <button type="button" onClick={create} disabled={!q || !a}>
          Add
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Question</th>
            <th>Answer</th>
            <th>Source</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.id}>
              <td>{row.question_text}</td>
              <td>{row.answer_text}</td>
              <td>{row.answer_source}</td>
              <td>
                <button type="button" className="danger" onClick={() => del(row.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

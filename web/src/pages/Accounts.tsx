import { useEffect, useState } from "react";
import { api, confirmAction } from "../api";

type Acct = {
  id?: number;
  domain: string;
  email: string;
  password_set?: boolean;
  notes?: string;
};

export default function Accounts() {
  const [items, setItems] = useState<Acct[]>([]);
  const [domain, setDomain] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");

  const load = () =>
    api<{ items: Acct[] }>("/api/v1/accounts")
      .then((d) => setItems(d.items))
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    await api("/api/v1/accounts", {
      method: "PUT",
      body: JSON.stringify({ domain, email, password: password || null }),
    });
    setPassword("");
    await load();
  };

  const del = async (d: string) => {
    if (!confirmAction(`Delete credentials for ${d}?`)) return;
    await api(`/api/v1/accounts/${encodeURIComponent(d)}`, { method: "DELETE" });
    await load();
  };

  return (
    <div>
      <h1>Credentials</h1>
      {err && <p className="error">{err}</p>}
      <div className="toolbar">
        <input placeholder="domain" value={domain} onChange={(e) => setDomain(e.target.value)} />
        <input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="button" onClick={save} disabled={!domain || !email}>
          Save
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Domain</th>
            <th>Email</th>
            <th>Password</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.domain + a.email}>
              <td>{a.domain}</td>
              <td>{a.email}</td>
              <td>{a.password_set ? "********" : "—"}</td>
              <td>
                <button type="button" className="danger" onClick={() => del(a.domain)}>
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

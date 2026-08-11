import { useEffect, useState } from "react";
import { api } from "../api";

export default function Settings() {
  const [profile, setProfile] = useState("");
  const [searches, setSearches] = useState("");
  const [limits, setLimits] = useState("");
  const [integrations, setIntegrations] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([
      api<{ raw: string }>("/api/v1/config/profile"),
      api<{ raw: string }>("/api/v1/config/searches"),
      api<{ raw: string }>("/api/v1/config/company-limits"),
      api<Record<string, unknown>>("/api/v1/integrations"),
    ])
      .then(([p, s, l, i]) => {
        setProfile(p.raw || "");
        setSearches(s.raw || "");
        setLimits(l.raw || "");
        setIntegrations(i);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  const save = async (kind: "profile" | "searches" | "company-limits", content: string) => {
    setMsg("");
    setErr("");
    try {
      await api(`/api/v1/config/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      });
      setMsg(`Saved ${kind}`);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <h1>Settings</h1>
      {err && <p className="error">{err}</p>}
      {msg && <p className="ok">{msg}</p>}
      <h2>Integrations (presence only)</h2>
      <pre className="mono">{JSON.stringify(integrations, null, 2)}</pre>
      <h2>profile.json</h2>
      <textarea value={profile} onChange={(e) => setProfile(e.target.value)} />
      <button type="button" onClick={() => save("profile", profile)}>
        Save profile
      </button>
      <h2>searches.yaml</h2>
      <textarea value={searches} onChange={(e) => setSearches(e.target.value)} />
      <button type="button" onClick={() => save("searches", searches)}>
        Save searches
      </button>
      <h2>company_limits.yaml</h2>
      <textarea value={limits} onChange={(e) => setLimits(e.target.value)} />
      <button type="button" onClick={() => save("company-limits", limits)}>
        Save limits
      </button>
    </div>
  );
}

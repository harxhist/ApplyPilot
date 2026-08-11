import { useEffect, useState } from "react";
import { api } from "../api";

type Stats = Record<string, unknown>;

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [s, h] = await Promise.all([
          api<Stats>("/api/v1/stats"),
          api<Record<string, unknown>>("/api/v1/health"),
        ]);
        if (!alive) return;
        setStats(s);
        setHealth(h);
        setErr("");
      } catch (e) {
        if (alive) setErr(String(e));
      }
    };
    load();
    const t = setInterval(load, 8000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (err) return <p className="error">{err}</p>;
  if (!stats) return <p className="muted">Loading…</p>;

  const cards: [string, unknown][] = [
    ["Total", stats.total],
    ["Scored", stats.scored],
    ["Tailored", stats.tailored],
    ["Cover letters", stats.with_cover_letter],
    ["Ready", stats.ready_to_apply],
    ["Applied", stats.applied],
    ["Needs human", stats.needs_human],
    ["Apply errors", stats.apply_errors],
  ];

  const dist = (stats.score_distribution as [number, number][]) || [];
  const byState = (stats.by_state as [string, number][]) || [];
  const funnel = (stats.score_funnel as Record<string, number>[]) || [];
  const blocked = stats.blocked_by_cap as { count?: number; companies?: string[] } | undefined;

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="muted">
        Tier {(health?.tier as number) ?? "?"} · apply mode {(health?.apply_mode as string) || "?"} ·{" "}
        {(health?.app_dir as string) || ""}
      </p>
      <div className="grid">
        {cards.map(([label, value]) => (
          <div className="card" key={label}>
            <div className="label">{label}</div>
            <div className="value">{String(value ?? 0)}</div>
          </div>
        ))}
      </div>

      <h2>Score distribution</h2>
      <table>
        <thead>
          <tr>
            <th>Score</th>
            <th>Count</th>
          </tr>
        </thead>
        <tbody>
          {dist.map(([score, count]) => (
            <tr key={score}>
              <td>{score}</td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>State distribution</h2>
      <table>
        <thead>
          <tr>
            <th>State</th>
            <th>Count</th>
          </tr>
        </thead>
        <tbody>
          {byState.map(([st, count]) => (
            <tr key={st}>
              <td>
                <span className="badge">{st}</span>
              </td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Funnel by score</h2>
      <table>
        <thead>
          <tr>
            <th>Score</th>
            <th>Cover ready</th>
            <th>Tailored</th>
            <th>Needs tailor</th>
            <th>Applied</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {funnel.map((row) => (
            <tr key={row.score}>
              <td>{row.score}</td>
              <td>{row.cover_ready}</td>
              <td>{row.tailored}</td>
              <td>{row.needs_tailor}</td>
              <td>{row.applied}</td>
              <td>{row.errors}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {blocked && blocked.count ? (
        <>
          <h2>Blocked by company cap</h2>
          <p>
            {blocked.count} companies — {(blocked.companies || []).join(", ") || "—"}
          </p>
          <p className="muted">Stale ready skipped: {String(stats.skipped_stale ?? 0)}</p>
        </>
      ) : null}
    </div>
  );
}

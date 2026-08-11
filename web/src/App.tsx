import { NavLink, Route, Routes } from "react-router-dom";
import { useState } from "react";
import { getToken, setToken } from "./api";
import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import Pipeline from "./pages/Pipeline";
import Apply from "./pages/Apply";
import Hitl from "./pages/Hitl";
import Tracking from "./pages/Tracking";
import Qa from "./pages/Qa";
import Accounts from "./pages/Accounts";
import Sessions from "./pages/Sessions";
import Settings from "./pages/Settings";
import QueueOps from "./pages/QueueOps";

const links = [
  ["/", "Dashboard"],
  ["/jobs", "Jobs"],
  ["/pipeline", "Pipeline"],
  ["/apply", "Apply"],
  ["/hitl", "Needs human"],
  ["/tracking", "Tracking"],
  ["/qa", "Q&A"],
  ["/accounts", "Credentials"],
  ["/sessions", "Sessions"],
  ["/settings", "Settings"],
  ["/ops", "Queue ops"],
] as const;

export default function App() {
  const [token, setTok] = useState(getToken());

  return (
    <div className="layout">
      <nav className="nav">
        <div className="brand">ApplyPilot</div>
        {links.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            {label}
          </NavLink>
        ))}
        <div className="token-bar">
          <input
            type="password"
            placeholder="API token"
            value={token}
            onChange={(e) => setTok(e.target.value)}
            onBlur={() => setToken(token)}
            title="APPLYPILOT_API_TOKEN"
          />
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/apply" element={<Apply />} />
          <Route path="/hitl" element={<Hitl />} />
          <Route path="/tracking" element={<Tracking />} />
          <Route path="/qa" element={<Qa />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/ops" element={<QueueOps />} />
        </Routes>
      </main>
    </div>
  );
}

import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Processes from "./pages/Processes.jsx";
import Scheduler from "./pages/Scheduler.jsx";
import AIAssistant from "./pages/AIAssistant.jsx";
import ErrorMonitor from "./pages/ErrorMonitor.jsx";

const NAV_ITEMS = [
  { to: "/", label: "DASHBOARD", end: true },
  { to: "/processes", label: "PROCESSES" },
  { to: "/scheduler", label: "SCHEDULER" },
  { to: "/assistant", label: "AI ASSISTANT" },
  { to: "/errors", label: "ERROR MONITOR" },
];

function App() {
  return (
    <div className="min-h-screen flex flex-col bg-term-bg text-term-text">
      <header className="border-b border-term-border bg-term-panel crt-flicker">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-baseline gap-3">
            <span className="text-term-green font-bold text-lg tracking-widest">PROCURA</span>
            <span className="text-term-dim text-xs">v1.0 :: os process scheduler simulator</span>
          </div>
          <nav className="flex gap-1 text-xs">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 border rounded transition-colors ${
                    isActive
                      ? "border-term-green text-term-green bg-term-green/10"
                      : "border-term-border text-term-dim hover:text-term-text hover:border-term-dim"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/processes" element={<Processes />} />
          <Route path="/scheduler" element={<Scheduler />} />
          <Route path="/assistant" element={<AIAssistant />} />
          <Route path="/errors" element={<ErrorMonitor />} />
        </Routes>
      </main>
      <footer className="border-t border-term-border text-center text-[10px] text-term-dim py-2">
        procura :: local-first, single-user, no auth :: task management reimagined as an OS scheduler
      </footer>
    </div>
  );
}

export default App;

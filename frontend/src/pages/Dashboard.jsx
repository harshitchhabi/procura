import { useEffect, useState } from "react";
import api from "../api.js";

const STATE_STYLES = {
  NEW: "text-term-dim",
  READY: "text-sky-400",
  RUNNING: "text-term-green",
  BLOCKED: "text-term-amber",
  COMPLETED: "text-term-dim",
  TERMINATED: "text-term-red",
};

function ResourceBar({ name, stats }) {
  const pct = stats?.utilization_pct ?? 0;
  const barColor = pct < 60 ? "bg-term-green" : pct < 85 ? "bg-term-amber" : "bg-term-red";
  return (
    <div className="mb-2">
      <div className="flex justify-between text-xs mb-1">
        <span className="uppercase text-term-dim">{name}</span>
        <span>
          {stats?.allocated ?? 0}/{stats?.capacity ?? 0} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="w-full h-2.5 bg-term-panel border border-term-border rounded overflow-hidden">
        <div className={`h-full ${barColor} transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [processes, setProcesses] = useState([]);
  const [resources, setResources] = useState(null);
  const [errors, setErrors] = useState([]);
  const [connError, setConnError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [procs, res, errs] = await Promise.all([
          api.getProcesses(),
          api.getResources(),
          api.getErrors(),
        ]);
        if (!cancelled) {
          setProcesses(procs);
          setResources(res);
          setErrors(errs);
          setConnError(null);
        }
      } catch (err) {
        if (!cancelled) setConnError(err.message);
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {connError && (
        <div className="lg:col-span-3 border border-term-red text-term-red text-xs p-2 rounded">
          Cannot reach backend at http://localhost:8000 ({connError}). Is `uvicorn main:app --reload` running?
        </div>
      )}

      <section className="lg:col-span-2 border border-term-border bg-term-panel rounded">
        <div className="px-3 py-2 border-b border-term-border text-term-green text-xs font-bold tracking-wider">
          PROCESS TABLE ({processes.length})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-term-dim text-left border-b border-term-border">
                <th className="px-3 py-2">PID</th>
                <th className="px-3 py-2">NAME</th>
                <th className="px-3 py-2">STATE</th>
                <th className="px-3 py-2">PRIORITY</th>
                <th className="px-3 py-2">BURST</th>
                <th className="px-3 py-2">MEM</th>
                <th className="px-3 py-2">CPU%</th>
                <th className="px-3 py-2">ERR</th>
              </tr>
            </thead>
            <tbody>
              {processes.map((p) => (
                <tr key={p.pid} className="border-b border-term-border/50 hover:bg-term-border/20">
                  <td className="px-3 py-1.5">{p.pid}</td>
                  <td className="px-3 py-1.5">{p.name}</td>
                  <td className={`px-3 py-1.5 font-bold ${STATE_STYLES[p.state] || ""}`}>{p.state}</td>
                  <td className="px-3 py-1.5">{p.priority}</td>
                  <td className="px-3 py-1.5">{p.burst_time}m</td>
                  <td className="px-3 py-1.5">{p.memory_requirement}MB</td>
                  <td className="px-3 py-1.5">{p.cpu_requirement}%</td>
                  <td className="px-3 py-1.5">{p.error_count}</td>
                </tr>
              ))}
              {processes.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-term-dim">
                    No processes. Run `python seed_data.py` or create one on the Processes page.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="flex flex-col gap-4">
        <section className="border border-term-border bg-term-panel rounded p-3">
          <div className="text-term-green text-xs font-bold tracking-wider mb-3">RESOURCE UTILIZATION</div>
          {resources
            ? Object.entries(resources.utilization).map(([name, stats]) => (
                <ResourceBar key={name} name={name} stats={stats} />
              ))
            : <div className="text-term-dim text-xs">Loading...</div>}
        </section>

        <section className="border border-term-border bg-term-panel rounded p-3 flex-1">
          <div className="text-term-amber text-xs font-bold tracking-wider mb-3">AI SYSTEM ACTIVITY FEED</div>
          <div className="space-y-2 max-h-64 overflow-y-auto text-xs">
            {errors.slice(0, 8).map((e) => (
              <div key={e.error_id} className="border-l-2 border-term-amber pl-2">
                <div className="text-term-dim">{(e.detected_at || "").slice(0, 19)}</div>
                <div>
                  <span className="text-term-red font-bold">{e.error_type}</span>{" "}
                  <span className="text-sky-400">pid={e.pid}</span>
                  {e.action_type && <span className="text-term-green"> -&gt; {e.action_type}</span>}
                </div>
              </div>
            ))}
            {errors.length === 0 && <div className="text-term-dim">No errors detected yet.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

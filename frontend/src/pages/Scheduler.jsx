import { useEffect, useState } from "react";
import api from "../api.js";

const ALGORITHMS = [
  { value: "fcfs", label: "FCFS" },
  { value: "sjf", label: "SJF" },
  { value: "priority", label: "Priority" },
  { value: "round_robin", label: "Round Robin" },
  { value: "eevdf", label: "EEVDF" },
  { value: "mlfq", label: "MLFQ" },
];

const PALETTE = ["#39ff88", "#ffb84d", "#5ec8ff", "#ff5c5c", "#c27bff", "#ffe066", "#7bffe0", "#ff9de0"];

function colorForPid(pid) {
  return PALETTE[pid % PALETTE.length];
}

export default function Scheduler() {
  const [algorithm, setAlgorithm] = useState("fcfs");
  const [quantum, setQuantum] = useState(4);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const runSchedule = async () => {
    setLoading(true);
    setError(null);
    try {
      const usesQuantum = algorithm === "round_robin" || algorithm === "eevdf" || algorithm === "mlfq";
      const data = await api.getSchedule(algorithm, usesQuantum ? quantum : undefined);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runSchedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const slices = result?.gantt || [];
  const makespan = Math.max(1, ...slices.map((s) => s.end));
  const lanes = [];
  for (const s of slices) {
    let lane = lanes.find((l) => l.pid === s.pid);
    if (!lane) {
      lane = { pid: s.pid, name: s.name, slices: [] };
      lanes.push(lane);
    }
    lane.slices.push(s);
  }
  const ticks = Array.from({ length: 6 }, (_, i) => Math.round((makespan * i) / 5));

  return (
    <div className="space-y-4">
      <section className="border border-term-border bg-term-panel rounded p-4 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-term-dim text-xs mb-1">Algorithm</label>
          <select
            className="bg-term-bg border border-term-border rounded px-3 py-1.5 text-sm"
            value={algorithm}
            onChange={(e) => setAlgorithm(e.target.value)}
          >
            {ALGORITHMS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
        {(algorithm === "round_robin" || algorithm === "eevdf" || algorithm === "mlfq") && (
          <div>
            <label className="block text-term-dim text-xs mb-1">Quantum</label>
            <input
              type="number"
              min="1"
              className="bg-term-bg border border-term-border rounded px-3 py-1.5 text-sm w-24"
              value={quantum}
              onChange={(e) => setQuantum(Number(e.target.value))}
            />
          </div>
        )}
        <button
          onClick={runSchedule}
          disabled={loading}
          className="border border-term-green text-term-green rounded px-4 py-1.5 text-sm hover:bg-term-green/10 disabled:opacity-50"
        >
          {loading ? "RUNNING..." : "RUN SCHEDULE"}
        </button>
        {error && <span className="text-term-red text-xs">{error}</span>}
      </section>

      {result && (
        <>
          <section className="border border-term-border bg-term-panel rounded p-4">
            <div className="flex items-baseline justify-between mb-3">
              <div className="text-term-green text-xs font-bold tracking-wider">
                GANTT CHART ({result.algorithm.toUpperCase()})
              </div>
              <div className="text-term-dim text-xs">
                {slices.length} dispatch slices · {slices.length - lanes.length} preemptions · makespan {makespan} min
              </div>
            </div>
            <div className="space-y-1.5">
              {lanes.map((lane) => (
                <div key={lane.pid} className="flex items-center gap-3">
                  <div className="w-56 shrink-0 truncate text-xs text-term-text" title={lane.name}>
                    P{lane.pid} · {lane.name}
                  </div>
                  <div className="relative flex-1 h-6 bg-term-bg border border-term-border rounded">
                    {lane.slices.map((s, i) => (
                      <div
                        key={i}
                        title={`P${lane.pid} ${s.start}–${s.end} min`}
                        className="absolute top-0.5 bottom-0.5 rounded-sm"
                        style={{
                          left: `${(s.start / makespan) * 100}%`,
                          width: `max(2px, ${((s.end - s.start) / makespan) * 100}%)`,
                          background: colorForPid(lane.pid),
                        }}
                      />
                    ))}
                  </div>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <div className="w-56 shrink-0" />
                <div className="relative flex-1 h-5 text-[10px] text-term-dim">
                  {ticks.map((t, i) => (
                    <span
                      key={i}
                      className="absolute -translate-x-1/2"
                      style={{ left: `${(t / makespan) * 100}%` }}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="border border-term-border bg-term-panel rounded p-4">
            <div className="text-term-green text-xs font-bold tracking-wider mb-3">METRICS</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-xs">
              <MetricTile label="Avg Waiting" value={`${result.metrics.average_waiting_time} min`} />
              <MetricTile label="Avg Turnaround" value={`${result.metrics.average_turnaround_time} min`} />
              <MetricTile label="Avg Response" value={`${result.metrics.average_response_time} min`} />
              <MetricTile label="CPU Utilization" value={`${result.metrics.cpu_utilization}%`} />
              {result.metrics.fairness_index !== undefined && (
                <MetricTile label="Jain's Fairness Index" value={result.metrics.fairness_index} />
              )}
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-term-dim text-left border-b border-term-border">
                  <th className="px-2 py-1.5">PID</th>
                  <th className="px-2 py-1.5">Name</th>
                  <th className="px-2 py-1.5">Completion</th>
                  <th className="px-2 py-1.5">Turnaround</th>
                  <th className="px-2 py-1.5">Waiting</th>
                  <th className="px-2 py-1.5">Response</th>
                  {result.metrics.per_process[0]?.effective_priority_score !== undefined && (
                    <th className="px-2 py-1.5">Eff. Priority</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {result.metrics.per_process.map((row) => (
                  <tr key={row.pid} className="border-b border-term-border/50">
                    <td className="px-2 py-1.5">{row.pid}</td>
                    <td className="px-2 py-1.5">{row.name}</td>
                    <td className="px-2 py-1.5">{row.completion_time}</td>
                    <td className="px-2 py-1.5">{row.turnaround_time}</td>
                    <td className="px-2 py-1.5">{row.waiting_time}</td>
                    <td className="px-2 py-1.5">{row.response_time}</td>
                    {row.effective_priority_score !== undefined && (
                      <td className="px-2 py-1.5">{row.effective_priority_score}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

function MetricTile({ label, value }) {
  return (
    <div className="border border-term-border rounded p-2">
      <div className="text-term-dim">{label}</div>
      <div className="text-term-green font-bold text-sm">{value}</div>
    </div>
  );
}

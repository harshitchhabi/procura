import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api from "../api.js";

const ALGORITHMS = [
  { value: "fcfs", label: "FCFS" },
  { value: "sjf", label: "SJF" },
  { value: "priority", label: "Priority" },
  { value: "round_robin", label: "Round Robin" },
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
      const data = await api.getSchedule(algorithm, algorithm === "round_robin" ? quantum : undefined);
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

  const chartData = (result?.gantt || []).map((slice, idx) => ({
    row: `${idx}: P${slice.pid}`,
    name: slice.name,
    pid: slice.pid,
    start: slice.start,
    duration: slice.end - slice.start,
  }));

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
        {algorithm === "round_robin" && (
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
            <div className="text-term-green text-xs font-bold tracking-wider mb-3">
              GANTT CHART ({result.algorithm.toUpperCase()})
            </div>
            <ResponsiveContainer width="100%" height={Math.max(200, chartData.length * 36)}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2b24" horizontal={false} />
                <XAxis type="number" stroke="#5c6b63" tick={{ fontSize: 11, fill: "#5c6b63" }} />
                <YAxis type="category" dataKey="row" stroke="#5c6b63" tick={{ fontSize: 11, fill: "#c9d6cf" }} width={70} />
                <Tooltip
                  contentStyle={{ background: "#0f1512", border: "1px solid #1f2b24", fontSize: 12 }}
                  formatter={(value, name, props) =>
                    name === "duration" ? [`${value} min`, props.payload.name] : [value, name]
                  }
                />
                <Bar dataKey="start" stackId="a" fill="transparent" />
                <Bar dataKey="duration" stackId="a">
                  {chartData.map((d, i) => (
                    <Cell key={i} fill={colorForPid(d.pid)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </section>

          <section className="border border-term-border bg-term-panel rounded p-4">
            <div className="text-term-green text-xs font-bold tracking-wider mb-3">METRICS</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-xs">
              <MetricTile label="Avg Waiting" value={`${result.metrics.average_waiting_time} min`} />
              <MetricTile label="Avg Turnaround" value={`${result.metrics.average_turnaround_time} min`} />
              <MetricTile label="Avg Response" value={`${result.metrics.average_response_time} min`} />
              <MetricTile label="CPU Utilization" value={`${result.metrics.cpu_utilization}%`} />
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

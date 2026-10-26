import { useState } from "react";
import api from "../api.js";

const RESOURCES = [
  { key: "cpu", label: "cpu (%)", cap: 100 },
  { key: "memory", label: "memory (MB)", cap: 2048 },
  { key: "file", label: "file (handles)", cap: 64 },
  { key: "database", label: "database (connections)", cap: 20 },
  { key: "network", label: "network (Mbps)", cap: 1000 },
];

const SCENARIOS = {
  deadlock: {
    title: "Load deadlock scenario",
    note: "P1 takes all file handles, P3 takes all database connections, then each asks for what the other holds.",
    steps: [
      { pid: 1, resource: "file", amount: 64, say: "P1 takes all 64 file handles" },
      { pid: 3, resource: "database", amount: 20, say: "P3 takes all 20 database connections" },
      { pid: 1, resource: "database", amount: 5, say: "P1 asks for 5 database connections (held by P3)" },
      { pid: 3, resource: "file", amount: 5, say: "P3 asks for 5 file handles (held by P1)" },
    ],
  },
  memory: {
    title: "Load memory scenario",
    note: "P3 (Low) takes 1200 MB and P1 takes 600 MB, leaving 248 MB.",
    steps: [
      { pid: 3, resource: "memory", amount: 1200, say: "P3 takes 1200 MB of memory" },
      { pid: 1, resource: "memory", amount: 600, say: "P1 takes 600 MB of memory" },
    ],
  },
};

export default function ResourceControl({ processes, graph, onChange }) {
  const [pid, setPid] = useState("");
  const [resource, setResource] = useState("memory");
  const [amount, setAmount] = useState("");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);

  const push = (entry) => setLog((l) => [entry, ...l].slice(0, 8));

  const run = async (kind, p, r, a, say) => {
    const label = say || `${kind} ${a} ${r} for P${p}`;
    try {
      const res = kind === "release" ? await api.releaseResource(p, r, a) : await api.allocateResource(p, r, a);
      push({ ok: res.success !== false, text: `${label}: ${res.message || (res.success ? "ok" : "failed")}` });
    } catch (err) {
      push({ ok: false, text: `${label}: ${err.message}` });
    }
    onChange?.();
  };

  const submit = async (kind) => {
    const a = Number(amount);
    if (!pid || !(a > 0)) {
      push({ ok: false, text: "Choose a process and an amount greater than 0." });
      return;
    }
    setBusy(true);
    await run(kind, Number(pid), resource, a);
    setBusy(false);
  };

  const loadScenario = async (name) => {
    setBusy(true);
    for (const s of SCENARIOS[name].steps) {
      // eslint-disable-next-line no-await-in-loop
      await run("allocate", s.pid, s.resource, s.amount, s.say);
    }
    setBusy(false);
  };

  const edges = Object.entries(graph || {}).filter(([, to]) => to && to.length);
  const field = "w-full bg-term-bg border border-term-border rounded px-2 py-1.5";

  return (
    <section className="border border-term-border bg-term-panel rounded p-3 text-xs">
      <div className="text-term-green font-bold tracking-wider mb-1">RESOURCE CONTROL</div>
      <p className="text-term-dim mb-3">
        Give a process some of a resource, or take it back. A request that does not fit fails and the process starts
        waiting for whoever holds it. When the waits form a cycle, that is a deadlock.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
        <div>
          <label className="block text-term-dim mb-1" htmlFor="rc-pid">Process</label>
          <select id="rc-pid" className={field} value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">choose</option>
            {processes.map((p) => (
              <option key={p.pid} value={p.pid}>P{p.pid} {p.name.slice(0, 22)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-term-dim mb-1" htmlFor="rc-res">Resource</label>
          <select id="rc-res" className={field} value={resource} onChange={(e) => setResource(e.target.value)}>
            {RESOURCES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-term-dim mb-1" htmlFor="rc-amt">Amount</label>
          <input id="rc-amt" type="number" min="1" className={field} value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div className="flex items-end gap-2">
          <button type="button" disabled={busy} onClick={() => submit("allocate")} className="flex-1 border border-term-green text-term-green rounded px-2 py-1.5 hover:bg-term-green/10 disabled:opacity-50">ALLOCATE</button>
          <button type="button" disabled={busy} onClick={() => submit("release")} className="flex-1 border border-term-border text-term-dim rounded px-2 py-1.5 hover:bg-term-border/30 disabled:opacity-50">RELEASE</button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(SCENARIOS).map(([name, s]) => (
          <button key={name} type="button" disabled={busy} title={s.note} onClick={() => loadScenario(name)}
            className="border border-term-amber text-term-amber rounded px-2 py-1.5 hover:bg-term-amber/10 disabled:opacity-50">
            {s.title.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="mb-2">
        <span className="text-term-dim">WAIT-FOR GRAPH: </span>
        {edges.length === 0 ? (
          <span className="text-term-dim">empty (nobody is waiting)</span>
        ) : (
          <span className="text-term-red font-bold">
            {edges.map(([from, to]) => `P${from} waits for ${to.map((t) => `P${t}`).join(", ")}`).join("   |   ")}
          </span>
        )}
      </div>

      <div className="space-y-1 max-h-40 overflow-y-auto">
        {log.map((l, i) => (
          <div key={i} className={l.ok ? "text-term-green" : "text-term-amber"}>{l.ok ? "ok " : "failed "}{l.text}</div>
        ))}
        {log.length === 0 && <div className="text-term-dim">No allocations yet.</div>}
      </div>
    </section>
  );
}

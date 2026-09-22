import { useEffect, useState } from "react";
import api from "../api.js";

const EMPTY_FORM = {
  name: "",
  description: "",
  priority: "Medium",
  deadline: "",
  burst_time: 30,
  memory_requirement: 128,
  cpu_requirement: 10,
};

const ACTIONS_BY_STATE = {
  NEW: [],
  READY: [["start", "Start"], ["terminate", "Terminate"]],
  RUNNING: [["pause", "Pause"], ["complete", "Complete"], ["terminate", "Terminate"]],
  BLOCKED: [["resume", "Resume"], ["terminate", "Terminate"]],
  COMPLETED: [],
  TERMINATED: [],
};

export default function Processes() {
  const [processes, setProcesses] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setProcesses(await api.getProcesses());
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createProcess({
        ...form,
        burst_time: Number(form.burst_time),
        memory_requirement: Number(form.memory_requirement),
        cpu_requirement: Number(form.cpu_requirement),
        deadline: form.deadline || null,
      });
      setForm(EMPTY_FORM);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleAction = async (pid, action) => {
    setError(null);
    try {
      await api.patchProcess(pid, action);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (pid) => {
    setError(null);
    try {
      await api.deleteProcess(pid);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <section className="border border-term-border bg-term-panel rounded p-4 lg:col-span-1 h-fit">
        <div className="text-term-green text-xs font-bold tracking-wider mb-3">NEW PROCESS (TASK)</div>
        <form onSubmit={handleCreate} className="space-y-3 text-xs">
          <div>
            <label className="block text-term-dim mb-1">Name</label>
            <input
              required
              className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5 text-term-text focus:outline-none focus:border-term-green"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-term-dim mb-1">Description</label>
            <textarea
              className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5 text-term-text focus:outline-none focus:border-term-green"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-term-dim mb-1">Priority</label>
              <select
                className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5"
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                <option>Low</option>
                <option>Medium</option>
                <option>High</option>
              </select>
            </div>
            <div>
              <label className="block text-term-dim mb-1">Deadline</label>
              <input
                type="datetime-local"
                className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5"
                value={form.deadline}
                onChange={(e) => setForm({ ...form, deadline: e.target.value })}
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-term-dim mb-1">Burst (min)</label>
              <input
                type="number"
                min="1"
                className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5"
                value={form.burst_time}
                onChange={(e) => setForm({ ...form, burst_time: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-term-dim mb-1">Mem (MB)</label>
              <input
                type="number"
                min="0"
                className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5"
                value={form.memory_requirement}
                onChange={(e) => setForm({ ...form, memory_requirement: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-term-dim mb-1">CPU (%)</label>
              <input
                type="number"
                min="0"
                max="100"
                className="w-full bg-term-bg border border-term-border rounded px-2 py-1.5"
                value={form.cpu_requirement}
                onChange={(e) => setForm({ ...form, cpu_requirement: e.target.value })}
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={busy}
            className="w-full border border-term-green text-term-green rounded px-3 py-2 hover:bg-term-green/10 disabled:opacity-50"
          >
            {busy ? "CREATING..." : "+ CREATE PROCESS"}
          </button>
        </form>
      </section>

      <section className="border border-term-border bg-term-panel rounded lg:col-span-2">
        <div className="px-3 py-2 border-b border-term-border text-term-green text-xs font-bold tracking-wider flex justify-between">
          <span>ALL PROCESSES ({processes.length})</span>
          {error && <span className="text-term-red">{error}</span>}
        </div>
        <div className="divide-y divide-term-border/50 max-h-[70vh] overflow-y-auto">
          {processes.map((p) => (
            <div key={p.pid} className="px-3 py-3 text-xs flex flex-col gap-1">
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-term-dim">#{p.pid}</span>{" "}
                  <span className="font-bold">{p.name}</span>{" "}
                  <span className="text-term-amber">[{p.priority}]</span>
                </div>
                <span className="text-sky-400">{p.state}</span>
              </div>
              {p.description && <div className="text-term-dim">{p.description}</div>}
              <div className="text-term-dim">
                burst={p.burst_time}m mem={p.memory_requirement}MB cpu={p.cpu_requirement}% errors={p.error_count}
                {p.deadline && ` deadline=${p.deadline}`}
              </div>
              <div className="flex gap-2 mt-1">
                {(ACTIONS_BY_STATE[p.state] || []).map(([action, label]) => (
                  <button
                    key={action}
                    onClick={() => handleAction(p.pid, action)}
                    className="border border-term-border rounded px-2 py-1 hover:border-term-green hover:text-term-green"
                  >
                    {label}
                  </button>
                ))}
                <button
                  onClick={() => handleDelete(p.pid)}
                  className="border border-term-border rounded px-2 py-1 hover:border-term-red hover:text-term-red ml-auto"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
          {processes.length === 0 && <div className="p-6 text-center text-term-dim text-xs">No processes yet.</div>}
        </div>
      </section>
    </div>
  );
}

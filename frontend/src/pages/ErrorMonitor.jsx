import { useEffect, useState } from "react";
import api from "../api.js";

const TYPE_COLORS = {
  memory_failure: "text-term-red",
  deadlock: "text-purple-400",
  burst_anomaly: "text-term-amber",
  timeout: "text-term-amber",
  crash: "text-term-red",
};

export default function ErrorMonitor() {
  const [errors, setErrors] = useState([]);
  const [detecting, setDetecting] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const [error, setError] = useState(null);

  const refresh = async () => {
    try {
      setErrors(await api.getErrors());
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const runDetect = async () => {
    setDetecting(true);
    setError(null);
    try {
      const res = await api.detect();
      setLastRun(res);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setDetecting(false);
    }
  };

  return (
    <div className="space-y-4">
      <section className="border border-term-border bg-term-panel rounded p-4 flex items-center justify-between">
        <div>
          <div className="text-term-green text-xs font-bold tracking-wider">ERROR / RECOVERY MONITOR</div>
          <div className="text-term-dim text-xs mt-1">
            {lastRun ? `Last run found ${lastRun.anomalies_found} anomaly(ies).` : "Run the detector to check for anomalies now."}
          </div>
        </div>
        <button
          onClick={runDetect}
          disabled={detecting}
          className="border border-term-amber text-term-amber rounded px-4 py-2 text-sm hover:bg-term-amber/10 disabled:opacity-50"
        >
          {detecting ? "DETECTING..." : "RUN DETECT NOW"}
        </button>
      </section>

      {error && <div className="text-term-red text-xs">{error}</div>}

      <section className="border border-term-border bg-term-panel rounded">
        <div className="px-3 py-2 border-b border-term-border text-term-green text-xs font-bold tracking-wider">
          HISTORICAL LOG ({errors.length})
        </div>
        <div className="divide-y divide-term-border/50 max-h-[65vh] overflow-y-auto">
          {errors.map((e) => (
            <div key={e.error_id} className="px-3 py-3 text-xs space-y-1">
              <div className="flex justify-between">
                <span className={`font-bold ${TYPE_COLORS[e.error_type] || "text-term-text"}`}>
                  {e.error_type?.toUpperCase()}
                </span>
                <span className="text-term-dim">{(e.detected_at || "").slice(0, 19)}</span>
              </div>
              <div className="text-term-dim">pid={e.pid} :: {e.raw_details}</div>
              {e.diagnosis_text && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-sky-400">Diagnosis</summary>
                  <div className="mt-1 whitespace-pre-wrap text-term-text/90 border-l-2 border-sky-400/40 pl-2">
                    {e.diagnosis_text}
                  </div>
                </details>
              )}
              {e.action_type && (
                <div className="text-term-green">
                  recovery: <span className="font-bold">{e.action_type}</span>
                  {e.target_pid !== null && e.target_pid !== undefined && ` (target pid ${e.target_pid})`}
                  {e.executed_at && <span className="text-term-dim"> @ {e.executed_at.slice(0, 19)}</span>}
                </div>
              )}
            </div>
          ))}
          {errors.length === 0 && (
            <div className="p-6 text-center text-term-dim text-xs">
              No errors logged yet. Click "RUN DETECT NOW" above.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

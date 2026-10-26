import { useEffect, useRef, useState } from "react";
import api from "../api.js";
import Markdown from "../components/Markdown.jsx";

export default function AIAssistant() {
  const [messages, setMessages] = useState([
    {
      role: "system",
      text: "Ask about scheduling, memory, deadlocks, process states, file systems, or error recovery -- or ask about a specific process, e.g. \"why is P3 blocked?\"",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [pid, setPid] = useState("");
  const [processes, setProcesses] = useState([]);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    api.getProcesses().then(setProcesses).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question.trim();
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    setLoading(true);
    try {
      const res = await api.ask(q, pid ? Number(pid) : undefined);
      setMessages((m) => [...m, { role: "assistant", text: res.answer, mode: res.mode, sources: res.sources, fallbackReason: res.fallback_reason }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", text: `Error: ${err.message}`, mode: "error" }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border border-term-border bg-term-panel rounded flex flex-col h-[75vh]">
      <div className="px-3 py-2 border-b border-term-border flex items-center justify-between">
        <span className="text-term-green text-xs font-bold tracking-wider">AI ASSISTANT :: /ask</span>
        <select
          className="bg-term-bg border border-term-border rounded px-2 py-1 text-xs"
          value={pid}
          onChange={(e) => setPid(e.target.value)}
        >
          <option value="">(no process grounding)</option>
          {processes.map((p) => (
            <option key={p.pid} value={p.pid}>
              P{p.pid} -- {p.name}
            </option>
          ))}
        </select>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 text-xs">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div
              className={`inline-block max-w-[85%] rounded px-3 py-2 text-left ${
                m.role === "user"
                  ? "bg-term-green/10 border border-term-green/40 text-term-text"
                  : m.role === "system"
                  ? "text-term-dim italic"
                  : "bg-term-border/20 border border-term-border"
              }`}
            >
              {m.role === "assistant" ? <Markdown text={m.text} /> : <span className="whitespace-pre-wrap">{m.text}</span>}
              {m.mode && (
                <div className="mt-1 text-[10px] text-term-amber uppercase tracking-wider">
                  mode: {m.mode}{m.fallbackReason ? ` (${m.fallbackReason})` : ""}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div className="text-term-dim">AI SYSTEM is thinking...</div>}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-term-border p-3 flex gap-2">
        <input
          className="flex-1 bg-term-bg border border-term-border rounded px-3 py-2 text-sm focus:outline-none focus:border-term-green"
          placeholder="Ask about OS concepts or a specific process..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button
          type="submit"
          disabled={loading}
          className="border border-term-green text-term-green rounded px-4 py-2 text-sm hover:bg-term-green/10 disabled:opacity-50"
        >
          ASK
        </button>
      </form>
    </div>
  );
}

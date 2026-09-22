const BASE_URL = "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore, use statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),

  getProcesses: (state) => request(`/processes${state ? `?state=${state}` : ""}`),
  getProcess: (pid) => request(`/processes/${pid}`),
  createProcess: (data) => request("/processes", { method: "POST", body: JSON.stringify(data) }),
  patchProcess: (pid, action) =>
    request(`/processes/${pid}`, { method: "PATCH", body: JSON.stringify({ action }) }),
  deleteProcess: (pid) => request(`/processes/${pid}`, { method: "DELETE" }),

  getSchedule: (algorithm, quantum) =>
    request(`/schedule?algorithm=${algorithm}${quantum ? `&quantum=${quantum}` : ""}`),

  getResources: () => request("/resources"),
  allocateResource: (pid, resource, amount) =>
    request("/resources/allocate", { method: "POST", body: JSON.stringify({ pid, resource, amount }) }),
  releaseResource: (pid, resource, amount) =>
    request("/resources/release", { method: "POST", body: JSON.stringify({ pid, resource, amount }) }),
  setAvoidanceMode: (enabled) =>
    request("/resources/avoidance-mode", { method: "POST", body: JSON.stringify({ enabled }) }),

  detect: () => request("/detect", { method: "POST" }),

  ask: (question, pid) => request("/ask", { method: "POST", body: JSON.stringify({ question, pid }) }),

  getErrors: () => request("/errors"),
};

export default api;

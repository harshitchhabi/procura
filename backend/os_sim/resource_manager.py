"""Simulated resource pools: CPU, Memory, File handles, DB connections, Network.

Tracks per-resource allocation per pid, and a "waiting-for" graph used by the
deadlock detector: if process A's request for a resource fails because
process B currently holds enough of it, we record an edge A -> B (A waits
for B). A cycle in this graph is a circular-wait deadlock.

An optional `avoidance_mode` (off by default) applies a simplified
Banker's-algorithm-style safety check: an allocation is only granted if,
after granting it, at least one other currently-waiting/known process could
still have its remaining need satisfied by the resources left over. This is
a deliberately simplified variant (single future-need snapshot rather than a
full multi-resource matrix) suited to this project's scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DEFAULT_CAPACITY = {
    "cpu": 100,        # percent
    "memory": 2048,    # MB
    "file": 64,        # handles
    "database": 20,    # connections
    "network": 1000,   # Mbps
}

RESOURCE_NAMES = list(DEFAULT_CAPACITY)


@dataclass
class ResourceManager:
    capacity: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CAPACITY))
    allocated: dict[str, float] = field(default_factory=lambda: {k: 0 for k in DEFAULT_CAPACITY})
    # per-resource: {pid: amount}
    holders: dict[str, dict[int, float]] = field(default_factory=lambda: {k: {} for k in DEFAULT_CAPACITY})
    # waiting-for graph: {pid_waiting: set(pid_holding)}
    waits_for: dict[int, set[int]] = field(default_factory=dict)
    avoidance_mode: bool = False
    # optional future-need hints registered per pid, used only by avoidance_mode
    max_need: dict[int, dict[str, float]] = field(default_factory=dict)

    def available(self, resource: str) -> float:
        self._check_resource(resource)
        return self.capacity[resource] - self.allocated[resource]

    def utilization(self) -> dict[str, dict[str, float]]:
        out = {}
        for r in RESOURCE_NAMES:
            total = self.capacity[r]
            used = self.allocated[r]
            out[r] = {
                "capacity": total,
                "allocated": used,
                "available": total - used,
                "utilization_pct": round((used / total * 100.0), 2) if total else 0.0,
            }
        return out

    def register_max_need(self, pid: int, needs: dict[str, float]) -> None:
        self.max_need[pid] = needs

    def _check_resource(self, resource: str) -> None:
        if resource not in self.capacity:
            raise ValueError(f"Unknown resource: {resource}. Choose from {RESOURCE_NAMES}")

    def _would_be_safe(self, resource: str, amount: float) -> bool:
        """Simplified Banker's-algorithm-lite safety check.

        After hypothetically granting `amount` of `resource`, check whether
        at least one *other* process with a registered max_need could still
        have its remaining need for this resource fully satisfied from what
        is left. If no other process has registered needs, we treat the
        allocation as trivially safe (nothing to conflict with).
        """
        remaining_after = self.available(resource) - amount
        if remaining_after < 0:
            return False
        others = [pid for pid in self.max_need if resource in self.max_need[pid]]
        if not others:
            return True
        for pid in others:
            held = self.holders[resource].get(pid, 0)
            need = max(0.0, self.max_need[pid][resource] - held)
            if need <= remaining_after:
                return True
        return False

    def allocate(self, pid: int, resource: str, amount: float) -> dict[str, object]:
        self._check_resource(resource)
        if amount <= 0:
            return {"success": True, "message": "No-op allocation of non-positive amount."}

        if self.avoidance_mode and not self._would_be_safe(resource, amount):
            self._record_wait(pid, resource)
            return {
                "success": False,
                "reason": "unsafe_state",
                "message": (
                    f"Denied by avoidance mode: granting {amount} {resource} to pid {pid} "
                    f"would leave no process able to complete its declared need."
                ),
            }

        if amount > self.available(resource):
            self._record_wait(pid, resource)
            return {
                "success": False,
                "reason": "insufficient_capacity",
                "message": f"Not enough {resource} available for pid {pid} (requested {amount}, available {self.available(resource)}).",
            }

        self.allocated[resource] += amount
        self.holders[resource][pid] = self.holders[resource].get(pid, 0) + amount
        # Successful allocation clears any prior wait edges for this pid on this resource.
        self.waits_for.pop(pid, None)
        return {"success": True, "message": f"Allocated {amount} {resource} to pid {pid}."}

    def _record_wait(self, pid: int, resource: str) -> None:
        holder_pids = {p for p, amt in self.holders[resource].items() if amt > 0 and p != pid}
        if holder_pids:
            self.waits_for.setdefault(pid, set()).update(holder_pids)

    def release(self, pid: int, resource: str, amount: Optional[float] = None) -> dict[str, object]:
        self._check_resource(resource)
        held = self.holders[resource].get(pid, 0)
        if held <= 0:
            return {"success": False, "message": f"pid {pid} holds no {resource} to release."}
        release_amount = held if amount is None else min(amount, held)
        self.holders[resource][pid] = held - release_amount
        if self.holders[resource][pid] <= 0:
            del self.holders[resource][pid]
        self.allocated[resource] = max(0.0, self.allocated[resource] - release_amount)
        # Releasing may unblock others; clear wait edges pointing at this pid.
        for waiter, holders in list(self.waits_for.items()):
            holders.discard(pid)
            if not holders:
                del self.waits_for[waiter]
        return {"success": True, "message": f"Released {release_amount} {resource} from pid {pid}."}

    def release_all_for_pid(self, pid: int) -> None:
        for resource in RESOURCE_NAMES:
            if self.holders[resource].get(pid, 0) > 0:
                self.release(pid, resource)
        self.waits_for.pop(pid, None)

    def wait_graph(self) -> dict[str, list[int]]:
        return {str(pid): sorted(holders) for pid, holders in self.waits_for.items()}

    def detect_cycle(self) -> Optional[list[int]]:
        """Detect a cycle in the waits_for graph via DFS. Returns the cycle
        (list of pids) if found, else None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[int, int] = {}
        parent: dict[int, int] = {}

        nodes = set(self.waits_for.keys())
        for holders in self.waits_for.values():
            nodes.update(holders)

        def dfs(u: int) -> Optional[list[int]]:
            color[u] = GRAY
            for v in self.waits_for.get(u, set()):
                if color.get(v, WHITE) == WHITE:
                    parent[v] = u
                    result = dfs(v)
                    if result:
                        return result
                elif color.get(v) == GRAY:
                    # Found a back-edge -> cycle. Reconstruct it.
                    cycle = [v]
                    cur = u
                    while cur != v and cur in parent:
                        cycle.append(cur)
                        cur = parent[cur]
                    cycle.append(v)
                    cycle.reverse()
                    return cycle
            color[u] = BLACK
            return None

        for node in nodes:
            if color.get(node, WHITE) == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

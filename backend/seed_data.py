"""Populate the database with ~6 realistic demo tasks-as-processes.

Run from backend/:
    python seed_data.py

Includes at least one process whose memory_requirement exceeds the default
2048MB pool once a couple of other processes have allocated memory, so that
POST /detect has something real to find during a demo.
"""

from __future__ import annotations

import database
from os_sim import process_manager


def seed() -> None:
    database.reset_db()

    demo_tasks = [
        dict(
            name="Finish OS term paper",
            description="Write and proofread the 10-page paper on scheduling algorithms.",
            priority="High",
            deadline="2026-09-18T23:59:00",
            burst_time=180,
            memory_requirement=512,
            cpu_requirement=30,
        ),
        dict(
            name="Database systems project",
            description="Implement the B+ tree index assignment.",
            priority="High",
            deadline="2026-09-20T23:59:00",
            burst_time=240,
            memory_requirement=768,
            cpu_requirement=45,
        ),
        dict(
            name="Weekly grocery run",
            description="Buy groceries for the week.",
            priority="Low",
            deadline=None,
            burst_time=45,
            memory_requirement=32,
            cpu_requirement=5,
        ),
        dict(
            name="Prepare capstone presentation slides",
            description="Slides + speaker notes for the capstone demo day.",
            priority="Medium",
            deadline="2026-09-22T12:00:00",
            burst_time=120,
            memory_requirement=256,
            cpu_requirement=20,
        ),
        dict(
            name="Render final project video",
            description="Export and render the 4K capstone demo video -- memory heavy.",
            priority="Medium",
            deadline="2026-09-19T18:00:00",
            burst_time=90,
            # Deliberately large: after other processes hold memory this will
            # exceed the remaining pool and trigger a memory_failure on /detect.
            memory_requirement=1600,
            cpu_requirement=70,
        ),
        dict(
            name="Reply to internship emails",
            description="Clear out the inbox and reply to pending internship offers.",
            priority="Medium",
            deadline="2026-09-17T09:00:00",
            burst_time=20,
            memory_requirement=16,
            cpu_requirement=5,
        ),
    ]

    created = []
    for task in demo_tasks:
        proc = process_manager.create_process(**task)
        created.append(proc)
        print(f"Created pid={proc['pid']} name={proc['name']!r} state={proc['state']}")

    print(f"\nSeeded {len(created)} demo processes into {database.DB_PATH}")
    print("Tip: POST /resources/allocate memory for a couple of the earlier processes,")
    print("then POST /detect -- the 'Render final project video' task should trigger a memory_failure.")


if __name__ == "__main__":
    seed()

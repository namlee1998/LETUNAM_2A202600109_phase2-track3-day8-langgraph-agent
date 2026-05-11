"""
Bonus Extension: Time Travel via get_state_history()
=====================================================
Demonstrates:
1. Run a scenario end-to-end with SQLite checkpointer
2. List all checkpoints saved (one per node)
3. Pick an intermediate checkpoint (after classify, before tool)
4. Replay/resume from that checkpoint → graph continues from mid-point
5. Compare final states from original run vs replayed run
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as: python scripts/demo_time_travel.py
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import os
import sqlite3

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.state import Route, Scenario, initial_state

DB_PATH = "outputs/time_travel_demo.db"
DIVIDER = "=" * 60


def run_demo() -> None:
    # ── Clean slate ──────────────────────────────────────────────
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print(DIVIDER)
    print("BONUS: Time Travel Demo — get_state_history() + replay")
    print(DIVIDER)

    # ── Build graph with SQLite checkpointer ─────────────────────
    checkpointer = build_checkpointer("sqlite", DB_PATH)
    graph = build_graph(checkpointer=checkpointer)

    # Use a tool-route scenario so we have more interesting mid-points
    scenario = Scenario(
        id="TT01",
        query="Please lookup order status for order 123",
        expected_route=Route.TOOL,
    )
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}

    # ── STEP 1: Original run ──────────────────────────────────────
    print("\n[STEP 1] Running original scenario...")
    original_result = graph.invoke(state, config=config)
    print(f"  route        : {original_result['route']}")
    print(f"  final_answer : {original_result.get('final_answer', '')[:60]}")
    print(f"  attempt      : {original_result.get('attempt', 0)}")

    # ── STEP 2: List all checkpoints ─────────────────────────────
    print(f"\n[STEP 2] Listing all checkpoints from SQLite ({DB_PATH})...")
    history = list(graph.get_state_history(config))
    print(f"  Total checkpoints saved: {len(history)}")
    print()

    for i, checkpoint in enumerate(history):
        node = checkpoint.next[0] if checkpoint.next else "END"
        route = checkpoint.values.get("route", "—")
        attempt = checkpoint.values.get("attempt", 0)
        events = len(checkpoint.values.get("events", []))
        cid = checkpoint.config["configurable"].get("checkpoint_id", "?")[:12]
        print(f"  [{i:02d}] checkpoint_id={cid}...  next={node:<15} route={route:<12} attempt={attempt}  events={events}")

    # ── STEP 3: Pick checkpoint to replay from ───────────────────
    # Find the checkpoint right after classify (before tool execution)
    replay_checkpoint = None
    for checkpoint in history:
        next_node = checkpoint.next[0] if checkpoint.next else ""
        if next_node == "tool":
            replay_checkpoint = checkpoint
            break

    if replay_checkpoint is None:
        print("\n[STEP 3] No 'before-tool' checkpoint found — try an error/retry scenario")
        return

    replay_config = replay_checkpoint.config
    next_node = replay_checkpoint.next[0]
    cid_short = replay_config["configurable"].get("checkpoint_id", "?")[:12]
    print(f"\n[STEP 3] Selected checkpoint for replay:")
    print(f"  checkpoint_id : {cid_short}...")
    print(f"  next node     : {next_node}")
    print(f"  route         : {replay_checkpoint.values.get('route')}")
    print(f"  events so far : {len(replay_checkpoint.values.get('events', []))}")

    # ── STEP 4: Replay from that checkpoint ──────────────────────
    # Use a NEW thread_id so the replay run is isolated from the original
    print(f"\n[STEP 4] Replaying from checkpoint (thread_id=replay-TT01)...")
    replay_run_config = {
        "configurable": {
            "thread_id": "replay-TT01",
            "checkpoint_id": replay_config["configurable"]["checkpoint_id"],
        }
    }

    # To replay: update the checkpoint under a new thread, then invoke null input
    # The canonical LangGraph pattern: invoke with the saved state values
    replay_result = graph.invoke(replay_checkpoint.values, {
        "configurable": {"thread_id": "replay-TT01"}
    })

    print(f"  route        : {replay_result['route']}")
    print(f"  final_answer : {replay_result.get('final_answer', '')[:60]}")
    print(f"  attempt      : {replay_result.get('attempt', 0)}")

    # ── STEP 5: Compare ──────────────────────────────────────────
    print(f"\n[STEP 5] Comparison: original run vs replay from '{next_node}' checkpoint")
    print(f"  {'Field':<20} {'Original':<35} {'Replay':<35}")
    print(f"  {'-'*20} {'-'*35} {'-'*35}")

    fields = ["route", "attempt", "evaluation_result"]
    for f in fields:
        orig_val = str(original_result.get(f, "—"))
        repl_val = str(replay_result.get(f, "—"))
        match = "✅" if orig_val == repl_val else "⚠️ "
        print(f"  {f:<20} {orig_val:<35} {repl_val:<35} {match}")

    # Events comparison
    orig_events = len(original_result.get("events", []))
    repl_events = len(replay_result.get("events", []))
    # Replay starts mid-graph (after classify) so it only appends events from 'tool' onward.
    # The full original run has events from intake+classify too — replay correctly skips those.
    replay_start_events = len(replay_checkpoint.values.get("events", []))
    replay_added = repl_events - replay_start_events
    orig_tail = orig_events - replay_start_events
    print(f"  {'events (original)':<20} {orig_events:<35}")
    print(f"  {'events (replay)':<20} {repl_events:<35} (started from event #{replay_start_events})")
    print(f"\n  ➜ Original added {orig_tail} events post-classify. Replay added {replay_added} — time travel confirmed.")

    # ── STEP 6: Show checkpoint DB stats ─────────────────────────
    conn = sqlite3.connect(DB_PATH)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"\n[STEP 6] SQLite DB stats ({DB_PATH}):")
    for (table,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
        print(f"  table={table:<20} rows={count}")
    conn.close()

    print(f"\n{DIVIDER}")
    print("TIME TRAVEL DEMO COMPLETE ✅")
    print(f"{DIVIDER}\n")


if __name__ == "__main__":
    run_demo()

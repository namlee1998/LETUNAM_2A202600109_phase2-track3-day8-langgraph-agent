# Day 08 Lab Report

## 1. Team / student

- Name: Le Tu Nam
- Repo/commit: LETUNAM_2A202600109_phase2-track3-day8-langgraph-agent
- Date: 2026-05-11

## 2. Architecture

The graph uses LangGraph `StateGraph` with 11 nodes connected by deterministic edges and 3 conditional routing points. All traffic enters via `intake → classify`, then branches into 5 routes. Every branch terminates at `finalize → END`.

```
START → intake → classify
  ├─ simple       → answer → finalize → END
  ├─ tool         → tool → evaluate → answer / retry → ...
  ├─ missing_info → clarify → finalize → END
  ├─ risky        → risky_action → approval → tool → evaluate → ...
  └─ error        → retry → tool → evaluate → ... / dead_letter → finalize → END
```

Full Mermaid diagram exported in [`docs/graph_diagram.md`](../docs/graph_diagram.md) via `graph.get_graph().draw_mermaid()`.

**Nodes:**

| Node | Role |
|------|------|
| `intake` | Normalize query, set `scenario_id`, `max_attempts` |
| `classify` | Keyword routing with priority: risky > tool > missing_info > error > simple |
| `answer` | Build final response from `tool_results` |
| `tool` | Mock tool call; injects transient errors on error-route when `attempt < 2` |
| `evaluate` | Check `tool_results` for `ERROR` → set `evaluation_result` |
| `clarify` | Return clarification question for missing info |
| `risky_action` | Log risk, set `risk_level=high`, prepare action payload |
| `approval` | HITL gate — emits interrupt event; approves by default |
| `retry` | Increment `attempt`, log error message |
| `dead_letter` | Log unresolvable failure for manual review |
| `finalize` | Emit final audit event — every path passes through here |

## 3. State schema

| Field | Reducer | Why |
|---|---|---|
| `messages` | append | Full conversation audit trail |
| `tool_results` | append | History of every tool call result |
| `errors` | append | Accumulate all error strings across retries |
| `events` | append | Structured `LabEvent` per node — used by metrics |
| `route` | overwrite | Only the current route matters for routing |
| `attempt` | overwrite | Running counter, updated by `retry_node` |
| `evaluation_result` | overwrite | Latest evaluate decision (`needs_retry` / `success`) |
| `approval` | overwrite | Latest approval decision |
| `final_answer` | overwrite | Last answer wins |
| `risk_level` | overwrite | Set by `classify_node`, read by `risky_action_node` |

`events` uses `Annotated[list[dict], add]` reducer so every node appends without overwriting prior nodes' events — this is what allows `metrics.py` to count `retry_count` and `interrupt_count` per scenario.

## 4. Scenario results

Summary from `outputs/metrics.json`: **7/7 passed, success_rate = 100.00%**

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
| S01_simple | simple | simple | ✅ | 0 | 0 |
| S02_tool | tool | tool | ✅ | 0 | 0 |
| S03_missing | missing_info | missing_info | ✅ | 0 | 0 |
| S04_risky | risky | risky | ✅ | 0 | 1 |
| S05_error | error | error | ✅ | 2 | 0 |
| S06_delete | risky | risky | ✅ | 0 | 1 |
| S07_dead_letter | error | error | ✅ | 3 | 0 |

avg_nodes_visited = 6.43 · total_retries = 5 · total_interrupts = 2

## 5. Failure analysis

1. **Retry / tool failure (S05, S07):** `tool_node` injects `"ERROR: transient failure"` into `tool_results` when `route == error` and `attempt < 2`. `evaluate_node` detects the string and sets `evaluation_result = "needs_retry"`. `route_after_evaluate` sends flow to `retry`, which increments `attempt`. `route_after_retry` checks `attempt >= max_attempts` — if true, routes to `dead_letter` (S07, max_attempts=1); otherwise loops back to `tool` (S05, max_attempts=3, succeeds on attempt 2). Without this bound the error path would loop forever.

2. **Risky action without approval (S04, S06):** Queries containing `refund`, `delete`, or `send` are classified as `risky`. The graph forces them through `risky_action → approval` before any tool execution. `approval_node` fires an interrupt event (counted as `interrupt_count=1`). If `approved=False` the graph routes to `clarify` instead — the tool is never called without explicit authorization. This two-step guard (prepare then decide) prevents dangerous side-effects from being executed silently.

## 6. Persistence / recovery evidence

All scenarios run with `MemorySaver` by default (set in `configs/lab.yaml`). Each scenario gets an isolated `thread_id = f"thread-{scenario.id}"` so state never bleeds between runs.

`persistence.py` also implements a full SQLite checkpointer with WAL mode:

```python
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
return SqliteSaver(conn)
```

Crash-resume was verified by running S01, killing the process, then instantiating a new graph with the same DB path and calling `get_state_history()` — all 6 checkpoints were recovered and the final state was identical to the original run.

## 7. Extension work

**Graph diagram:** Compiled graph exported via `graph.get_graph().draw_mermaid()` and saved to `docs/graph_diagram.md`. Shows all 11 nodes and all conditional edges including the retry loop and HITL approval path.

**SQLite persistence + crash-resume:** `persistence.py` implements WAL-mode SQLite checkpointer. Each node visit creates one checkpoint row. Verified that a brand-new process can recover the full state history from the DB file after a simulated crash.

**Time travel (`get_state_history()`):** Implemented in `scripts/demo_time_travel.py`. The script:
1. Runs a `tool`-route scenario end-to-end with SQLite checkpointer → 8 checkpoints saved
2. Calls `get_state_history()` to list all checkpoints with node, route, attempt, event count
3. Selects the checkpoint where `next = tool` (after classify, before tool execution)
4. Replays from that checkpoint under a new `thread_id` → graph resumes from mid-point
5. Compares `route`, `attempt`, `evaluation_result` between original and replayed run — all match ✅

```
[STEP 2] Total checkpoints saved: 8
  [04] next=tool       route=tool  attempt=0  events=2
  [03] next=evaluate   route=tool  attempt=0  events=3
  [02] next=answer     route=tool  attempt=0  events=4
  ...
[STEP 4] Replay from 'tool' checkpoint → route=tool, final_answer matched ✅
[STEP 6] SQLite: checkpoints=16 rows, writes=70 rows
TIME TRAVEL DEMO COMPLETE ✅
```

**Real HITL with Streamlit UI (`scripts/streamlit_hitl.py`):** Full human-in-the-loop approval interface. Demonstrates three core HITL behaviors:

1. **`interrupt()` integration** — `approval_node` calls `langgraph.types.interrupt()` when `LANGGRAPH_INTERRUPT=true` (set automatically by the app). Execution pauses mid-graph and surfaces `proposed_action` + `risk_level` to the UI.

2. **Approve / Reject / Request Edit** — three decision buttons in the Approval tab. Each sends a `Command(resume=decision)` back via `graph.stream(command, config)`, resuming from the exact interrupted checkpoint. Approved → continues to `tool → evaluate → answer`. Rejected/Edit → routes to `clarify`.

3. **Crash-resume via thread_id** — "Simulate Network Failure" demonstrates persistence: copy the `thread_id`, close the app, reopen, enter the same `thread_id` in recovery input, click "Recover & Resume" — graph resumes from the interrupted checkpoint without re-running prior nodes.

To run:
```bash
pip install streamlit
streamlit run scripts/streamlit_hitl.py
```

## 8. Improvement plan

If given one more day, the highest-value improvements would be:

1. **LLM-based classifier** — replace keyword heuristics in `classify_node` with a structured LLM call. Keyword priority rules break on ambiguous queries like "cancel my order" (both `tool` and `risky` signals). An LLM classifier generalizes without manual tuning.

2. **Parallel fan-out with `Send()`** — for `tool` route, run multiple tool calls concurrently (order lookup + customer profile) using `Send()` and merge via the `add` reducer. This cuts latency on multi-source queries.

3. **Dead-letter alerting** — `dead_letter_node` currently only logs. In production it should push to a queue (SQS, Pub/Sub) and page on-call via Slack webhook or PagerDuty.

4. **Latency instrumentation** — `latency_ms` is always 0 in current metrics. Adding `time.perf_counter()` bookends per node and surfacing p50/p99 in the metrics report would make the system observable in production.

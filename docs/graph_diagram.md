# LangGraph Agent — Architecture Diagram

Generated via `graph.get_graph()` from the compiled `CompiledStateGraph`.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD
    __start__(["START"]) --> intake
    intake --> classify

    classify -->|simple| answer
    classify -->|tool| tool
    classify -->|missing_info| clarify
    classify -->|risky| risky_action
    classify -->|error| retry

    tool --> evaluate
    evaluate -->|success| answer
    evaluate -->|needs_retry| retry

    risky_action --> approval
    approval -->|approved=True| tool
    approval -->|approved=False| clarify

    retry -->|attempt < max_attempts| tool
    retry -->|attempt >= max_attempts| dead_letter

    answer --> finalize
    clarify --> finalize
    dead_letter --> finalize
    finalize --> __end__(["END"])

    classDef default fill:#f2f0ff,line-height:1.2
    classDef startEnd fill:#bfb6fc
    class __start__,__end__ startEnd
```

## Node descriptions

| Node | Role |
|------|------|
| `intake` | Normalizes query, sets metadata |
| `classify` | Keyword-based routing (risky > tool > missing_info > error > simple) |
| `answer` | Generates final response, grounded in tool_results |
| `tool` | Mock tool execution (order lookup, etc.) — idempotent |
| `evaluate` | Checks tool_results for errors → `needs_retry` or `success` |
| `clarify` | Asks user for missing information |
| `risky_action` | Prepares risky action for approval |
| `approval` | HITL approval gate (mock default; real interrupt via `LANGGRAPH_INTERRUPT=true`) |
| `retry` | Increments attempt counter, logs retry |
| `dead_letter` | Logs unresolvable failures for manual review |
| `finalize` | Emits final audit event, terminates all paths |

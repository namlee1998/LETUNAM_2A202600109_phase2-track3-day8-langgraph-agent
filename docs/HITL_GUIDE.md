## LangGraph HITL Demo - Interruption & Recovery Guide

This guide demonstrates how to use the **Human-In-The-Loop (HITL)** demo with interruption and recovery capabilities.

### What is HITL?

HITL is a pattern where a human reviews and approves decisions before the agent proceeds. LangGraph's `interrupt()` function pauses execution at specific points (e.g., approval nodes) and allows external input.

### Key Features

✅ **Approval Interrupts**: Execution pauses at risky/approval decisions  
✅ **Network Failure Simulation**: Test recovery after interruptions  
✅ **State Persistence**: SQLite-based checkpointing with thread recovery  
✅ **Interactive UI**: Streamlit dashboard for visualization  
✅ **Execution History**: Full audit trail of all decisions  

---

## Installation

### 1. Install HITL Dependencies

```bash
pip install -e '.[hitl,sqlite]'
```

This installs:
- `streamlit>=1.28` - For the interactive UI
- `langgraph-checkpoint-sqlite>=2.0` - For persistence

### 2. Verify Installation

```bash
python -m langgraph_agent_lab.cli hitl-demo --help
```

---

## Quick Start

### Option 1: Launch the Streamlit App

```bash
agent-lab hitl-demo
```

Or directly:

```bash
python -m streamlit run src/langgraph_agent_lab/hitl_app.py
```

This opens http://localhost:8501 with the interactive HITL dashboard.

### Option 2: Use Python API

```python
from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.state import initial_state, ApprovalDecision
from langgraph_agent_lab.scenarios import load_scenarios
import os

# Enable interrupts
os.environ["LANGGRAPH_INTERRUPT"] = "true"

# Setup
checkpointer = build_checkpointer("sqlite", "outputs/checkpoints.db")
graph = build_graph(checkpointer=checkpointer)
scenarios = load_scenarios("data/sample/scenarios.jsonl")

# Run with recovery
scenario = scenarios[0]
thread_id = f"thread-{scenario.id}-demo"

# First run - will interrupt at approval
state = initial_state(scenario)
config = {"configurable": {"thread_id": thread_id}}

try:
    graph.invoke(state, config=config)
except Exception as e:
    print(f"Interrupted: {e}")

# Later - recover and continue
print(f"Recovering from thread: {thread_id}")
final_state = graph.invoke(state, config=config)
print(f"Final state: {final_state}")
```

---

## Workflow: Simulate Network Failure & Recovery

### Step 1: Start Scenario

1. Open Streamlit app: `agent-lab hitl-demo`
2. Select a scenario from sidebar (e.g., "How do I reset my password?")
3. Click **"▶️ Run Until Approval"**

**Result**: Execution runs and pauses at the approval node
- Thread ID is created: `thread-scenario-xxxxx`
- Current state is saved in SQLite checkpoint
- State shows pending approval decision

### Step 2: Simulate Network Failure

1. Click **"🌐 Simulate Network Failure"**
2. Close the app (or just wait)

**Behind the scenes**:
- Your state is persisted in `outputs/checkpoints.db`
- Thread ID: `thread-scenario-xxxxx` can be recovered anytime

### Step 3: Recover & Resume

1. Reopen the Streamlit app: `agent-lab hitl-demo`
2. Enable **"Recover from existing thread"** checkbox
3. Paste your thread ID: `thread-scenario-xxxxx`
4. Click **"▶️ Run Until Approval"** again

**Result**: 
- LangGraph loads the previous state from checkpoint
- Execution continues from the same point
- Approval decision is ready for your input

### Step 4: Make Approval Decision

In the **"Approval"** tab:
- View pending action and risk level
- Click **✅ Accept**, **❌ Reject**, or **🔄 Request Edit**

**Result**: State is updated, execution continues

---

## Technical Deep Dive

### How Persistence Works

**Thread-based Storage**:
```
outputs/
├── checkpoints.db (SQLite)
│   ├── thread-scenario-1 → full state with messages, events
│   ├── thread-scenario-2 → full state with messages, events
│   └── ...
```

Each `thread_id` stores:
- Complete `AgentState` (query, messages, events, etc.)
- All intermediate results
- Full audit trail

**Checkpoint Recovery**:
```python
graph.invoke(state, config={"configurable": {"thread_id": "thread-xxx"}})
```

LangGraph automatically:
1. Checks if checkpoint exists for thread_id
2. Loads previous state if found
3. Resumes execution from that point

### Interrupt Mechanism

The approval node uses LangGraph's `interrupt()`:

```python
def approval_node(state: AgentState) -> dict:
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt
        
        # Pauses here and waits for external input
        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
        })
        # Resumes when input is provided
        decision = ApprovalDecision(**value)
    else:
        decision = ApprovalDecision(approved=True)  # Mock mode
    
    return {"approval": decision.model_dump()}
```

### State Persistence Fields

All of these are persisted per thread:

| Field | Type | Purpose |
|-------|------|---------|
| `thread_id` | str | Unique session identifier |
| `scenario_id` | str | Which scenario is running |
| `query` | str | User input |
| `route` | str | Classified route (simple, tool, risky, etc.) |
| `messages` | list[str] | Append-only message log |
| `events` | list[dict] | Append-only audit events |
| `approval` | dict | Decision from approval node |
| `final_answer` | str | Generated response |

---

## Use Cases

### Use Case 1: Risky Actions (Finance, Refunds)

```
User: "Process a $1000 refund for order #12345"
         ↓
    [CLASSIFY] → Route: RISKY
         ↓
    [RISKY_ACTION] → Prepare action
         ↓
    [APPROVAL] ← INTERRUPT: Awaiting human decision
         ↓
    Human reviews: "Is this legitimate? Risk level: HIGH"
    Human clicks: ✅ APPROVE or ❌ REJECT
         ↓
    [TOOL] → Execute refund (if approved)
         ↓
    [ANSWER] → "Refund processed successfully"
```

### Use Case 2: Complex Queries (Missing Info)

```
User: "I'm having issues"
         ↓
    [CLASSIFY] → Route: MISSING_INFO
         ↓
    [CLARIFY] → "Can you provide more details?"
         ↓
    [FINALIZE] → Send clarification request
```

### Use Case 3: Tool Failures with Retry

```
User: "What's my order status?"
         ↓
    [TOOL] → External API call fails (transient error)
         ↓
    [EVALUATE] → "Needs retry"
         ↓
    [RETRY] → Attempt 2/3
         ↓
    [TOOL] → Success!
         ↓
    [ANSWER] → "Your order is shipped"
```

---

## Troubleshooting

### Issue: "interrupt() not triggered"

**Cause**: `LANGGRAPH_INTERRUPT` not set

**Solution**:
```bash
export LANGGRAPH_INTERRUPT=true
agent-lab hitl-demo
```

Or in Python:
```python
import os
os.environ["LANGGRAPH_INTERRUPT"] = "true"
```

### Issue: "Checkpoint not found"

**Cause**: Using different checkpointer or database

**Solution**:
- Check `configs/lab.yaml` matches checkpointer type
- For SQLite: ensure `outputs/checkpoints.db` exists
- For Postgres: verify connection string

```yaml
# configs/lab.yaml
checkpointer: sqlite  # or postgres
database_url: outputs/checkpoints.db
```

### Issue: "State not recovering"

**Cause**: Different thread_id or corrupted checkpoint

**Solution**:
```bash
# Reset checkpoints (deletes all history)
rm outputs/checkpoints.db

# Or inspect existing checkpoints
sqlite3 outputs/checkpoints.db "SELECT * FROM checkpoints LIMIT 5;"
```

### Issue: Streamlit app won't start

**Cause**: Missing streamlit

**Solution**:
```bash
pip install streamlit
```

---

## Advanced Configuration

### Change Checkpoint Backend

Edit `configs/lab.yaml`:

```yaml
# Memory (no persistence - debug only)
checkpointer: memory

# SQLite (file-based, default)
checkpointer: sqlite
database_url: outputs/checkpoints.db

# PostgreSQL (production-ready)
checkpointer: postgres
database_url: postgresql://user:password@localhost/agent_db
```

### Custom Approval Logic

Modify [src/langgraph_agent_lab/nodes.py](../src/langgraph_agent_lab/nodes.py):

```python
def approval_node(state: AgentState) -> dict:
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt
        
        # Customize what information is shown
        interrupt_data = {
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
            "attempt": state.get("attempt"),  # Add more context
            "previous_errors": state.get("errors", []),
        }
        
        value = interrupt(interrupt_data)
        decision = ApprovalDecision(**value)
    else:
        decision = ApprovalDecision(approved=True)
    
    return {"approval": decision.model_dump()}
```

### Monitor Checkpoint Size

```bash
# SQLite
sqlite3 outputs/checkpoints.db ".database"
sqlite3 outputs/checkpoints.db "SELECT COUNT(*) as thread_count FROM checkpoints;"

# PostgreSQL
psql postgresql://user:password@localhost/agent_db -c \
  "SELECT COUNT(*) as thread_count FROM checkpoints;"
```

---

## Testing

### Test Interrupt & Recovery

```bash
# Run tests that use sqlite checkpointer
pytest tests/ -v -k "test_graph" 

# Run with coverage
pytest tests/ --cov=src/langgraph_agent_lab --cov-report=html
```

### Manual Integration Test

```bash
# 1. Run scenarios (populates checkpoints)
agent-lab run-scenarios --config configs/lab.yaml --output outputs/metrics.json

# 2. Verify recovery capability
python -c "
from langgraph_agent_lab.persistence import build_checkpointer
import sqlite3

checkpointer = build_checkpointer('sqlite', 'outputs/checkpoints.db')
conn = sqlite3.connect('outputs/checkpoints.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM checkpoints')
count = cursor.fetchone()[0]
print(f'Stored checkpoints: {count}')
"

# 3. Launch demo
agent-lab hitl-demo
```

---

## References

- [LangGraph Interrupts](https://langchain-ai.github.io/langgraph/concepts/interrupts/)
- [LangGraph Persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [AgentState Schema](../src/langgraph_agent_lab/state.py)
- [Example Scenarios](../data/sample/scenarios.jsonl)

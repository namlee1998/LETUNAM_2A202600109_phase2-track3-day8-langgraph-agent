"""Streamlit HITL (Human-In-The-Loop) demo for LangGraph interruption and recovery.

This app demonstrates:
- Running the agent until an approval decision is needed (interrupt)
- Accepting or rejecting the approval
- Simulating network failure and resuming with the same thread_id
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import streamlit as st
import yaml
from langgraph.types import Command

try:
    from langgraph_agent_lab.graph import build_graph
    from langgraph_agent_lab.persistence import build_checkpointer
    from langgraph_agent_lab.scenarios import load_scenarios
    from langgraph_agent_lab.state import initial_state
except ImportError:  # pragma: no cover
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from langgraph_agent_lab.graph import build_graph
    from langgraph_agent_lab.persistence import build_checkpointer
    from langgraph_agent_lab.scenarios import load_scenarios
    from langgraph_agent_lab.state import initial_state


def get_config() -> dict:
    """Load configuration."""
    config_path = Path("configs/lab.yaml")
    if config_path.exists():
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return {
        "scenarios_path": "data/sample/scenarios.jsonl",
        "checkpointer": "sqlite",
        "database_url": "outputs/checkpoints.db",
    }


def setup_streamlit_config() -> None:
    """Configure Streamlit page settings."""
    st.set_page_config(
        page_title="LangGraph HITL Demo",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def init_session_state() -> None:
    """Initialize Streamlit session state."""
    if "config" not in st.session_state:
        st.session_state.config = get_config()
    if "scenarios" not in st.session_state:
        st.session_state.scenarios = load_scenarios(st.session_state.config["scenarios_path"])
    if "selected_scenario" not in st.session_state:
        st.session_state.selected_scenario = None
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    if "current_state" not in st.session_state:
        st.session_state.current_state = None
    if "execution_history" not in st.session_state:
        st.session_state.execution_history = []
    if "is_interrupted" not in st.session_state:
        st.session_state.is_interrupted = False
    if "interrupt_value" not in st.session_state:
        st.session_state.interrupt_value = None
    if "status_message" not in st.session_state:
        st.session_state.status_message = ""
    if "selected_scenario_id" not in st.session_state:
        st.session_state.selected_scenario_id = None


def get_graph_and_checkpointer() -> tuple:
    """Build graph and checkpointer."""
    os.environ["LANGGRAPH_INTERRUPT"] = "true"
    cfg = st.session_state.config
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)
    return graph, checkpointer


def merge_state(state: dict, patch: dict) -> None:
    """Merge a partial node result into current state."""
    for key, value in patch.items():
        if key == "__interrupt__":
            continue
        if isinstance(value, dict) and key not in state:
            # Flatten node output payloads into the top-level state.
            state.update(value)
            continue
        if isinstance(value, list) and isinstance(state.get(key), list):
            state[key].extend(value)
        else:
            state[key] = value


def stream_graph(graph: object, payload: dict, thread_id: str) -> dict:
    """Stream the graph until completion or interrupt, updating state in-place."""
    run_config = {"configurable": {"thread_id": thread_id}}
    state = payload.copy()
    st.session_state.is_interrupted = False
    st.session_state.interrupt_value = None
    st.session_state.status_message = ""

    for chunk in graph.stream(state, config=run_config):
        if "__interrupt__" in chunk:
            interrupt_data = chunk["__interrupt__"][0].value
            st.session_state.is_interrupted = True
            st.session_state.interrupt_value = interrupt_data
            st.session_state.status_message = "Paused at approval point"
            st.warning("⏸️ Execution interrupted at approval point")
            break
        merge_state(state, chunk)

    if not st.session_state.is_interrupted:
        st.session_state.status_message = "Execution completed"
    st.session_state.current_state = state
    return state


def resume_graph(graph: object, thread_id: str, decision: dict) -> dict:
    """Resume a previously interrupted graph using a human decision."""
    run_config = {"configurable": {"thread_id": thread_id}}
    state = {}
    command = Command(resume=decision)
    st.session_state.is_interrupted = False
    st.session_state.status_message = ""

    for chunk in graph.stream(command, config=run_config):
        if "__interrupt__" in chunk:
            interrupt_data = chunk["__interrupt__"][0].value
            st.session_state.is_interrupted = True
            st.session_state.interrupt_value = interrupt_data
            st.session_state.status_message = "Paused at approval point"
            st.warning("⏸️ Execution interrupted again")
            break
        merge_state(state, chunk)

    if not st.session_state.is_interrupted:
        st.session_state.interrupt_value = None
        st.session_state.status_message = "Execution completed after resume"
        st.success("✅ Execution completed after resume")

    st.session_state.current_state = state
    return state


def render_sidebar() -> str | None:
    """Render sidebar for scenario selection and controls."""
    with st.sidebar:
        st.title("🤖 HITL Controls")
        
        st.subheader("Scenario Selection")
        scenarios_list = st.session_state.scenarios
        scenario_names = [f"{s.id}: {s.query[:50]}" for s in scenarios_list]
        selected_idx = st.selectbox("Choose a scenario:", range(len(scenarios_list)), 
                                    format_func=lambda i: scenario_names[i])
        
        if selected_idx is not None and scenarios_list:
            return scenarios_list[selected_idx].id
    return None


def render_main_content() -> None:
    """Render main content area."""
    st.title("🤖 LangGraph HITL Demo")
    st.markdown("""
    This demo showcases:
    - **Human-In-The-Loop**: Approval decisions with interrupt()
    - **Persistence**: SQLite checkpoint recovery
    - **Interruption Simulation**: Simulate network failures and resume
    """)
    
    # Get selected scenario
    selected_scenario_id = render_sidebar()
    
    if not selected_scenario_id:
        st.info("👈 Select a scenario from the sidebar to start")
        return
    
    # Find scenario
    scenario = next((s for s in st.session_state.scenarios if s.id == selected_scenario_id), None)
    if not scenario:
        st.error("Scenario not found")
        return
    
    if st.session_state.selected_scenario_id != scenario.id:
        st.session_state.current_state = None
        st.session_state.is_interrupted = False
        st.session_state.interrupt_value = None
        st.session_state.status_message = ""
        st.session_state.thread_id = None
        st.session_state.selected_scenario_id = scenario.id
    
    # Display scenario info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Scenario", scenario.id)
    with col2:
        st.metric("Requires Approval", "Yes" if scenario.requires_approval else "No")
    with col3:
        st.metric("Expected Route", scenario.expected_route.value)
    
    st.divider()
    
    # Query display
    st.subheader("📝 User Query")
    st.info(scenario.query)
    
    # Thread ID section
    st.subheader("🔗 Session Management")
    col1, col2, col3 = st.columns(3)
    with col1:
        use_existing = st.checkbox("Recover from existing thread", value=False)

    recovery_thread_id = st.session_state.thread_id
    existing_thread = ""
    if use_existing:
        existing_thread = st.text_input(
            "Enter thread ID to recover:",
            value=st.session_state.thread_id or "",
            help="Type an existing thread_id to recover from an earlier run"
        )
        if existing_thread:
            recovery_thread_id = existing_thread.strip()

    if use_existing and not recovery_thread_id:
        st.warning("Enter an existing thread ID to recover from the previously paused run.")

    if recovery_thread_id and not recovery_thread_id.startswith(f"thread-{scenario.id}"):
        st.error(
            "The entered thread ID does not match the selected scenario. "
            "Choose the same scenario used to start the original run."
        )

    thread_id = recovery_thread_id or f"thread-{scenario.id}-{uuid.uuid4().hex[:8]}"

    if thread_id:
        st.caption(f"Thread ID: `{thread_id}`")
    
    # Execution controls
    st.subheader("⚙️ Execution Controls")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("▶️ Run Until Approval", use_container_width=True):
            st.session_state.thread_id = thread_id
            with st.spinner("Running agent..."):
                graph, _ = get_graph_and_checkpointer()
                state = initial_state(scenario)
                state["thread_id"] = thread_id

                st.session_state.execution_history.append({
                    "timestamp": "now",
                    "thread_id": thread_id,
                    "action": "run_until_approval",
                    "scenario_id": scenario.id,
                    "state": state.copy(),
                })

                state = stream_graph(graph, state, thread_id)
                st.session_state.current_state = state
                if not st.session_state.is_interrupted:
                    st.success("✅ Execution completed")
                else:
                    st.warning("⏸️ Execution paused at approval point")
    
    with col2:
        if st.button("🌐 Simulate Network Failure", use_container_width=True,
                     disabled=st.session_state.thread_id is None):
            st.warning(
                f"""🔌 **Network Failure Simulated**

                You can now close this app or wait. Your state is saved with thread_id:
                `{st.session_state.thread_id}`

                Click "Recover & Resume" to continue from where you left off."""
            )
    
    with col3:
        recover_disabled = not recovery_thread_id
        if st.button("🔄 Recover & Resume", use_container_width=True,
                     disabled=recover_disabled):
            st.session_state.thread_id = thread_id
            st.info(f"Attempting to recover from thread: `{thread_id}`")
            with st.spinner("Recovering agent state..."):
                graph, _ = get_graph_and_checkpointer()
                state = initial_state(scenario)
                state["thread_id"] = thread_id
                state = stream_graph(graph, state, thread_id)
                st.session_state.current_state = state

                st.session_state.execution_history.append({
                    "timestamp": "now",
                    "thread_id": thread_id,
                    "action": "recover_resume",
                    "scenario_id": scenario.id,
                    "state": state.copy(),
                    "was_interrupted": st.session_state.is_interrupted,
                })

                if not st.session_state.is_interrupted:
                    st.success("✅ State recovered and execution resumed")
                else:
                    st.warning("⏸️ Execution paused at approval point after recovery")
    
    if st.session_state.status_message:
        st.info(st.session_state.status_message)

    # Display current state
    if st.session_state.current_state:
        st.divider()
        st.subheader("📊 Current State")
        if st.session_state.is_interrupted:
            st.error("⚠️ Paused at approval point. Complete the approval decision below.")
        
        # Show state summary in tabs
        tab1, tab2, tab3, tab4 = st.tabs(["Summary", "Messages", "Approval", "Events"])
        
        with tab1:
            cols = st.columns(2)
            state = st.session_state.current_state
            with cols[0]:
                st.write(f"**Route:** {state.get('route', 'N/A')}")
                st.write(f"**Risk Level:** {state.get('risk_level', 'N/A')}")
                st.write(f"**Attempt:** {state.get('attempt', 0)}")
            with cols[1]:
                st.write(f"**Final Answer:** {state.get('final_answer', 'Pending')}")
                st.write(f"**Pending Question:** {state.get('pending_question', 'None')}")
        
        with tab2:
            if state.get("messages"):
                st.markdown("**Messages Log:**")
                for msg in state.get("messages", []):
                    st.text(msg)
            else:
                st.info("No messages yet")
        
        with tab3:
            approval = state.get("approval")
            interrupt_value = st.session_state.interrupt_value

            if approval:
                st.json(approval)
                st.success("Approval already recorded")
            elif interrupt_value:
                st.json(interrupt_value)
                st.subheader("Make Decision")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Accept", use_container_width=True):
                        decision = {
                            "approved": True,
                            "reviewer": "streamlit-user",
                            "comment": "accepted via UI",
                        }
                        graph, _ = get_graph_and_checkpointer()
                        state = resume_graph(graph, thread_id, decision)
                        st.session_state.execution_history.append({
                            "timestamp": "now",
                            "thread_id": thread_id,
                            "action": "approve",
                            "scenario_id": scenario.id,
                            "decision": decision,
                            "state": state.copy(),
                        })
                with col2:
                    if st.button("❌ Reject", use_container_width=True):
                        decision = {
                            "approved": False,
                            "reviewer": "streamlit-user",
                            "comment": "rejected via UI",
                        }
                        graph, _ = get_graph_and_checkpointer()
                        state = resume_graph(graph, thread_id, decision)
                        st.session_state.execution_history.append({
                            "timestamp": "now",
                            "thread_id": thread_id,
                            "action": "reject",
                            "scenario_id": scenario.id,
                            "decision": decision,
                            "state": state.copy(),
                        })
                with col3:
                    if st.button("🔄 Request Edit", use_container_width=True):
                        decision = {
                            "approved": False,
                            "reviewer": "streamlit-user",
                            "comment": "request edit via UI",
                        }
                        graph, _ = get_graph_and_checkpointer()
                        state = resume_graph(graph, thread_id, decision)
                        st.session_state.execution_history.append({
                            "timestamp": "now",
                            "thread_id": thread_id,
                            "action": "request_edit",
                            "scenario_id": scenario.id,
                            "decision": decision,
                            "state": state.copy(),
                        })
            else:
                st.info("No approval pending")
        
        with tab4:
            if state.get("events"):
                st.markdown("**Event Log:**")
                for event in state.get("events", []):
                    st.json(event)
            else:
                st.info("No events yet")
    
    # Execution history
    st.divider()
    st.subheader("📜 Execution History")
    if st.session_state.execution_history:
        for i, entry in enumerate(st.session_state.execution_history, 1):
            with st.expander(f"Execution {i}: {entry.get('action', 'unknown')}"):
                st.json(entry)
    else:
        st.info("No execution history yet")


def main() -> None:
    """Main app entry point."""
    setup_streamlit_config()
    init_session_state()
    render_main_content()


if __name__ == "__main__":
    main()

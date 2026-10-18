from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from database.db_manager import DBManager
from src.action_engine import dispatch_action
from src.ai_agent import generate_insight_and_action

load_dotenv()
st.set_page_config(page_title="QueryFlow AI", layout="wide")


def _render_mode_badge(mode: str) -> None:
    color = "#2e7d32" if mode == "sqlite" else "#1565c0"
    label = "SQLite Local Mode" if mode == "sqlite" else "MySQL Live Mode"
    st.markdown(
        f"<div style='padding:8px 12px;border-radius:8px;background:{color};color:white;font-weight:600'>{label}</div>",
        unsafe_allow_html=True,
    )


def _safe_to_json(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, ensure_ascii=False)


def _render_chart(df: pd.DataFrame, config: dict[str, Any]) -> None:
    chart_type = config.get("chart_type", "none")
    x_col = config.get("x_column", "")
    y_col = config.get("y_column", "")
    title = config.get("title", "Generated Chart")

    if chart_type == "none" or df.empty:
        st.info("No chart suggested for this response.")
        return

    if x_col not in df.columns or y_col not in df.columns:
        st.warning("Chart skipped: suggested columns are not present in the query output.")
        return

    fig = None
    if chart_type == "bar":
        fig = px.bar(df, x=x_col, y=y_col, title=title)
    elif chart_type == "line":
        fig = px.line(df, x=x_col, y=y_col, title=title)
    elif chart_type == "pie":
        fig = px.pie(df, names=x_col, values=y_col, title=title)
    elif chart_type == "scatter":
        fig = px.scatter(df, x=x_col, y=y_col, title=title)

    if fig is None:
        st.warning("Unsupported chart type from AI response.")
    else:
        st.plotly_chart(fig, use_container_width=True)


def _query_and_cache(prompt: str, manager: DBManager) -> None:
    schema_context = manager.get_schema_context()
    result = generate_insight_and_action(prompt, schema_context, manager.execute_read_query)
    st.session_state.last_result = result
    st.session_state.last_prompt = prompt
    st.session_state.editable_payload = result.get("recommended_action", {}).get("payload_preview", "")

    manager.log_audit_event(
        user_query=prompt,
        generated_sql=result.get("sql_query"),
        action_taken="",
        status="query_success" if not result.get("query_error") else "query_failed",
    )


def main() -> None:
    st.title("QueryFlow AI")
    st.caption("Autonomous Text-to-SQL Analytics & Operations Execution Agent for SMEs")

    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "last_prompt" not in st.session_state:
        st.session_state.last_prompt = ""
    if "editable_payload" not in st.session_state:
        st.session_state.editable_payload = ""

    manager = DBManager()

    with st.sidebar:
        st.subheader("Connection")
        _render_mode_badge(manager.mode)

        st.subheader("Live Schema Inspector")
        with st.expander("View schema context", expanded=False):
            st.code(manager.get_schema_context(), language="sql")

        st.subheader("1-Click Demo Prompts")
        demo_prompts = [
            "Which products are below reorder level right now, who is their supplier, and how much revenue have they generated?",
            "Show category-wise revenue breakdown over the last 30 days and highlight the lowest performing category.",
            "Enna products stock romba kammiya iruku? Show supplier contact details for immediate restock.",
        ]
        for idx, prompt in enumerate(demo_prompts, start=1):
            if st.button(f"Demo {idx}", use_container_width=True):
                _query_and_cache(prompt, manager)

    kpis = manager.get_kpi_snapshot()
    kpi_cols = st.columns(4)
    kpi_cols[0].metric("Total Revenue", f"₹{kpis['total_revenue']:,.0f}")
    kpi_cols[1].metric("Active Products", f"{kpis['active_products']}")
    kpi_cols[2].metric("Low-Stock Alerts", f"{kpis['low_stock_alerts']}")
    kpi_cols[3].metric("Automated Actions Executed", f"{kpis['actions_executed']}")

    workspace_tab, audit_tab = st.tabs(["Query Workspace", "Audit Logs"])

    with workspace_tab:
        prompt = st.text_input(
            "Ask in English or Tanglish",
            value=st.session_state.last_prompt,
            placeholder="e.g. Enna products stock kammiya iruku and high sales la poguthu?",
        )
        if st.button("Run Query", type="primary") and prompt.strip():
            _query_and_cache(prompt.strip(), manager)

        result = st.session_state.last_result
        if result:
            df = result.get("result_df", pd.DataFrame())
            left, right = st.columns([1.3, 1])

            with left:
                st.subheader("Executive Summary")
                st.write(result.get("insight_summary", "No insight available"))
                _render_chart(df, result.get("chart_config", {}))
                with st.expander("Raw DataFrame", expanded=False):
                    st.dataframe(df, use_container_width=True)

            with right:
                with st.expander("Under the Hood", expanded=True):
                    sql_query = result.get("sql_query", "")
                    st.code(sql_query, language="sql")
                    safety = manager.is_safe_sql(sql_query)
                    st.success("SQL Safety: PASS") if safety else st.error("SQL Safety: FAIL")
                    st.write(f"Self-heal retries: {result.get('retry_count', 0)}")
                    st.json(result.get("healing_log", []))
                    if result.get("query_error"):
                        st.error(result["query_error"])

                st.subheader("Autonomous Action Card")
                action_data = result.get("recommended_action", {})
                st.write(action_data.get("action_title", "Recommended Action"))
                edited_payload = st.text_area(
                    "Editable Payload",
                    value=st.session_state.editable_payload or action_data.get("payload_preview", ""),
                    height=180,
                    key="editable_payload_area",
                )
                st.session_state.editable_payload = edited_payload

                if st.button("⚡ Execute Action Now", use_container_width=True):
                    dispatch_input = dict(action_data)
                    dispatch_input["payload_preview"] = edited_payload
                    receipt = dispatch_action(
                        dispatch_input,
                        df,
                        user_query=st.session_state.last_prompt,
                        generated_sql=result.get("sql_query"),
                    )
                    st.toast(f"Action executed ({receipt['mode']} mode): {receipt['dispatch_status']}")
                    st.code(_safe_to_json(receipt), language="json")

    with audit_tab:
        st.subheader("Live audit_logs")
        audit_df = manager.get_audit_logs(limit=200)
        st.dataframe(audit_df, use_container_width=True, height=320)

    st.subheader("Recent Audit Trail")
    st.dataframe(manager.get_audit_logs(limit=30), use_container_width=True, height=220)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
except Exception:  # noqa: BLE001
    genai = None


@dataclass(slots=True)
class AgentOutput:
    thought_process: str
    sql_query: str
    insight_summary: str
    chart_config: dict[str, Any]
    recommended_action: dict[str, Any]
    retry_count: int
    healing_log: list[str]
    query_error: str | None
    result_df: Any


SYSTEM_PROMPT = """
You are QueryFlow AI, a reliable analytics copilot for Indian SME operations teams.
Understand English and Tanglish phrasing (example: "Enna products stock kammiya iruku and high sales la poguthu?").
Generate one safe read-only SQL query only.

Rules:
- Use only columns/tables from the schema context.
- SQL must start with SELECT or WITH.
- No mutation SQL.
- Output strict JSON only (no markdown) with keys:
  thought_process, sql_query, insight_summary, chart_config, recommended_action
- chart_config keys: chart_type, x_column, y_column, title
- recommended_action keys: should_trigger, action_type, target_recipient, action_title, payload_preview
""".strip()


DEFAULT_RESPONSE = {
    "thought_process": "Analyzed inventory and sales patterns with safe joins.",
    "sql_query": (
        "SELECT p.product_name, p.stock_quantity, p.reorder_level, "
        "COALESCE(SUM(s.total_amount_inr), 0) AS revenue_30d "
        "FROM products p "
        "LEFT JOIN sales_orders s ON p.product_id = s.product_id "
        "AND s.order_date >= date('now', '-30 day') "
        "GROUP BY p.product_id, p.product_name, p.stock_quantity, p.reorder_level "
        "ORDER BY revenue_30d DESC"
    ),
    "insight_summary": "Showing top products by recent revenue with stock posture.",
    "chart_config": {
        "chart_type": "bar",
        "x_column": "product_name",
        "y_column": "revenue_30d",
        "title": "Revenue by Product (Last 30 Days)",
    },
    "recommended_action": {
        "should_trigger": True,
        "action_type": "TELEGRAM_ALERT",
        "target_recipient": "Ops Channel",
        "action_title": "Send stock-risk update",
        "payload_preview": "Share high revenue items with low stock risk for immediate follow-up.",
    },
}


def _strip_json(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.S)
    if raw_text.startswith("{") and raw_text.endswith("}"):
        return json.loads(raw_text)
    match = re.search(r"\{.*\}", raw_text, flags=re.S)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No valid JSON found in model response")


def _fallback_plan(user_prompt: str) -> dict[str, Any]:
    lowered = user_prompt.lower()
    if "category" in lowered and "revenue" in lowered:
        return {
            "thought_process": "Aggregated category revenue for recent period.",
            "sql_query": (
                "SELECT p.category, ROUND(SUM(s.total_amount_inr), 2) AS category_revenue "
                "FROM sales_orders s "
                "JOIN products p ON p.product_id = s.product_id "
                "WHERE s.order_date >= date('now', '-30 day') "
                "GROUP BY p.category "
                "ORDER BY category_revenue DESC"
            ),
            "insight_summary": "Category-wise revenue trend for the last 30 days.",
            "chart_config": {
                "chart_type": "pie",
                "x_column": "category",
                "y_column": "category_revenue",
                "title": "Category Revenue Mix (30 Days)",
            },
            "recommended_action": {
                "should_trigger": True,
                "action_type": "EXPORT_REPORT",
                "target_recipient": "Ops Team",
                "action_title": "Export category performance report",
                "payload_preview": "Category performance extracted for strategy review.",
            },
        }

    if any(term in lowered for term in ["stock", "kammi", "reorder", "restock"]):
        return {
            "thought_process": "Joined products with suppliers and sales to find low-stock high-demand items.",
            "sql_query": (
                "SELECT p.product_name, p.stock_quantity, p.reorder_level, sp.supplier_name, sp.contact_email, "
                "ROUND(COALESCE(SUM(s.total_amount_inr),0),2) AS revenue_30d "
                "FROM products p "
                "JOIN suppliers sp ON sp.supplier_id = p.supplier_id "
                "LEFT JOIN sales_orders s ON s.product_id = p.product_id "
                "AND s.order_date >= date('now', '-30 day') "
                "WHERE p.stock_quantity < p.reorder_level "
                "GROUP BY p.product_id, p.product_name, p.stock_quantity, p.reorder_level, sp.supplier_name, sp.contact_email "
                "ORDER BY revenue_30d DESC"
            ),
            "insight_summary": "Low-stock products with supplier contacts prioritized by 30-day revenue.",
            "chart_config": {
                "chart_type": "bar",
                "x_column": "product_name",
                "y_column": "revenue_30d",
                "title": "Low Stock Revenue Risk",
            },
            "recommended_action": {
                "should_trigger": True,
                "action_type": "RESTOCK_PO_EMAIL",
                "target_recipient": "Supplier email",
                "action_title": "Send urgent restock request",
                "payload_preview": "Request urgent replenishment for top low-stock revenue products.",
            },
        }

    return dict(DEFAULT_RESPONSE)


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(DEFAULT_RESPONSE)
    normalized.update({k: v for k, v in payload.items() if k in normalized})

    chart = normalized.get("chart_config") if isinstance(normalized.get("chart_config"), dict) else {}
    normalized["chart_config"] = {
        "chart_type": str(chart.get("chart_type", "none")).lower(),
        "x_column": str(chart.get("x_column", "")),
        "y_column": str(chart.get("y_column", "")),
        "title": str(chart.get("title", "QueryFlow Chart")),
    }

    action = normalized.get("recommended_action") if isinstance(normalized.get("recommended_action"), dict) else {}
    normalized["recommended_action"] = {
        "should_trigger": bool(action.get("should_trigger", False)),
        "action_type": str(action.get("action_type", "EXPORT_REPORT")),
        "target_recipient": str(action.get("target_recipient", "Ops Team")),
        "action_title": str(action.get("action_title", "Execute recommended action")),
        "payload_preview": str(action.get("payload_preview", "")),
    }
    normalized["sql_query"] = str(normalized.get("sql_query", "")).strip()
    normalized["thought_process"] = str(normalized.get("thought_process", "")).strip()
    normalized["insight_summary"] = str(normalized.get("insight_summary", "")).strip()
    return normalized


def _model_json(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or genai is None:
        raise RuntimeError("Gemini unavailable")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    text = getattr(response, "text", "") or ""
    if not text and getattr(response, "candidates", None):
        parts = response.candidates[0].content.parts
        text = "".join(getattr(p, "text", "") for p in parts)
    return _strip_json(text)


def _ask_model(user_prompt: str, schema_context: str, correction: str | None = None) -> dict[str, Any]:
    correction_block = f"\nFix this SQL using DB error:\n{correction}\n" if correction else ""
    prompt = (
        f"{SYSTEM_PROMPT}\n\nSCHEMA CONTEXT:\n{schema_context}\n\n"
        f"USER QUESTION:\n{user_prompt}\n"
        f"{correction_block}\n"
        "Return strict JSON now."
    )
    try:
        return _normalize(_model_json(prompt))
    except Exception:  # noqa: BLE001
        fallback = _fallback_plan(user_prompt)
        if correction:
            error_lower = correction.lower()
            if "date(" in fallback["sql_query"] and any(token in error_lower for token in ["mysql", "syntax", "date_sub"]):
                fallback["sql_query"] = fallback["sql_query"].replace(
                    "date('now', '-30 day')",
                    "DATE_SUB(CURDATE(), INTERVAL 30 DAY)",
                )
        return _normalize(fallback)


def generate_insight_and_action(
    user_prompt: str,
    schema_context: str,
    db_execute_fn: Callable[[str], tuple[Any, str | None]],
) -> dict[str, Any]:
    attempt = 0
    healing_log: list[str] = []
    correction_note: str | None = None
    payload = _ask_model(user_prompt, schema_context)

    while attempt <= 2:
        sql_query = payload.get("sql_query", "")
        df, error = db_execute_fn(sql_query)
        if not error:
            payload["retry_count"] = attempt
            payload["healing_log"] = healing_log
            payload["query_error"] = None
            payload["result_df"] = df
            return payload

        if attempt == 2:
            payload["retry_count"] = attempt
            payload["healing_log"] = healing_log
            payload["query_error"] = error
            payload["result_df"] = df
            return payload

        attempt += 1
        correction_note = f"Broken SQL: {sql_query}\nDB Error: {error}"
        healing_log.append(f"Retry {attempt}: {error}")
        payload = _ask_model(user_prompt, schema_context, correction_note)

    payload["retry_count"] = attempt
    payload["healing_log"] = healing_log
    payload["query_error"] = "Unable to produce valid SQL"
    payload["result_df"] = None
    return payload

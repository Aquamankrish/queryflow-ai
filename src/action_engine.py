from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from database.db_manager import DBManager

load_dotenv()


def _enrich_payload(payload_preview: str, query_df: pd.DataFrame) -> str:
    if query_df is None or query_df.empty:
        return payload_preview
    preview_rows = query_df.head(5).to_dict(orient="records")
    summary = json.dumps(preview_rows, ensure_ascii=False)
    return f"{payload_preview}\n\nTop query rows:\n{summary}"


def _send_email(subject: str, body: str, recipient: str) -> tuple[str, int | None, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_SENDER", user).strip()

    if not (host and user and password and sender and recipient):
        return "simulated", None, "SMTP credentials missing; simulated dispatch"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(sender, [recipient], msg.as_string())
        return "real", 250, "Email sent"
    except Exception as exc:  # noqa: BLE001
        return "simulated", None, f"Email failed; simulated fallback used: {exc}"


def dispatch_action(
    action_data: dict[str, Any],
    query_df: pd.DataFrame,
    user_query: str | None = None,
    generated_sql: str | None = None,
) -> dict[str, Any]:
    manager = DBManager()
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    action_type = str(action_data.get("action_type", "EXPORT_REPORT"))
    target = str(action_data.get("target_recipient", "Ops Team"))
    title = str(action_data.get("action_title", "Execute QueryFlow Action"))
    payload_preview = str(action_data.get("payload_preview", ""))

    enriched_payload = _enrich_payload(payload_preview, query_df)
    statuses: dict[str, Any] = {}
    simulated = True
    attempts = 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id and action_type in {"TELEGRAM_ALERT", "EXPORT_REPORT"}:
        attempts += 1
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"{title}\n\n{enriched_payload}"},
                timeout=15,
            )
            statuses["telegram_status"] = response.status_code
            simulated = simulated and response.status_code >= 400
        except Exception as exc:  # noqa: BLE001
            statuses["telegram_status"] = f"error: {exc}"

    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    if webhook_url:
        attempts += 1
        try:
            response = requests.post(
                webhook_url,
                json={
                    "timestamp": now,
                    "action_type": action_type,
                    "title": title,
                    "recipient": target,
                    "payload": enriched_payload,
                },
                timeout=15,
            )
            statuses["webhook_status"] = response.status_code
            simulated = simulated and response.status_code >= 400
        except Exception as exc:  # noqa: BLE001
            statuses["webhook_status"] = f"error: {exc}"

    mode, smtp_status, smtp_message = _send_email(title, enriched_payload, target)
    statuses["smtp_status"] = smtp_status
    statuses["smtp_message"] = smtp_message
    if mode == "real":
        attempts += 1
        simulated = False

    if not statuses:
        statuses = {"dispatch": "simulated-no-integrations"}

    any_success = any(isinstance(v, int) and v < 400 for v in statuses.values() if v is not None)
    dispatch_status = "success" if any_success or attempts == 0 or simulated else "failed"

    receipt = {
        "timestamp": now,
        "action_type": action_type,
        "target_recipient": target,
        "dispatch_status": dispatch_status,
        "http_statuses": statuses,
        "mode": "simulated" if simulated else "real",
        "payload": enriched_payload,
    }

    manager.log_audit_event(
        user_query=user_query,
        generated_sql=generated_sql,
        action_taken=json.dumps(receipt, ensure_ascii=False),
        status=dispatch_status,
    )
    return receipt

# QueryFlow AI

QueryFlow AI is a production-ready hackathon MVP that turns natural language (English + Tanglish) into safe SQL analytics and optional one-click operational actions.

## Features
- Streamlit wide-layout dashboard with KPIs, tabs, session state, schema inspector, demo prompts, SQL debugger, action card, and live audit logs.
- Dual database mode:
  - **Zero-config SQLite** (default): auto-creates `queryflow_sme.db` with seeded SME demo data.
  - **Optional MySQL** via `.env` credentials.
- AI agent:
  - Gemini (`gemini-2.5-flash`) when `GEMINI_API_KEY` is configured.
  - Deterministic local fallback mode when key is missing.
  - Strict JSON output normalization and SQL self-healing retries.
- Autonomous action engine with Telegram, webhook, SMTP email, and safe simulated fallback.

## Project Structure
- `.env.example`
- `requirements.txt`
- `README.md`
- `database/db_manager.py`
- `src/ai_agent.py`
- `src/action_engine.py`
- `app.py`

## Quick Start (Zero-Config SQLite)
1. Use Python 3.11+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy environment file:
   ```bash
   cp .env.example .env
   ```
4. Run app:
   ```bash
   streamlit run app.py
   ```

On first run, the app creates and seeds:
- `suppliers`
- `products`
- `sales_orders`
- `audit_logs`

## Optional Integrations
### Gemini
Set `GEMINI_API_KEY` in `.env` to enable live LLM generation.

### MySQL Live Mode
Set:
- `USE_MYSQL=true`
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`

If MySQL is unavailable, app falls back to SQLite automatically.

### Telegram / Webhook / SMTP
Configure these to enable real action dispatch:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `WEBHOOK_URL`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SENDER`

Without credentials, dispatch runs in simulated-safe mode.

## Security Guardrails
- SQL safety allows **SELECT/WITH only**.
- Rejects comments, multiple statements, and mutation keywords (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `GRANT`, etc.).
- Query executions and actions are logged in `audit_logs`.

## Sample Prompts
- Which products are below reorder level right now, who is their supplier, and how much revenue have they generated?
- Show category-wise revenue breakdown over the last 30 days and highlight the lowest performing category.
- Enna products stock romba kammiya iruku? Show supplier contact details for immediate restock.

## Limitations
- LLM output quality depends on model availability and prompt understanding.
- Fallback mode is deterministic and optimized for demo reliability, not open-ended reasoning.
- Action dispatches are best-effort and rely on external service uptime.

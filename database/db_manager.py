from __future__ import annotations

import os
import random
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Generator

import pandas as pd
from dotenv import load_dotenv

try:
    import mysql.connector as mysql_connector
except Exception:  # noqa: BLE001
    mysql_connector = None

load_dotenv()


@dataclass(slots=True)
class DBConfig:
    use_mysql: bool
    sqlite_path: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str


class DBManager:
    """Database manager supporting local SQLite and optional MySQL."""

    def __init__(self) -> None:
        self.config = DBConfig(
            use_mysql=os.getenv("USE_MYSQL", "false").strip().lower() == "true",
            sqlite_path=os.getenv("SQLITE_DB_PATH", "queryflow_sme.db"),
            mysql_host=os.getenv("MYSQL_HOST", "localhost"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_user=os.getenv("MYSQL_USER", "root"),
            mysql_password=os.getenv("MYSQL_PASSWORD", ""),
            mysql_database=os.getenv("MYSQL_DATABASE", "queryflow_sme"),
        )
        self._mode = "mysql" if self.config.use_mysql else "sqlite"
        self._ensure_database_ready()

    @property
    def mode(self) -> str:
        return self._mode

    def mode_label(self) -> str:
        return "MySQL Live Mode" if self.mode == "mysql" else "SQLite Local Mode"

    @contextmanager
    def _connection(self) -> Generator[Any, None, None]:
        if self.mode == "mysql":
            if mysql_connector is None:
                raise RuntimeError("mysql-connector-python is not installed")
            conn = mysql_connector.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                passwd=self.config.mysql_password,
                database=self.config.mysql_database,
                autocommit=False,
            )
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self.config.sqlite_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _ensure_database_ready(self) -> None:
        try:
            with self._connection() as conn:
                self._create_tables(conn)
                self._seed_if_empty(conn)
        except Exception:
            if self.mode == "mysql":
                self._mode = "sqlite"
                with self._connection() as conn:
                    self._create_tables(conn)
                    self._seed_if_empty(conn)

    def _create_tables(self, conn: Any) -> None:
        cursor = conn.cursor()
        if self.mode == "mysql":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS suppliers (
                    supplier_id INT PRIMARY KEY,
                    supplier_name VARCHAR(120) NOT NULL,
                    contact_email VARCHAR(150) NOT NULL,
                    phone VARCHAR(30) NOT NULL,
                    city VARCHAR(80) NOT NULL,
                    lead_time_days INT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id INT PRIMARY KEY,
                    product_name VARCHAR(120) NOT NULL,
                    category VARCHAR(80) NOT NULL,
                    unit_price_inr DECIMAL(10,2) NOT NULL,
                    stock_quantity INT NOT NULL,
                    reorder_level INT NOT NULL,
                    supplier_id INT NOT NULL,
                    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sales_orders (
                    order_id INT PRIMARY KEY,
                    product_id INT NOT NULL,
                    quantity_sold INT NOT NULL,
                    total_amount_inr DECIMAL(12,2) NOT NULL,
                    order_date DATE NOT NULL,
                    customer_region VARCHAR(80) NOT NULL,
                    payment_status VARCHAR(30) NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp DATETIME NOT NULL,
                    user_query TEXT,
                    generated_sql TEXT,
                    action_taken TEXT,
                    status VARCHAR(60) NOT NULL
                )
                """
            )
        else:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS suppliers (
                    supplier_id INTEGER PRIMARY KEY,
                    supplier_name TEXT NOT NULL,
                    contact_email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    city TEXT NOT NULL,
                    lead_time_days INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id INTEGER PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    unit_price_inr REAL NOT NULL,
                    stock_quantity INTEGER NOT NULL,
                    reorder_level INTEGER NOT NULL,
                    supplier_id INTEGER NOT NULL,
                    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sales_orders (
                    order_id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    quantity_sold INTEGER NOT NULL,
                    total_amount_inr REAL NOT NULL,
                    order_date TEXT NOT NULL,
                    customer_region TEXT NOT NULL,
                    payment_status TEXT NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_query TEXT,
                    generated_sql TEXT,
                    action_taken TEXT,
                    status TEXT NOT NULL
                )
                """
            )

    def _seed_if_empty(self, conn: Any) -> None:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM suppliers")
        count = cursor.fetchone()[0]
        if count:
            return

        suppliers = [
            (1, "Apex Electronics", "ops@apexelectronics.in", "+91-9840011122", "Chennai", 4),
            (2, "GreenLeaf Grocers Supply", "support@greenleafsupply.in", "+91-9845022233", "Bengaluru", 3),
            (3, "Western Components Hub", "sales@westerncomponents.in", "+91-9820013344", "Mumbai", 5),
            (4, "Delta Packaging Works", "service@deltapackaging.in", "+91-9900014455", "Hyderabad", 6),
            (5, "NorthStar Essentials", "hello@northstaressentials.in", "+91-9810015566", "Delhi", 7),
            (6, "Coastal Fresh Distributors", "contact@coastalfresh.in", "+91-9444016677", "Kochi", 4),
        ]

        products = [
            (1, "Millet Health Mix", "Groceries", 240.0, 18, 30, 2),
            (2, "Organic Turmeric Powder", "Groceries", 130.0, 42, 35, 2),
            (3, "Bluetooth Barcode Scanner", "Electronics", 2200.0, 9, 20, 1),
            (4, "POS Receipt Roll Pack", "Operations", 320.0, 27, 25, 4),
            (5, "Cold Pressed Groundnut Oil", "Groceries", 410.0, 11, 22, 6),
            (6, "Smart Shelf Label", "Electronics", 950.0, 31, 18, 3),
            (7, "Reusable Carry Bag", "Operations", 25.0, 160, 120, 4),
            (8, "Retail Billing Tablet", "Electronics", 14500.0, 6, 12, 1),
            (9, "Instant Filter Coffee Mix", "Beverages", 180.0, 55, 30, 6),
            (10, "Dry Fruit Combo Box", "Snacks", 560.0, 14, 24, 5),
            (11, "Ready Idli Batter 1kg", "Fresh", 75.0, 19, 28, 6),
            (12, "Eco Cleaner Refill", "Home Care", 210.0, 24, 20, 5),
            (13, "LED Signage Strip", "Electronics", 780.0, 15, 15, 3),
            (14, "Sugar-Free Biscuit Pack", "Snacks", 65.0, 33, 26, 5),
            (15, "Premium Basmati Rice 5kg", "Groceries", 690.0, 8, 16, 2),
        ]

        sales_orders: list[tuple[Any, ...]] = []
        random.seed(42)
        regions = ["Chennai", "Coimbatore", "Bengaluru", "Mumbai", "Pune", "Hyderabad", "Delhi", "Kochi"]
        payment_statuses = ["PAID", "PAID", "PAID", "PENDING"]

        for order_id in range(1, 61):
            product = products[(order_id * 7) % len(products)]
            product_id = product[0]
            qty = random.randint(1, 12)
            total = Decimal(str(product[3])) * qty
            order_dt = date.today() - timedelta(days=random.randint(0, 29))
            sales_orders.append(
                (
                    order_id,
                    product_id,
                    qty,
                    float(total),
                    order_dt.isoformat(),
                    random.choice(regions),
                    random.choice(payment_statuses),
                )
            )

        self._bulk_insert(
            conn,
            "suppliers",
            ["supplier_id", "supplier_name", "contact_email", "phone", "city", "lead_time_days"],
            suppliers,
        )
        self._bulk_insert(
            conn,
            "products",
            [
                "product_id",
                "product_name",
                "category",
                "unit_price_inr",
                "stock_quantity",
                "reorder_level",
                "supplier_id",
            ],
            products,
        )
        self._bulk_insert(
            conn,
            "sales_orders",
            [
                "order_id",
                "product_id",
                "quantity_sold",
                "total_amount_inr",
                "order_date",
                "customer_region",
                "payment_status",
            ],
            sales_orders,
        )

    def _bulk_insert(self, conn: Any, table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        cursor = conn.cursor()
        if self.mode == "mysql":
            placeholders = ", ".join(["%s"] * len(columns))
        else:
            placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        cursor.executemany(f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})", rows)

    def get_schema_context(self) -> str:
        with self._connection() as conn:
            if self.mode == "mysql":
                tables_df = pd.read_sql("SHOW TABLES", conn)
                table_names = tables_df.iloc[:, 0].tolist()
            else:
                table_names = pd.read_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
                    conn,
                )["name"].tolist()

            sections: list[str] = []
            for table in table_names:
                if self.mode == "mysql":
                    cols = pd.read_sql(f"SHOW COLUMNS FROM {table}", conn)
                    columns = [f"{row['Field']} {row['Type']}" for _, row in cols.iterrows()]
                    fk_df = pd.read_sql(
                        (
                            "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                            "FROM information_schema.KEY_COLUMN_USAGE "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL"
                        ),
                        conn,
                        params=[self.config.mysql_database, table],
                    )
                    fk_lines = [
                        f"{row['COLUMN_NAME']} -> {row['REFERENCED_TABLE_NAME']}.{row['REFERENCED_COLUMN_NAME']}"
                        for _, row in fk_df.iterrows()
                    ]
                else:
                    cols = pd.read_sql(f"PRAGMA table_info({table})", conn)
                    columns = [f"{row['name']} {row['type']}" for _, row in cols.iterrows()]
                    fk_df = pd.read_sql(f"PRAGMA foreign_key_list({table})", conn)
                    fk_lines = [f"{row['from']} -> {row['table']}.{row['to']}" for _, row in fk_df.iterrows()]

                sample_df = pd.read_sql(f"SELECT * FROM {table} LIMIT 3", conn)
                samples = sample_df.to_dict(orient="records")
                sections.append(
                    "\n".join(
                        [
                            f"TABLE: {table}",
                            "COLUMNS:",
                            *[f"- {c}" for c in columns],
                            "FOREIGN_KEYS:",
                            *([f"- {f}" for f in fk_lines] or ["- none"]),
                            "SAMPLE_ROWS:",
                            *[f"- {row}" for row in samples],
                        ]
                    )
                )
            return "\n\n".join(sections)

    def is_safe_sql(self, sql_string: str) -> bool:
        if not sql_string or not sql_string.strip():
            return False
        sql = sql_string.strip()

        if "--" in sql or "/*" in sql or "*/" in sql or "#" in sql:
            return False

        normalized = re.sub(r"\s+", " ", sql).strip().lower()
        if ";" in normalized.rstrip(";"):
            return False
        if normalized.endswith(";"):
            normalized = normalized[:-1].strip()

        if not (normalized.startswith("select") or normalized.startswith("with")):
            return False

        blocked = {
            "drop",
            "delete",
            "update",
            "insert",
            "alter",
            "truncate",
            "grant",
            "revoke",
            "create",
            "replace",
            "merge",
            "call",
            "execute",
        }
        tokenized = set(re.findall(r"\b[a-z_]+\b", normalized))
        if blocked.intersection(tokenized):
            return False

        return True

    def execute_read_query(self, sql_string: str) -> tuple[pd.DataFrame, str | None]:
        if not self.is_safe_sql(sql_string):
            return pd.DataFrame(), "Rejected by SQL safety guardrail"
        try:
            with self._connection() as conn:
                df = pd.read_sql(sql_string, conn)
            return df, None
        except Exception as exc:  # noqa: BLE001
            return pd.DataFrame(), str(exc)

    def get_kpi_snapshot(self) -> dict[str, float | int]:
        with self._connection() as conn:
            total_revenue = pd.read_sql("SELECT COALESCE(SUM(total_amount_inr),0) AS value FROM sales_orders", conn)["value"][0]
            active_products = pd.read_sql("SELECT COUNT(*) AS value FROM products", conn)["value"][0]
            low_stock = pd.read_sql("SELECT COUNT(*) AS value FROM products WHERE stock_quantity < reorder_level", conn)["value"][0]
            actions = pd.read_sql(
                "SELECT COUNT(*) AS value FROM audit_logs WHERE action_taken IS NOT NULL AND action_taken <> ''",
                conn,
            )["value"][0]
        return {
            "total_revenue": float(total_revenue or 0),
            "active_products": int(active_products or 0),
            "low_stock_alerts": int(low_stock or 0),
            "actions_executed": int(actions or 0),
        }

    def log_audit_event(
        self,
        user_query: str | None,
        generated_sql: str | None,
        action_taken: str | None,
        status: str,
    ) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            if self.mode == "mysql":
                cursor.execute(
                    "INSERT INTO audit_logs (timestamp, user_query, generated_sql, action_taken, status) VALUES (NOW(), %s, %s, %s, %s)",
                    (user_query, generated_sql, action_taken, status),
                )
            else:
                cursor.execute(
                    "INSERT INTO audit_logs (timestamp, user_query, generated_sql, action_taken, status) VALUES (datetime('now'), ?, ?, ?, ?)",
                    (user_query, generated_sql, action_taken, status),
                )

    def get_audit_logs(self, limit: int = 100) -> pd.DataFrame:
        query = f"SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT {int(limit)}"
        with self._connection() as conn:
            return pd.read_sql(query, conn)


def get_db_manager() -> DBManager:
    return DBManager()

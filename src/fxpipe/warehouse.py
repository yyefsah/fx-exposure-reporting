"""Entrepôt SQLite : chargement des tables et lecture des vues d'exposition."""
import sqlite3
from pathlib import Path

import pandas as pd

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    return con


def load_rates(con: sqlite3.Connection, eur_prices: pd.DataFrame) -> None:
    long = (eur_prices.rename_axis("date").reset_index().melt("date", var_name="currency", value_name="eur_per_unit"))
    long["date"] = long["date"].dt.strftime("%Y-%m-%d")
    con.execute("DELETE FROM fx_eur")
    long.to_sql("fx_eur", con, if_exists="append", index=False)
    con.commit()


def load_items(con: sqlite3.Connection, run_id: str, items: pd.DataFrame) -> None:
    items.assign(run_id=run_id)[["run_id", "item_id", "counterparty", "item_type", "currency", "amount",
                                 "hedged_amount", "due_date", "sign", "open_amount_signed", "days_to_due",
                                 "bucket"]].to_sql("open_items", con, if_exists="append", index=False)
    con.commit()


def read(con: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, con, params=params)

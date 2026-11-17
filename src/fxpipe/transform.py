"""Mise en forme des taux : format large, taux croisés vs EUR, rendements logarithmiques."""
import numpy as np
import pandas as pd


def to_wide(raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Format large : une colonne par devise, valeur = unités de devise pour 1 USD (conserve les NaN de la source)."""
    labels = {v: k for k, v in cfg["currencies"].items()}
    d = raw[raw["Country"].isin(labels)].copy()
    d["Date"] = pd.to_datetime(d["Date"])
    d["ccy"] = d["Country"].map(labels)
    wide = d.pivot_table(index="Date", columns="ccy", values="Exchange rate", aggfunc="last", dropna=False)
    wide = wide[[c for c in cfg["currencies"]]].sort_index()
    return wide.loc[wide.index >= pd.Timestamp(cfg["source"]["history_start"])]


def eur_per_ccy(wide_usd: pd.DataFrame, ffill_limit: int = 3) -> pd.DataFrame:
    """Valeur en EUR d'une unité de chaque devise.

    La source cote tout en « devise pour 1 USD » ; donc  EUR par unité de CCY = (EUR par USD) / (CCY par USD).
    USD = (EUR par USD). Les trous (jours fériés US) sont comblés sur au plus `ffill_limit` jours."""
    w = wide_usd.ffill(limit=ffill_limit)
    out = pd.DataFrame(index=w.index)
    out["USD"] = w["EUR"]
    for c in w.columns:
        if c != "EUR":
            out[c] = w["EUR"] / w[c]
    return out.dropna(how="any")


def log_returns(prices: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    return np.log(prices).diff(horizon).dropna(how="any")

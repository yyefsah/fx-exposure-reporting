"""Génère un carnet de factures ouvertes SIMULÉ pour une PME exportatrice française.

Les taux de change du projet sont réels ; ce carnet ne l'est pas (aucune donnée d'entreprise n'est publique).
Usage :  python scripts/generate_exposures.py --as-of 2026-11-13 --seed 2026
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

MIX = {"USD": 0.52, "GBP": 0.16, "CHF": 0.10, "JPY": 0.12, "CNY": 0.10}
SCALE = {"USD": 70_000, "GBP": 45_000, "CHF": 50_000, "JPY": 7_000_000, "CNY": 380_000}   # montant médian en devise


def generate(as_of: str, seed: int = 2026, n: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d0 = pd.Timestamp(as_of)
    ccy = rng.choice(list(MIX), size=n, p=list(MIX.values()))
    typ = np.where(rng.random(n) < 0.72, "AR", "AP")                      # créances clients / dettes fournisseurs
    amount = np.round(np.array([SCALE[c] for c in ccy]) * rng.lognormal(0, 0.8, n), -2)
    horizon = rng.choice([-1, 1], p=[0.04, 0.96], size=n)                  # ~4 % de factures échues impayées
    days = np.where(horizon < 0, -rng.integers(1, 40, n), rng.integers(5, 200, n))
    due = d0 + pd.to_timedelta(days, unit="D")
    hedged = np.zeros(n)
    cover = (typ == "AR") & (np.isin(ccy, ["USD", "GBP"])) & (rng.random(n) < 0.55) & (days > 0)
    hedged[cover] = np.round(amount[cover] * rng.choice([0.5, 0.75, 1.0], size=cover.sum()), -2)
    return pd.DataFrame({
        "item_id": [f"INV-{i:05d}" for i in range(1, n + 1)],
        "counterparty": [f"{'CLI' if t == 'AR' else 'FOU'}-{rng.integers(1, 60):03d}" for t in typ],
        "item_type": typ, "currency": ccy, "amount": amount, "due_date": due.date.astype(str), "hedged_amount": hedged,
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-11-13")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/exposures/open_items.csv")
    a = ap.parse_args()
    df = generate(a.as_of, a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} lignes -> {a.out}")

"""Chargement et validation du carnet de factures ouvertes, calcul de l'exposition nette non couverte."""
import numpy as np
import pandas as pd

BUCKETS = ["Échu", "0-30 j", "31-90 j", "91-180 j", ">180 j"]
REQUIRED = ["item_id", "item_type", "currency", "amount", "due_date", "hedged_amount"]


def bucket(days: int) -> str:
    if days < 0:
        return "Échu"
    if days <= 30:
        return "0-30 j"
    if days <= 90:
        return "31-90 j"
    if days <= 180:
        return "91-180 j"
    return ">180 j"


def load_and_validate(path, as_of: pd.Timestamp, currencies: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Retourne (lignes valides enrichies, anomalies rencontrées). Les lignes invalides sont écartées ET listées."""
    df = pd.read_csv(path)
    issues: list[str] = []
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"colonnes manquantes dans le carnet : {missing}")
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    masks = {
        "devise non suivie": ~df["currency"].isin(currencies + ["USD"]),
        "type invalide (AR/AP attendu)": ~df["item_type"].isin(["AR", "AP"]),
        "montant ≤ 0 ou manquant": ~(df["amount"] > 0),
        "date d'échéance illisible": df["due_date"].isna(),
        "couverture > montant": df["hedged_amount"] > df["amount"],
        "identifiant en double": df["item_id"].duplicated(keep="first"),
    }
    bad = pd.Series(False, index=df.index)
    for label, m in masks.items():
        if m.any():
            issues.append(f"{int(m.sum())} ligne(s) écartée(s) : {label}")
        bad |= m
    ok = df[~bad].copy()
    ok["sign"] = np.where(ok["item_type"] == "AR", 1, -1)
    ok["open_amount_signed"] = ok["sign"] * (ok["amount"] - ok["hedged_amount"])
    ok["days_to_due"] = (ok["due_date"] - as_of).dt.days
    ok["bucket"] = ok["days_to_due"].map(bucket)
    ok["due_date"] = ok["due_date"].dt.strftime("%Y-%m-%d")
    overdue = int((ok["days_to_due"] < 0).sum())
    if overdue:
        issues.append(f"{overdue} facture(s) échue(s) non soldée(s) conservée(s) dans la tranche « Échu »")
    return ok, issues

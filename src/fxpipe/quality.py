"""Contrôles qualité des données de marché : chaque contrôle renvoie OK / WARN / FAIL."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Check:
    name: str
    status: str          # OK | WARN | FAIL
    detail: str


def run_checks(raw: pd.DataFrame, wide: pd.DataFrame, cfg: dict, as_of: pd.Timestamp) -> list[Check]:
    q, out = cfg["quality"], []

    # 1) schéma
    need = {"Date", "Country", "Exchange rate"}
    miss = need - set(raw.columns)
    out.append(Check("schéma", "FAIL" if miss else "OK", f"colonnes manquantes : {sorted(miss)}" if miss else "colonnes conformes"))
    if miss:
        return out
    absent = [c for c in cfg["currencies"] if c not in wide.columns or wide[c].dropna().empty]
    out.append(Check("devises présentes", "FAIL" if absent else "OK", f"absentes : {absent}" if absent else f"{len(cfg['currencies'])} devises"))
    if absent:
        return out

    # 2) doublons (date, pays)
    dup = int(raw.duplicated(["Date", "Country"]).sum())
    out.append(Check("doublons", "FAIL" if dup else "OK", f"{dup} lignes (date, pays) en double"))

    # 3) fraîcheur (jours ouvrés entre la dernière observation et la date de traitement)
    last = wide.dropna(how="any").index.max()
    lag = int(np.busday_count(last.date(), as_of.date()))
    st = "FAIL" if lag > q["max_staleness_business_days"] else ("WARN" if lag > 2 else "OK")
    out.append(Check("fraîcheur", st, f"dernière observation complète : {last.date()} ({lag} jours ouvrés avant {as_of.date()})"))

    # 4) plausibilité / unités (devise pour 1 USD)
    bad = []
    for c, (lo, hi) in cfg["plausible_range"].items():
        s = wide[c].dropna()
        if s.min() < lo or s.max() > hi:
            bad.append(f"{c}: [{s.min():.4g} ; {s.max():.4g}] hors [{lo} ; {hi}]")
    out.append(Check("plausibilité (unités)", "FAIL" if bad else "OK", "; ".join(bad) if bad else "toutes les séries dans la fourchette attendue"))

    # 4b) niveaux d'ancrage (détecte une inversion de cotation : EUR/USD et USD/EUR se chevauchent en fourchette)
    bad_a = []
    for a in cfg.get("anchors", []):
        d = pd.Timestamp(a["date"])
        if d in wide.index and not np.isnan(wide.loc[d, a["ccy"]]):
            v = wide.loc[d, a["ccy"]]
            if abs(v / a["value"] - 1) > a["tol"]:
                bad_a.append(f"{a['ccy']} au {a['date']} : {v:.4g} au lieu de ≈ {a['value']}")
    out.append(Check("niveaux d'ancrage", "FAIL" if bad_a else "OK", "; ".join(bad_a) if bad_a else "niveaux historiques conformes (sens de cotation confirmé)"))

    # 5) trous consécutifs sur les 2 dernières années
    recent = wide.loc[wide.index >= wide.index.max() - pd.DateOffset(years=2)]
    worst = 0
    for c in recent.columns:
        isna = recent[c].isna().to_numpy()
        run = best = 0
        for v in isna:
            run = run + 1 if v else 0
            best = max(best, run)
        worst = max(worst, best)
    out.append(Check("trous consécutifs (2 ans)", "FAIL" if worst > q["max_consecutive_missing"] else "OK",
                     f"plus longue séquence manquante : {worst} jours"))

    # 6) sauts quotidiens (signalés, pas bloquants : peuvent être de vrais événements de marché)
    r = np.log(wide.ffill(limit=3)).diff()
    z = r / r.rolling(250, min_periods=60).std().shift(1)
    jumps = (z.abs() > q["jump_sigma"])
    n_jump = int(jumps.sum().sum())
    ex = []
    for c in jumps.columns:
        for d in jumps.index[jumps[c]][-2:]:
            ex.append(f"{c} {d.date()} ({r.loc[d, c]:+.1%})")
    out.append(Check("sauts quotidiens", "WARN" if n_jump else "OK",
                     f"{n_jump} sauts > {q['jump_sigma']}σ sur l'historique ; derniers : {', '.join(ex[-4:])}" if n_jump else "aucun"))

    # 7) séries figées
    frozen = []
    for c in wide.columns:
        s = wide[c].dropna().tail(250)
        runs = (s != s.shift()).cumsum()
        if runs.value_counts().max() >= q["flat_run_days"]:
            frozen.append(c)
    out.append(Check("séries figées", "WARN" if frozen else "OK", f"valeur constante ≥ {q['flat_run_days']} jours : {frozen}" if frozen else "aucune"))
    return out


def has_failure(checks: list[Check]) -> bool:
    return any(c.status == "FAIL" for c in checks)

"""Mesures de risque de change : VaR/ES historiques, VaR EWMA, stress, backtest (Kupiec, Christoffersen)."""
import numpy as np
import pandas as pd
from scipy import stats


def pnl_from_returns(returns: pd.DataFrame, exposure_eur: pd.Series) -> pd.Series:
    """P&L en EUR d'un vecteur d'expositions nettes (EUR) soumis à des rendements log de la devise vs EUR."""
    n = exposure_eur.reindex(returns.columns).fillna(0.0)
    return ((np.exp(returns) - 1.0) * n).sum(axis=1)


def hist_var_es(pnl: pd.Series, confidence: float) -> tuple[float, float]:
    q = np.quantile(pnl, 1 - confidence)
    tail = pnl[pnl <= q]
    return float(-q), float(-tail.mean())


def horizon_returns(prices: pd.DataFrame, horizon: int, window: int) -> pd.DataFrame:
    """Rendements log chevauchants sur `horizon` jours, fenêtre glissante de `window` observations."""
    r = np.log(prices).diff(horizon).dropna()
    return r.tail(window)


def ewma_var(daily: pd.DataFrame, exposure_eur: pd.Series, lam: float, confidence: float, horizon: int) -> float:
    n = exposure_eur.reindex(daily.columns).fillna(0.0).to_numpy()
    x = daily.to_numpy()
    w = lam ** np.arange(len(x))[::-1]
    w /= w.sum()
    cov = (x * w[:, None]).T @ x
    sigma_1d = float(np.sqrt(n @ cov @ n))
    return float(stats.norm.ppf(confidence) * sigma_1d * np.sqrt(horizon))


def stress_tests(exposure_eur: pd.Series, prices: pd.DataFrame, shocks: list[float], horizon: int) -> pd.DataFrame:
    rows = []
    for s in shocks:
        # choc de l'euro de s : l'EUR s'apprécie de +s => chaque devise perd s en valeur EUR (approx. 1/(1+s) - 1)
        pnl = float((exposure_eur * (1 / (1 + s) - 1)).sum())
        rows.append(dict(scenario=f"EUR {s:+.0%} vs toutes devises", pnl_eur=pnl))
    r = np.log(prices).diff(horizon).dropna()
    pnl_hist = pnl_from_returns(r, exposure_eur)
    worst = pnl_hist.idxmin()
    rows.append(dict(scenario=f"Pire fenêtre de {horizon} j depuis {prices.index[0].year} (fin {worst.date()})",
                     pnl_eur=float(pnl_hist.min())))
    return pd.DataFrame(rows)


def kupiec_pof(x: int, n: int, p: float) -> tuple[float, float]:
    """Test de couverture inconditionnelle de Kupiec : H0 = taux d'exceptions égal à p."""
    ph = x / n
    ll0 = (n - x) * np.log(1 - p) + x * np.log(p)
    ll1 = (n - x) * np.log(1 - ph) + (x * np.log(ph) if x > 0 else 0.0)
    lr = -2 * (ll0 - ll1)
    return float(lr), float(stats.chi2.sf(lr, 1))


def christoffersen_independence(hits: np.ndarray) -> tuple[float, float]:
    """Test d'indépendance des exceptions (grappes) de Christoffersen."""
    h = hits.astype(int)
    a, b = h[:-1], h[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    if n01 + n11 == 0 or n01 == 0:
        return 0.0, 1.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0

    def ll(p, a_, b_):   # a_ échecs, b_ succès
        return (a_ * np.log(p) if a_ else 0.0) + (b_ * np.log(1 - p) if b_ else 0.0)

    l0 = ll(pi, n01 + n11, n00 + n10)
    l1 = ll(pi01, n01, n00) + ll(pi11, n11, n10) if n10 + n11 else ll(pi01, n01, n00)
    lr = -2 * (l0 - l1)
    return float(max(lr, 0.0)), float(stats.chi2.sf(max(lr, 0.0), 1))


def backtest(prices: pd.DataFrame, exposure_eur: pd.Series, confidence: float, window: int) -> dict:
    """Backtest 1 jour d'un portefeuille hypothétique (exposition actuelle appliquée à l'historique)."""
    daily = np.log(prices).diff().dropna()
    pnl = pnl_from_returns(daily, exposure_eur)
    var = -pnl.rolling(window).quantile(1 - confidence).shift(1)
    ok = var.notna()
    hits = (pnl[ok] < -var[ok]).to_numpy()
    n, x = len(hits), int(hits.sum())
    p = 1 - confidence
    lr_pof, p_pof = kupiec_pof(x, n, p)
    lr_ind, p_ind = christoffersen_independence(hits)
    last_year = hits[-250:]
    return {"confidence": confidence, "n_days": n, "expected_exceptions": n * p, "exceptions": x,
            "exception_rate": x / n, "kupiec_lr": lr_pof, "kupiec_p": p_pof, "christoffersen_ind_lr": lr_ind,
            "christoffersen_ind_p": p_ind, "exceptions_last_250d": int(last_year.sum()),
            "first_date": str(pnl[ok].index[0].date()), "last_date": str(pnl[ok].index[-1].date())}


def hedge_requirement(var_value: float, limit: float) -> float:
    """Part de l'exposition nette actuelle à couvrir en plus pour ramener la VaR sous la limite (VaR linéaire en l'exposition)."""
    return float(max(0.0, 1 - limit / var_value)) if var_value > 0 else 0.0

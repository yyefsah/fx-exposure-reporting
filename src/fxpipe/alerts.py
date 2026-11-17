"""Règles d'alerte de la politique de trésorerie."""
import pandas as pd


def evaluate(cfg: dict, results: dict, checks: list, backtests: list[dict]) -> list[dict]:
    r, alerts = cfg["risk"], []
    var = results["var_hist"]
    if var > r["var_limit_eur"]:
        alerts.append(dict(severity="CRITIQUE", code="VAR_LIMIT",
                           message=f"VaR {r['confidence']:.0%} {r['horizon_days']} j = {var:,.0f} € > limite {r['var_limit_eur']:,.0f} € "
                                   f"(couverture supplémentaire à envisager : {results['extra_hedge_share']:.0%} de l'exposition nette)"))
    gross, hedged = results["gross_flow_eur"], results["hedged_eur"]
    ratio = hedged / gross if gross else 0.0
    if ratio < r["min_hedge_ratio"]:
        alerts.append(dict(severity="ATTENTION", code="HEDGE_RATIO",
                           message=f"Taux de couverture {ratio:.0%} < minimum {r['min_hedge_ratio']:.0%} des flux bruts"))
    conc = results["concentration"]
    top = max(conc, key=conc.get)
    if conc[top] > r["max_ccy_concentration"]:
        alerts.append(dict(severity="ATTENTION", code="CONCENTRATION",
                           message=f"{top} = {conc[top]:.0%} de l'exposition nette non couverte (seuil {r['max_ccy_concentration']:.0%})"))
    if results["overdue_eur"] > 0:
        alerts.append(dict(severity="INFO", code="OVERDUE",
                           message=f"{results['overdue_n']} facture(s) échue(s) non soldée(s) : {results['overdue_eur']:,.0f} € d'exposition nette à relancer"))
    for c in checks:
        if c.status in ("WARN", "FAIL"):
            alerts.append(dict(severity="CRITIQUE" if c.status == "FAIL" else "INFO", code="DATA_QUALITY",
                               message=f"Qualité des données — {c.name} : {c.detail}"))
    for b in backtests:
        if b["kupiec_p"] < 0.05:
            alerts.append(dict(severity="ATTENTION", code="BACKTEST",
                               message=f"Backtest VaR {b['confidence']:.0%} rejeté par Kupiec (p={b['kupiec_p']:.3g}) : "
                                       f"{b['exceptions']} exceptions vs {b['expected_exceptions']:.0f} attendues"))
        if b["christoffersen_ind_p"] < 0.05:
            alerts.append(dict(severity="INFO", code="BACKTEST_CLUSTER",
                               message=f"Backtest VaR {b['confidence']:.0%} : exceptions groupées dans le temps "
                                       f"(Christoffersen p={b['christoffersen_ind_p']:.3g}) — le risque varie avec le régime de volatilité, que la fenêtre historique glissante suit avec retard"))
    order = {"CRITIQUE": 0, "ATTENTION": 1, "INFO": 2}
    return sorted(alerts, key=lambda a: order[a["severity"]])


def to_markdown(alerts: list[dict], as_of: str) -> str:
    if not alerts:
        return f"# Alertes change — {as_of}\n\nAucune alerte.\n"
    lines = [f"# Alertes change — {as_of}", ""]
    for a in alerts:
        lines.append(f"- **[{a['severity']}]** `{a['code']}` — {a['message']}")
    return "\n".join(lines) + "\n"

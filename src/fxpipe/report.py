"""Livrables : classeur Excel de pilotage, note PDF de 2 pages, graphiques."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#c9c8c4"
HEAD = PatternFill("solid", fgColor="1F3B57")
RAG = {"CRITIQUE": "F4B6B6", "ATTENTION": "FCE3B0", "INFO": "DCE9F7"}
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#ececea", "axes.axisbelow": True, "savefig.bbox": "tight", "figure.dpi": 150})


def _eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def charts(out: Path, results: dict, net: pd.DataFrame, pnl: pd.Series, bts: list[dict], cfg: dict) -> dict:
    d = out / "charts"
    d.mkdir(exist_ok=True)
    paths = {}
    # 1) exposition nette non couverte par devise
    n = net.set_index("currency")["net_open_eur"].sort_values()
    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    ax.barh(n.index, n.values / 1e3, color=[BLUE if v >= 0 else ORANGE for v in n.values], height=0.6)
    ax.axvline(0, color="#8a8984", lw=1)
    ax.set_xlabel("k€ (positif = devise à recevoir, négatif = à payer)")
    ax.set_title("Exposition nette non couverte", loc="left", fontsize=10)
    for y, v in enumerate(n.values / 1e3):
        ax.text(v, y, f" {v:,.0f}".replace(",", " "), va="center", ha="left" if v >= 0 else "right", fontsize=8)
    fig.savefig(d / "exposure.png"); plt.close(fig); paths["exposure"] = d / "exposure.png"
    # 2) distribution des P&L 10 j avec VaR / ES
    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    ax.hist(pnl / 1e3, bins=60, color=GREY)
    ax.axvline(-results["var_hist"] / 1e3, color=BLUE, lw=2, label=f"VaR 99 % : {_eur(results['var_hist'])}")
    ax.axvline(-results["es_hist"] / 1e3, color=ORANGE, lw=2, label=f"ES 99 % : {_eur(results['es_hist'])}")
    ax.axvline(-cfg["risk"]["var_limit_eur"] / 1e3, color="#52514e", lw=1.2, ls="--", label=f"Limite : {_eur(cfg['risk']['var_limit_eur'])}")
    ax.set_xlabel("P&L à 10 jours (k€), scénarios historiques"); ax.set_ylabel("Nb de scénarios")
    ax.legend(frameon=False, fontsize=7.5, loc="upper right")
    ax.set_title("Distribution des P&L simulés", loc="left", fontsize=10)
    fig.savefig(d / "pnl.png"); plt.close(fig); paths["pnl"] = d / "pnl.png"
    return {k: str(v) for k, v in paths.items()}


def _sheet(wb, title, df, widths=None, money_cols=()):
    ws = wb.create_sheet(title)
    for j, c in enumerate(df.columns, 1):
        cell = ws.cell(1, j, str(c))
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, row in enumerate(df.itertuples(index=False), 2):
        for j, v in enumerate(row, 1):
            v = None if (isinstance(v, float) and np.isnan(v)) else v
            cell = ws.cell(i, j, v.item() if hasattr(v, "item") else v)
            if df.columns[j - 1] in money_cols:
                cell.number_format = '#,##0 "€";[Red]-#,##0 "€"'
    for j, c in enumerate(df.columns, 1):
        ws.column_dimensions[ws.cell(1, j).column_letter].width = (widths or {}).get(c, max(14, len(str(c)) + 2))
    ws.freeze_panes = "A2"
    return ws


def build(cfg, out: Path, results, net, ladder, stress, bts, checks, alerts, prices, pnl, meta, run_id) -> dict:
    ch = charts(out, results, net, pnl, bts, cfg)
    rk = cfg["risk"]
    wb = Workbook()
    ws = wb.active; ws.title = "Synthèse"
    ws["A1"] = f"Reporting de position de change — valorisation au {results['valuation_date']}"
    ws["A1"].font = Font(bold=True, size=14)
    kpis = [("Exposition nette non couverte (somme signée)", results["net_exposure_eur"]),
            ("Exposition nette brute (somme des valeurs absolues)", results["gross_unhedged_eur"]),
            (f"VaR historique {rk['confidence']:.0%} {rk['horizon_days']} j", results["var_hist"]),
            (f"Expected shortfall {rk['confidence']:.0%} {rk['horizon_days']} j", results["es_hist"]),
            (f"VaR paramétrique EWMA (λ={rk['ewma_lambda']})", results["var_ewma"]),
            ("Limite de VaR (politique de trésorerie)", rk["var_limit_eur"]),
            ("Couverture supplémentaire nécessaire (part de l'exposition nette)", results["extra_hedge_share"])]
    for i, (k, v) in enumerate(kpis, 3):
        ws.cell(i, 1, k)
        c = ws.cell(i, 2, v)
        c.number_format = "0%" if "part de" in k else '#,##0 "€"'
        c.font = Font(bold=True)
    r0 = 3 + len(kpis) + 1
    ws.cell(r0, 1, "Alertes").font = Font(bold=True, size=12)
    for i, a in enumerate(alerts, r0 + 1):
        ws.cell(i, 1, a["severity"]).fill = PatternFill("solid", fgColor=RAG[a["severity"]])
        ws.cell(i, 2, a["message"])
    if not alerts:
        ws.cell(r0 + 1, 1, "Aucune alerte")
    ws.column_dimensions["A"].width = 62; ws.column_dimensions["B"].width = 120

    nt = net.rename(columns={"currency": "Devise", "receivables_ccy": "Créances (devise)", "payables_ccy": "Dettes (devise)",
                             "hedged_signed_ccy": "Couvert (devise)", "net_open_ccy": "Net non couvert (devise)",
                             "net_open_eur": "Net non couvert (€)", "net_gross_eur": "Net avant couverture (€)",
                             "gross_flow_eur": "Flux bruts (€)"}).drop(columns=["run_id"])
    _sheet(wb, "Exposition par devise", nt, money_cols=("Net non couvert (€)", "Net avant couverture (€)", "Flux bruts (€)"))
    lad = ladder.pivot_table(index="bucket", columns="currency", values="net_open_eur", aggfunc="sum", fill_value=0)
    order = [b for b in ["Échu", "0-30 j", "31-90 j", "91-180 j", ">180 j"] if b in lad.index]
    lad = lad.loc[order]
    lad["Total"] = lad.sum(axis=1)
    _sheet(wb, "Échéancier", lad.reset_index().rename(columns={"bucket": "Tranche"}), money_cols=tuple(lad.columns))
    risk_tbl = pd.DataFrame([("VaR historique", results["var_hist"]), ("Expected shortfall", results["es_hist"]),
                             ("VaR historique 95 %", results["var95_hist"]), ("VaR EWMA", results["var_ewma"])],
                            columns=["Mesure", "Montant (€)"])
    ws2 = _sheet(wb, "VaR & stress", risk_tbl, money_cols=("Montant (€)",))
    start = len(risk_tbl) + 4
    ws2.cell(start - 1, 1, "Scénarios de stress").font = Font(bold=True)
    for j, c in enumerate(["Scénario", "P&L (€)"], 1):
        cell = ws2.cell(start, j, c); cell.font = Font(bold=True, color="FFFFFF"); cell.fill = HEAD
    for i, r in enumerate(stress.itertuples(index=False), start + 1):
        ws2.cell(i, 1, r.scenario); ws2.cell(i, 2, r.pnl_eur).number_format = '#,##0 "€";[Red]-#,##0 "€"'
    ws2.column_dimensions["A"].width = 70
    bt = pd.DataFrame(bts).rename(columns={"confidence": "Niveau", "n_days": "Jours testés", "expected_exceptions": "Exceptions attendues",
                                           "exceptions": "Exceptions", "exception_rate": "Taux observé", "kupiec_lr": "Kupiec LR",
                                           "kupiec_p": "Kupiec p-value", "christoffersen_ind_lr": "Christoffersen LR",
                                           "christoffersen_ind_p": "Christoffersen p-value", "exceptions_last_250d": "Exceptions (250 derniers j)",
                                           "first_date": "Début", "last_date": "Fin"})
    _sheet(wb, "Backtest", bt)
    _sheet(wb, "Qualité des données", pd.DataFrame([c.__dict__ for c in checks]).rename(
        columns={"name": "Contrôle", "status": "Statut", "detail": "Détail"}), widths={"Détail": 110, "Contrôle": 28})
    trace = pd.DataFrame([("run_id", run_id), ("empreinte SHA-256 de la source", meta.get("sha256")),
                          ("lignes source", meta.get("rows")), ("données issues du cache", meta.get("from_cache")),
                          ("factures valides", results["n_items"])] +
                         [("anomalie carnet", s) for s in results["item_issues"]], columns=["Élément", "Valeur"])
    _sheet(wb, "Traçabilité", trace, widths={"Élément": 34, "Valeur": 90})
    xlsx = out / "rapport_change.xlsx"
    wb.save(xlsx)

    # --- PDF
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=colors.HexColor("#1F3B57"))
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    pdf = out / "rapport_change.pdf"
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm)
    el = [Paragraph(f"Position de change — {results['valuation_date']}", h1),
          Paragraph("Exposition nette non couverte, VaR, alertes. Taux : Fed H.10 (réels) ; factures : carnet simulé.", body), Spacer(1, 6)]
    t = Table([["Exposition nette (signée)", _eur(results["net_exposure_eur"]), f"VaR {rk['confidence']:.0%} {rk['horizon_days']} j", _eur(results["var_hist"])],
               ["Exposition brute non couverte", _eur(results["gross_unhedged_eur"]), "Expected shortfall", _eur(results["es_hist"])],
               ["Taux de couverture (flux bruts)", f"{results['hedged_eur'] / results['gross_flow_eur']:.0%}", "Limite de VaR", _eur(rk["var_limit_eur"])]],
              colWidths=[5.2 * cm, 3.6 * cm, 4.6 * cm, 3.6 * cm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d0cc")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f4f7")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f2f4f7")),
                           ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"), ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold")]))
    el += [t, Spacer(1, 8), Paragraph("<b>Alertes</b>", body)]
    for a in alerts[:8]:
        el.append(Paragraph(f"<b>[{a['severity']}]</b> {a['message']}", body))
    if not alerts:
        el.append(Paragraph("Aucune alerte.", body))
    el += [Spacer(1, 8), Table([[Image(ch["exposure"], 8.6 * cm, 4.6 * cm), Image(ch["pnl"], 8.6 * cm, 4.6 * cm)]])]
    bt_rows = [["Backtest 1 jour", "Jours", "Exceptions", "Attendues", "p Kupiec", "p Christoffersen"]]
    for b in bts:
        bt_rows.append([f"VaR {b['confidence']:.0%}", f"{b['n_days']:,}".replace(",", " "), b["exceptions"], f"{b['expected_exceptions']:.0f}",
                        f"{b['kupiec_p']:.3g}", f"{b['christoffersen_ind_p']:.3g}"])
    tb = Table(bt_rows, colWidths=[3.2 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm, 3.4 * cm])
    tb.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3B57")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d0cc"))]))
    el += [Spacer(1, 8), tb, Spacer(1, 6),
           Paragraph("Méthode : VaR par simulation historique (rendements chevauchants sur la fenêtre configurée), exposition nette = créances − dettes − couvertures, "
                     "valorisée au dernier cours. Détails, échéancier et contrôles qualité : rapport_change.xlsx.", body)]
    doc.build(el)
    return {"xlsx": str(xlsx), "pdf": str(pdf), **ch}

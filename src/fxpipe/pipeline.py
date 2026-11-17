"""Orchestration : ingestion → qualité → entrepôt SQL → risque → alertes → rapports. Journalisé et idempotent."""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fxpipe import alerts as alerts_mod
from fxpipe import exposure, ingest, quality, report, risk, settings, transform, warehouse

log = logging.getLogger("fxpipe")


def run(as_of: str | None = None, offline: bool = False, cfg_path: str | None = None) -> dict:
    t0 = time.time()
    cfg = settings.load(cfg_path)
    root = Path(cfg["_root"])
    out_dir = root / cfg["paths"]["outputs"]
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    as_of_ts = pd.Timestamp(as_of) if as_of else pd.Timestamp.today().normalize()
    con = warehouse.connect(root / cfg["paths"]["warehouse"])
    meta: dict = {}
    status, message = "OK", ""
    try:
        log.info("run %s — as_of %s", run_id, as_of_ts.date())
        raw, meta = ingest.fetch_raw(cfg, offline=offline)
        wide = transform.to_wide(raw, cfg)
        checks = quality.run_checks(raw, wide, cfg, as_of_ts)
        pd.DataFrame([c.__dict__ for c in checks]).assign(run_id=run_id)[["run_id", "name", "status", "detail"]] \
            .rename(columns={"name": "check_name"}).to_sql("quality_log", con, if_exists="append", index=False)
        for c in checks:
            log.log(logging.ERROR if c.status == "FAIL" else logging.INFO, "qualité [%s] %s : %s", c.status, c.name, c.detail)
        if quality.has_failure(checks):
            raise RuntimeError("contrôle qualité en échec : pipeline interrompu, rapport non généré")

        prices = transform.eur_per_ccy(wide)
        prices = prices.loc[prices.index <= as_of_ts]
        valuation_date = prices.index.max()
        warehouse.load_rates(con, prices)

        items, item_issues = exposure.load_and_validate(root / cfg["paths"]["exposures"], valuation_date,
                                                        list(cfg["currencies"]))
        warehouse.load_items(con, run_id, items)
        net = warehouse.read(con, "SELECT * FROM v_net_exposure WHERE run_id = ? ORDER BY currency", (run_id,))
        ladder = warehouse.read(con, "SELECT * FROM v_maturity_ladder WHERE run_id = ?", (run_id,))
        expo = net.set_index("currency")["net_open_eur"]

        rk = cfg["risk"]
        h_ret = risk.horizon_returns(prices, rk["horizon_days"], rk["window_days"])
        pnl = risk.pnl_from_returns(h_ret, expo)
        var_h, es_h = risk.hist_var_es(pnl, rk["confidence"])
        var95_h, _ = risk.hist_var_es(pnl, 0.95)
        daily = transform.log_returns(prices).tail(rk["window_days"])
        var_e = risk.ewma_var(daily, expo, rk["ewma_lambda"], rk["confidence"], rk["horizon_days"])
        stress = risk.stress_tests(expo, prices, rk["stress_shocks"], rk["horizon_days"])
        bts = [risk.backtest(prices, expo, c, rk["window_days"]) for c in rk["backtest_confidence"]]
        extra = risk.hedge_requirement(var_h, rk["var_limit_eur"])
        unhedged_abs = expo.abs()
        gross_flow = float(net["gross_flow_eur"].sum())
        hedged_eur = float((items["sign"].abs() * items["hedged_amount"] *
                            items["currency"].map(prices.iloc[-1])).sum())
        od = items[items["days_to_due"] < 0]
        results = {
            "valuation_date": str(valuation_date.date()), "var_hist": var_h, "es_hist": es_h, "var95_hist": var95_h,
            "var_ewma": var_e, "net_exposure_eur": float(expo.sum()), "gross_unhedged_eur": float(unhedged_abs.sum()),
            "gross_flow_eur": gross_flow, "hedged_eur": hedged_eur, "extra_hedge_share": extra,
            "concentration": (unhedged_abs / unhedged_abs.sum()).to_dict() if unhedged_abs.sum() else {},
            "overdue_n": int(len(od)), "overdue_eur": float((od["open_amount_signed"] * od["currency"].map(prices.iloc[-1])).abs().sum()),
            "n_items": int(len(items)), "item_issues": item_issues,
        }
        rows = [(run_id, k, "portfolio", v) for k, v in results.items() if isinstance(v, float)]
        con.executemany("INSERT INTO risk_results VALUES (?,?,?,?)", rows)
        con.commit()
        alerts = alerts_mod.evaluate(cfg, results, checks, bts)
        (out_dir / "alerts.md").write_text(alerts_mod.to_markdown(alerts, results["valuation_date"]), encoding="utf-8")
        (out_dir / "alerts.json").write_text(json.dumps(alerts, indent=2, ensure_ascii=False), encoding="utf-8")
        artefacts = report.build(cfg, out_dir, results, net, ladder, stress, bts, checks, alerts, prices, pnl, meta, run_id)
        results["artefacts"] = artefacts
        results["alerts"] = alerts
        results["backtests"] = bts
        results["stress"] = stress.to_dict("records")
        results["quality"] = [c.__dict__ for c in checks]
        message = f"{len(alerts)} alerte(s)"
    except Exception as exc:
        status, message, results = "FAIL", str(exc), {}
        log.exception("échec du run %s", run_id)
        (out_dir / "alerts.md").write_text(f"# Échec du pipeline — {as_of_ts.date()}\n\n{message}\n", encoding="utf-8")
    finally:
        con.execute("INSERT INTO run_log VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), str(as_of_ts.date()), status,
                     round(time.time() - t0, 2), meta.get("sha256"), int(meta.get("from_cache", False)),
                     len(results.get("alerts", [])), message))
        con.commit()
        con.close()
    results.update(status=status, message=message, run_id=run_id)
    return results

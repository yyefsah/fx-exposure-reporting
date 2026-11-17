import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from fxpipe import exposure, pipeline, quality, risk, settings, transform  # noqa: E402
from generate_exposures import generate  # noqa: E402

CFG = settings.load()
LEVELS = {"EUR": 0.848, "GBP": 0.602, "CHF": 1.366, "JPY": 112.0, "CNY": 8.28}   # devise pour 1 USD
VOL = {"EUR": 0.006, "GBP": 0.006, "CHF": 0.007, "JPY": 0.006, "CNY": 0.002}


def synthetic_long(end="2026-11-13", seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("1999-01-04", end)
    rows = []
    for ccy, label in CFG["currencies"].items():
        eps = rng.normal(0, VOL[ccy], len(dates))
        ou = np.zeros(len(dates))
        eps[0] = 0.0
        for i in range(1, len(dates)):               # retour à la moyenne : reste dans des niveaux réalistes
            ou[i] = 0.995 * ou[i - 1] + eps[i]
        path = LEVELS[ccy] * np.exp(ou)
        rows.append(pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Country": label, "Exchange rate": path}))
    return pd.concat(rows, ignore_index=True)


def test_cross_rates_are_converted_to_eur_per_unit():
    wide = pd.DataFrame({"EUR": [0.9], "GBP": [0.75], "JPY": [150.0], "CHF": [0.9], "CNY": [7.0]},
                        index=pd.to_datetime(["2026-01-02"]))
    p = transform.eur_per_ccy(wide)
    assert p["USD"].iloc[0] == pytest.approx(0.9)            # 1 USD = 0,9 EUR
    assert p["GBP"].iloc[0] == pytest.approx(0.9 / 0.75)     # 1 GBP = 1,2 EUR
    assert p["JPY"].iloc[0] == pytest.approx(0.9 / 150)


def test_historical_var_matches_normal_theory_for_single_position():
    rng = np.random.default_rng(1)
    prices = pd.DataFrame({"USD": np.exp(np.cumsum(rng.normal(0, 0.005, 20_000)))},
                          index=pd.bdate_range("1950-01-02", periods=20_000))
    n = pd.Series({"USD": 1_000_000.0})
    pnl = risk.pnl_from_returns(np.log(prices).diff(10).dropna(), n)
    var, es = risk.hist_var_es(pnl, 0.99)
    theo = 1_000_000 * 2.326 * 0.005 * np.sqrt(10)
    assert var == pytest.approx(theo, rel=0.08)
    assert es > var


def test_kupiec_and_christoffersen_known_values():
    lr, p = risk.kupiec_pof(0, 250, 0.01)
    assert lr == pytest.approx(-2 * 250 * np.log(0.99), rel=1e-9)
    assert p == pytest.approx(0.0250, abs=0.001)
    assert risk.kupiec_pof(10, 1000, 0.01)[1] == pytest.approx(1.0, abs=1e-9)   # taux observé = taux attendu
    iid = np.random.default_rng(3).random(20_000) < 0.01
    assert risk.christoffersen_independence(iid)[1] > 0.01
    clustered = np.zeros(20_000, bool)
    clustered[1000:1040] = True                                   # 40 exceptions d'affilée
    assert risk.christoffersen_independence(clustered)[1] < 1e-6


def test_hedge_requirement_scales_var_to_limit():
    assert risk.hedge_requirement(200_000, 150_000) == pytest.approx(0.25)
    assert risk.hedge_requirement(100_000, 150_000) == 0.0


def _checks(long_df, as_of="2026-11-17"):
    wide = transform.to_wide(long_df, CFG)
    return {c.name: c for c in quality.run_checks(long_df, wide, CFG, pd.Timestamp(as_of))}


def test_quality_passes_on_clean_data():
    res = _checks(synthetic_long())
    assert not quality.has_failure(list(res.values())), {k: v.detail for k, v in res.items() if v.status == "FAIL"}


def test_quality_detects_unit_inversion_duplicates_and_stale_data():
    df = synthetic_long()
    inv = df.copy()
    m = inv["Country"] == "Euro"
    inv.loc[m, "Exchange rate"] = 1 / inv.loc[m, "Exchange rate"]     # source qui change de convention de cotation
    assert _checks(inv)["niveaux d'ancrage"].status == "FAIL"   # la fourchette seule ne le voit pas
    dup = pd.concat([df, df.iloc[:5]])
    assert _checks(dup)["doublons"].status == "FAIL"
    assert _checks(df, as_of="2026-12-30")["fraîcheur"].status == "FAIL"


def test_exposure_validation_rejects_bad_rows_and_flags_overdue(tmp_path):
    df = generate("2026-11-13", seed=5, n=40)
    bad = pd.DataFrame([
        dict(item_id="X1", counterparty="C", item_type="AR", currency="USD", amount=-5, due_date="2026-12-01", hedged_amount=0),
        dict(item_id="X2", counterparty="C", item_type="AR", currency="XXX", amount=5, due_date="2026-12-01", hedged_amount=0),
        dict(item_id="X3", counterparty="C", item_type="AP", currency="GBP", amount=100, due_date="2026-12-01", hedged_amount=500),
        dict(item_id=df.item_id.iloc[0], counterparty="C", item_type="AP", currency="GBP", amount=100, due_date="2026-12-01", hedged_amount=0),
    ])
    f = tmp_path / "items.csv"
    pd.concat([df, bad]).to_csv(f, index=False)
    ok, issues = exposure.load_and_validate(f, pd.Timestamp("2026-11-13"), list(CFG["currencies"]))
    assert len(ok) == len(df) and not ok["item_id"].isin(["X1", "X2", "X3"]).any()
    assert len(issues) >= 4
    assert ((ok["item_type"] == "AR") == (ok["sign"] == 1)).all()
    assert (ok.loc[ok.days_to_due < 0, "bucket"] == "Échu").all()


def test_pipeline_end_to_end_offline_and_failure_mode(tmp_path):
    cache = tmp_path / "raw"
    cache.mkdir()
    synthetic_long().to_csv(cache / "rates_20261113T000000Z.csv", index=False)
    generate("2026-11-13", seed=2026).to_csv(tmp_path / "items.csv", index=False)
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    cfg["source"]["cache_dir"] = str(cache)
    cfg["paths"] = {"warehouse": str(tmp_path / "w.db"), "exposures": str(tmp_path / "items.csv"), "outputs": str(tmp_path / "out")}
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg))
    res = pipeline.run("2026-11-17", offline=True, cfg_path=str(cfg_file))
    assert res["status"] == "OK", res["message"]
    assert res["var_hist"] > 0 and Path(res["artefacts"]["xlsx"]).exists() and Path(res["artefacts"]["pdf"]).exists()
    # date de traitement trop tardive : les données sont périmées -> le pipeline doit échouer proprement
    bad = pipeline.run("2027-03-01", offline=True, cfg_path=str(cfg_file))
    assert bad["status"] == "FAIL" and "qualité" in bad["message"]

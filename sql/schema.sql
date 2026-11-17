-- Entrepôt SQLite du pipeline de reporting de change
CREATE TABLE IF NOT EXISTS run_log (
  run_id TEXT PRIMARY KEY, started_at TEXT, as_of TEXT, status TEXT, duration_s REAL,
  source_sha256 TEXT, from_cache INTEGER, n_alerts INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS quality_log (run_id TEXT, check_name TEXT, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS fx_eur (date TEXT, currency TEXT, eur_per_unit REAL, PRIMARY KEY (date, currency));
CREATE TABLE IF NOT EXISTS open_items (
  run_id TEXT, item_id TEXT, counterparty TEXT, item_type TEXT, currency TEXT, amount REAL,
  hedged_amount REAL, due_date TEXT, sign INTEGER, open_amount_signed REAL, days_to_due INTEGER, bucket TEXT);
CREATE TABLE IF NOT EXISTS risk_results (run_id TEXT, metric TEXT, scope TEXT, value REAL);

DROP VIEW IF EXISTS v_net_exposure;
CREATE VIEW v_net_exposure AS
SELECT i.run_id, i.currency,
       SUM(CASE WHEN i.item_type = 'AR' THEN i.amount ELSE 0 END)                       AS receivables_ccy,
       SUM(CASE WHEN i.item_type = 'AP' THEN i.amount ELSE 0 END)                       AS payables_ccy,
       SUM(i.sign * i.hedged_amount)                                                    AS hedged_signed_ccy,
       SUM(i.open_amount_signed)                                                        AS net_open_ccy,
       SUM(i.open_amount_signed) * f.eur_per_unit                                       AS net_open_eur,
       SUM(i.sign * i.amount) * f.eur_per_unit                                          AS net_gross_eur,
       SUM(CASE WHEN i.item_type = 'AR' THEN i.amount ELSE 0 END) * f.eur_per_unit
         + SUM(CASE WHEN i.item_type = 'AP' THEN i.amount ELSE 0 END) * f.eur_per_unit  AS gross_flow_eur
FROM open_items i
JOIN fx_eur f ON f.currency = i.currency
 AND f.date = (SELECT MAX(date) FROM fx_eur)
GROUP BY i.run_id, i.currency;

DROP VIEW IF EXISTS v_maturity_ladder;
CREATE VIEW v_maturity_ladder AS
SELECT i.run_id, i.bucket, i.currency,
       SUM(i.open_amount_signed * f.eur_per_unit) AS net_open_eur,
       COUNT(*)                                    AS n_items
FROM open_items i
JOIN fx_eur f ON f.currency = i.currency AND f.date = (SELECT MAX(date) FROM fx_eur)
GROUP BY i.run_id, i.bucket, i.currency;

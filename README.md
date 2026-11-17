# Reporting automatisé du risque de change d'une PME exportatrice

Pipeline Python/SQL qui produit chaque semaine, sans intervention, la position de change d'une PME
facturant en USD, GBP, CHF, JPY et CNY : exposition nette non couverte, VaR/Expected Shortfall,
stress tests, backtest du modèle, alertes de politique de trésorerie et rapport Excel + PDF.

**Données :**
* **Taux de change réels** : Réserve fédérale américaine (série H.10 via FRED/[datahub](https://github.com/datasets/exchange-rates)),
  quotidiens depuis 1999 et à jour au 13/11/2026 lors de la dernière exécution.
* **Carnet de factures simulé** (320 lignes, `scripts/generate_exposures.py`, graine fixe) : aucune donnée d'entreprise n'est publique.
  Les chiffres d'exposition, de couverture et de VaR en euros décrivent donc une entreprise fictive.
*Projet personnel ; ce n'est pas une mission réalisée pour une entreprise.*

## Ce que le pipeline fait

```
Fed H.10 (CSV) ─► ingestion (cache + SHA-256) ─► 9 contrôles qualité ─► entrepôt SQLite (vues SQL d'exposition)
                                                        │ FAIL ⇒ arrêt, aucun rapport
carnet de factures ─► validation des lignes ───────────►│
                                                        ▼
                         VaR / ES historiques · VaR EWMA · stress · backtest ─► alertes ─► rapport .xlsx + .pdf
```

| Étape | Détail |
|---|---|
| Ingestion | 3 essais avec attente, copie archivée horodatée avec empreinte, **repli sur le cache signalé** si la source est en panne |
| Qualité | schéma, doublons, fraîcheur, fourchettes, **niveaux d'ancrage** (lancement de l'euro 1999), trous, sauts > 6σ, séries figées. Un `FAIL` stoppe le pipeline |
| Exposition | créances − dettes − couvertures par devise, échéancier, factures échues ; lignes invalides écartées **et listées** |
| Risque | VaR 99 % à 10 j par simulation historique (portefeuille complet, corrélations incluses), ES, VaR EWMA, stress, backtest Kupiec + Christoffersen |
| Alertes | limite de VaR, taux de couverture minimum, concentration par devise, qualité des données, échec de backtest — seuils dans `config/settings.yaml` |
| Traçabilité | table `run_log` (une ligne par exécution, statut, durée, empreinte de la source), contrôles qualité historisés en base |

Code de sortie de `run.py` : `0` rapport généré, `2` rapport généré avec alerte critique, `1` échec.
Exécution complète : environ 2 secondes.

## Résultats de la dernière exécution (valorisation au 13/11/2026)

| Indicateur | Valeur |
|---|---|
| Exposition nette non couverte | 4,30 M€ (CNY 1,52 M€, GBP 1,04 M€, CHF 0,88 M€, JPY 0,79 M€, USD 0,07 M€) |
| VaR 99 % à 10 jours (historique, 3 ans) | **95 056 €** (limite fixée dans la config : 150 000 €, non dépassée) |
| Expected Shortfall 99 % | 114 233 € |
| VaR paramétrique EWMA | 67 450 € |
| Stress : l'euro s'apprécie de 10 % face à toutes les devises | −390 939 € |
| Pire fenêtre de 10 jours depuis 1999 (fin 17/12/2008) | −320 867 € |
| Taux de couverture des flux bruts | 22 % (< seuil de 50 % ⇒ alerte) |

**Ce que le backtest apprend.** Sur 6 519 jours (2001-2026), la VaR 99 % à 1 jour est dépassée **63 fois pour 65 attendues**
(Kupiec p = 0,78) : le niveau est bon. En revanche l'indépendance des dépassements est **rejetée** (Christoffersen p = 0,003 à 99 %,
p = 3·10⁻⁵ à 95 %) : ils se regroupent en périodes de forte volatilité. De même, la pire fenêtre historique (−321 k€) vaut plus de
3 fois la VaR calculée sur les 3 dernières années : la fenêtre glissante ne « voit » pas les crises passées. Le pipeline le signale
dans les alertes plutôt que de le masquer.

## Choix et limites

* **Sens de cotation** : la documentation de la source indique « USD par EUR » pour l'euro et la livre, mais les données sont en
  « devise pour 1 USD » (cohérent avec l'euro à 1,18 USD au lancement en 1999). Une fourchette de plausibilité ne détecte pas cette
  inversion (les deux sens se chevauchent) ; c'est pourquoi un contrôle d'ancrage a été ajouté, avec un test qui injecte l'inversion.
* Exposition valorisée au dernier cours, sans courbes de taux : pas de calcul du coût des couvertures à terme (points de terme).
* Un carnet de factures est une vue d'un flux ; pas de budget prévisionnel ni de flux futurs non facturés.
* VaR historique sur 750 jours : simple et auditable, mais lente à réagir (voir backtest). Les seuils de la config sont des hypothèses.
* `.github/workflows/weekly_report.yml` planifie l'exécution hebdomadaire ; **non exécuté dans cet environnement** (premier lancement à valider sur GitHub).

## Utilisation

```bash
pip install -r requirements.txt
python scripts/generate_exposures.py --as-of 2026-11-13    # carnet simulé (déjà fourni)
python run.py                                              # ou --as-of AAAA-MM-JJ, --offline
pytest -q                                                  # 8 tests, sans accès réseau
```
Livrables dans `outputs/` : `rapport_change.xlsx` (7 onglets), `rapport_change.pdf`, `alerts.md`, `warehouse.db`.

## Structure

`src/fxpipe/` (ingest, quality, transform, exposure, risk, alerts, report, pipeline) · `sql/schema.sql` (tables + vues) ·
`config/settings.yaml` · `tests/` (VaR vs théorie normale, valeurs connues de Kupiec, détection de défauts de données injectés, pipeline bout en bout hors ligne, mode d'échec).

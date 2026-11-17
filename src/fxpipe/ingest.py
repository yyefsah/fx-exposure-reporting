"""Récupération des taux de change (avec cache horodaté, reprise sur erreur et traçabilité)."""
import hashlib
import io
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


class IngestError(RuntimeError):
    pass


def _download(url: str, timeout: int, retries: int) -> bytes:
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # réseau, DNS, HTTP 5xx...
            last = exc
            log.warning("téléchargement échoué (essai %d/%d) : %s", attempt, retries, exc)
            time.sleep(min(2 ** attempt, 8))
    raise IngestError(f"source injoignable après {retries} essais : {last}")


def fetch_raw(cfg: dict, offline: bool = False) -> tuple[pd.DataFrame, dict]:
    """Retourne (données brutes longues, métadonnées de traçabilité).

    * en ligne : télécharge, archive une copie horodatée (empreinte SHA-256) ;
    * hors ligne ou source en panne : bascule sur la dernière copie archivée et le signale (`from_cache`)."""
    src = cfg["source"]
    cache = Path(cfg["_root"]) / src["cache_dir"]
    cache.mkdir(parents=True, exist_ok=True)
    payload, from_cache = None, False
    if not offline:
        try:
            payload = _download(src["url"], src["timeout_s"], src["retries"])
        except IngestError as exc:
            log.error("%s -> bascule sur le cache", exc)
    if payload is None:
        files = sorted(cache.glob("rates_*.csv"))
        if not files:
            raise IngestError("aucune donnée : source injoignable et cache vide")
        payload, from_cache = files[-1].read_bytes(), True
        log.warning("utilisation du cache %s", files[-1].name)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (cache / f"rates_{stamp}.csv").write_bytes(payload)
    df = pd.read_csv(io.BytesIO(payload))
    meta = {"rows": len(df), "sha256": hashlib.sha256(payload).hexdigest()[:16], "from_cache": from_cache,
            "bytes": len(payload)}
    return df, meta

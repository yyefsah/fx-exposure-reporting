"""Point d'entrée :  python run.py [--as-of AAAA-MM-JJ] [--offline]
Code de sortie : 0 = rapport généré, 1 = échec (qualité des données, source), 2 = rapport généré avec alerte critique."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from fxpipe import pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="date de traitement (défaut : aujourd'hui)")
    ap.add_argument("--offline", action="store_true", help="n'utilise que le cache local")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("outputs/pipeline.log", encoding="utf-8")])
    res = pipeline.run(a.as_of, a.offline, a.config)
    if res["status"] != "OK":
        return 1
    return 2 if any(x["severity"] == "CRITIQUE" for x in res["alerts"]) else 0


if __name__ == "__main__":
    Path("outputs").mkdir(exist_ok=True)
    sys.exit(main())

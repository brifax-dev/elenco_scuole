"""Controllo dei file JSON del repository (lanciato da GitHub Actions).

Un errore qui vuol dire che l'app e il servizio Fantabasket non riescono a
leggere il file: per esempio un calendario non valido blocca l'invio delle
formazioni di tutta la competizione. Controlli:

1. ogni file .json è un JSON valido (con riga e colonna dell'errore);
2. calendario_*.json: elenco di turni con "partite", ogni partita con
   "casa" e "trasferta"; oppure, per le competizioni a classifica di
   giornata (es. Champions), turni con "classifica", ogni riga con
   "squadra" e "punti" ("posizione" facoltativa);
3. formazioni_*.json: "scadenza", se c'è, in un formato riconosciuto
   (2026-10-04T18:00, 2026-10-04 18:00, 04/10/2026 18:00, con fuso facoltativo);
4. versione.json: "versione" e link https di download.

Uso: python .github/scripts/controlla_json.py [cartella]
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ITALIAN = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:[ T,]+(\d{1,2})[:.](\d{2}))?$")
ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?(Z|[+-]\d{2}:?\d{2})?$",
    re.IGNORECASE,
)


def valid_deadline(text: str) -> bool:
    text = text.strip()
    m = ITALIAN.match(text) or ISO.match(text)
    if not m:
        return False
    try:
        if m.re is ITALIAN:
            day, month, year = int(m[1]), int(m[2]), int(m[3])
            hour, minute = int(m[4] or 0), int(m[5] or 0)
        else:
            year, month, day = int(m[1]), int(m[2]), int(m[3])
            hour, minute = int(m[4] or 0), int(m[5] or 0)
        datetime(year, month, day, hour, minute)
        return True
    except ValueError:
        return False


def check_calendar(data) -> list[str]:
    if not isinstance(data, list):
        return ["deve essere un elenco di turni [ ... ]"]
    errors = []
    for i, rnd in enumerate(data, 1):
        where = f"turno {i}"
        if not isinstance(rnd, dict):
            errors.append(f"{where}: deve essere un oggetto {{ ... }}")
            continue
        name = rnd.get("fase") or rnd.get("girone") or rnd.get("turno")
        if name:
            where += f" ({name})"
        matches = rnd.get("partite")
        if matches is None and isinstance(rnd.get("classifica"), list):
            errors += check_day_ranking(where, rnd["classifica"])
            continue
        if not isinstance(matches, list):
            errors.append(f'{where}: manca "partite" (elenco delle partite) o "classifica" (classifica di giornata)')
            continue
        for j, m in enumerate(matches, 1):
            if not isinstance(m, dict):
                errors.append(f"{where}, partita {j}: deve essere un oggetto {{ ... }}")
                continue
            for key in ("casa", "trasferta"):
                if not isinstance(m.get(key), str):
                    errors.append(f'{where}, partita {j}: manca "{key}" (testo, anche vuoto "")')
            for key in ("punteggioCasa", "punteggioTrasferta"):
                v = m.get(key)
                if v is not None and not isinstance(v, (str, int, float)):
                    errors.append(f'{where}, partita {j}: "{key}" deve essere un numero o un testo')
    return errors


def check_day_ranking(where: str, rows) -> list[str]:
    """Classifica di giornata (es. Champions): squadra, punti e posizione."""
    errors = []
    for j, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            errors.append(f"{where}, riga {j} della classifica: deve essere un oggetto {{ ... }}")
            continue
        if not isinstance(r.get("squadra"), str) or not r["squadra"].strip():
            errors.append(f'{where}, riga {j} della classifica: manca "squadra"')
        punti = r.get("punti")
        if isinstance(punti, str):
            try:
                float(punti.replace(",", "."))
            except ValueError:
                punti = None
        if punti is None or isinstance(punti, bool) or not isinstance(punti, (int, float, str)):
            errors.append(f'{where}, riga {j} della classifica: "punti" deve essere un numero')
        pos = r.get("posizione")
        if pos is not None and (isinstance(pos, bool) or not isinstance(pos, int)):
            errors.append(f'{where}, riga {j} della classifica: "posizione" deve essere un numero intero')
    return errors


def check_formations(data) -> list[str]:
    if not isinstance(data, dict):
        return ["deve essere un oggetto { ... }"]
    deadline = data.get("scadenza")
    if deadline in (None, ""):
        return []
    if not isinstance(deadline, str) or not valid_deadline(deadline):
        return [
            f'"scadenza": {json.dumps(deadline, ensure_ascii=False)} non è una data valida '
            '(es. "2026-10-04T18:00" oppure "04/10/2026 18:00", ora italiana)'
        ]
    return []


def check_version(data) -> list[str]:
    if not isinstance(data, dict):
        return ["deve essere un oggetto { ... }"]
    errors = []
    if not re.fullmatch(r"\d+(\.\d+)*", str(data.get("versione", ""))):
        errors.append('"versione" deve essere un numero di versione, es. "1.0.1"')
    for k, v in (data.get("download") or {}).items():
        if not str(v).startswith("https://"):
            errors.append(f'"download.{k}" deve essere un link https://')
    return errors


def main(root: Path) -> int:
    files = sorted(p for p in root.rglob("*.json") if ".git" not in p.parts)
    problems = 0
    for path in files:
        name = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            print(f"::error file={name}::{name}: non è testo UTF-8")
            problems += 1
            continue
        except json.JSONDecodeError as e:
            line = path.read_text(encoding="utf-8").splitlines()[e.lineno - 1] if e.lineno else ""
            print(
                f"::error file={name},line={e.lineno},col={e.colno}::"
                f"{name}, riga {e.lineno}, colonna {e.colno}: JSON non valido ({e.msg})"
            )
            print(f"    {line.strip()}")
            problems += 1
            continue
        base = path.name
        errors = []
        if base.startswith("calendario_"):
            errors = check_calendar(data)
        elif base.startswith("formazioni_"):
            errors = check_formations(data)
        elif base == "versione.json":
            errors = check_version(data)
        for err in errors:
            print(f"::error file={name}::{name}: {err}")
        problems += len(errors)
    if problems:
        print(f"\n{problems} problemi in {len(files)} file JSON: correggili, l'app non li legge.")
        return 1
    print(f"{len(files)} file JSON controllati: tutto a posto.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))

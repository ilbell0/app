# -*- coding: utf-8 -*-
"""Validatore delle invarianti dei dataset tattici.

Uso:  python tools/validate_data.py
Esce con codice 1 se trova errori. Codifica le regole emerse dagli audit:
ogni regressione futura (frecce orfane, contraddizioni, vocabolari sporchi,
matrice disallineata) viene intercettata qui invece che dall'utente in app.
"""
import re
import sys

from datasets import DATASETS, extract_assignments, load_json

ERRORS = []
WARNINGS = []

def err(msg):
    ERRORS.append(msg)

def warn(msg):
    WARNINGS.append(msg)

ARROW_VALUES = {"↑", "↓", "—"}
MENTALITY_EN = {"Normal", "Defensive", "Attacking", "Hard Attacking", "Hard Defending"}
MENTALITY_IT = {"Normale", "Difensiva", "Offensiva", "Molto Offensiva", "Molto Difensiva"}
PRESSING_EN = {"Low", "Medium", "High"}
PRESSING_IT = {"Basso", "Medio", "Alto"}
PASSING_EN = {"Short", "Long", "Mixed"}
PASSING_IT = {"Corti", "Lunghi", "Misti"}
TACKLING_EN = {"Easy", "Normal", "Hard"}
TACKLING_IT = {"Facile", "Normale", "Duro"}
MARKING_EN = {"Zonal", "Man-to-Man"}
MARKING_IT = {"Zonale", "Uomo a Uomo"}
FOCUS_EN = {"Down Both Flanks", "Through the Middle", "Mixed", "Right Flank", "Left Flank"}
FOCUS_IT = {"Per entrambe le fasce", "Per il centro", "Misto", "Fascia destra", "Fascia sinistra"}
ENG_VOCAB = {
    "men": MENTALITY_IT,
    "pass": {"Fasce", "Centro", "Misto"},
    "stile": PASSING_IT,
    "ctrl": {"SI", "NO"},
    "press": PRESSING_IT,
    "cont": TACKLING_IT,
    "marc": {"Zona", "Uomo"},
    "fuo": {"SI", "NO"},
}
# mojibake: UTF-8 letto come Latin-1/cp1252 ("Ã¬", "â€"). Mai legittimo nei dati.
MOJIBAKE_RX = re.compile(r"Ã|â€|Â°|Å")
# parole italiane con accento perso (regressione tipica dei generatori)
ACCENT_RX = re.compile(
    r"\b(piu|perche|puo|cosi|mentalita|abilita|velocita|qualita|superiorita|"
    r"staticita|profondita|difficolta|intensita|capacita|possibilita|densita)\b|"
    r"\b[eE]'(?=[\s,.;:!?)\]]|$)", re.IGNORECASE)


def check_formations(F):
    names, ids = set(), set()
    for f in F:
        n = f.get("name", "?")
        if f["id"] in ids:
            err(f"FORMATIONS: id duplicato {f['id']}")
        if n in names:
            err(f"FORMATIONS: nome duplicato {n}")
        ids.add(f["id"])
        names.add(n)
        pos = f.get("positions") or []
        if len(pos) != 11:
            err(f"FORMATIONS {n}: {len(pos)} giocatori invece di 11")
        if pos.count("GK") != 1:
            err(f"FORMATIONS {n}: numero portieri = {pos.count('GK')}")
        ndef = sum(1 for p in pos if p in ("DL", "DC", "DR"))
        if f.get("defense_count") != ndef:
            err(f"FORMATIONS {n}: defense_count={f.get('defense_count')} ma difensori={ndef}")
        blocks = [("recommended_tactics", f.get("recommended_tactics") or {})]
        for sc in ("strong", "equal", "weak"):
            s = (f.get("opponent_settings") or {}).get(sc)
            if not s:
                err(f"FORMATIONS {n}: scenario opponent_settings.{sc} mancante")
                continue
            blocks.append((sc, s))
            for k, v in (s.get("arrows") or {}).items():
                if k not in pos:
                    err(f"FORMATIONS {n}/{sc}: freccia su posizione inesistente {k}")
                if v not in ARROW_VALUES:
                    err(f"FORMATIONS {n}/{sc}: valore freccia anomalo {v!r}")
        for sc, s in blocks:
            for field, vocab in [
                ("mentality", MENTALITY_EN), ("mentality_it", MENTALITY_IT),
                ("pressing", PRESSING_EN), ("pressing_it", PRESSING_IT),
                ("passing_style", PASSING_EN), ("passing_style_it", PASSING_IT),
                ("tackling", TACKLING_EN), ("tackling_it", TACKLING_IT),
                ("marking", MARKING_EN), ("marking_it", MARKING_IT),
                ("focus_passing", FOCUS_EN), ("focus_passing_it", FOCUS_IT),
            ]:
                if field in s and s[field] not in vocab:
                    err(f"FORMATIONS {n}/{sc}: {field}={s[field]!r} fuori vocabolario")
            if s.get("offside_trap") is True and s.get("pressing") == "Low":
                err(f"FORMATIONS {n}/{sc}: fuorigioco ON con pressing basso")
            if s.get("counter_attack") is True and s.get("mentality") in ("Attacking", "Hard Attacking"):
                err(f"FORMATIONS {n}/{sc}: contropiede ON con mentalità offensiva")
    byname = {f["name"]: f for f in F}
    for f in F:
        for key in ("effective_against", "vulnerable_to"):
            for t in f.get(key) or []:
                if t not in byname:
                    err(f"FORMATIONS {f['name']}: {key} cita modulo inesistente {t!r}")
        for t in f.get("effective_against") or []:
            g = byname.get(t)
            if g and f["name"] in (g.get("effective_against") or []):
                err(f"FORMATIONS: contraddizione {f['name']} e {t} si battono a vicenda")
        both = set(f.get("effective_against") or []) & set(f.get("vulnerable_to") or [])
        if both:
            err(f"FORMATIONS {f['name']}: stessi moduli in effective e vulnerable: {sorted(both)}")
    return names


def check_engine(E, names, byname):
    avs = set()
    for e in E:
        av = e.get("av", "?")
        if av in avs:
            err(f"ENGINE: avversario duplicato {av}")
        avs.add(av)
        if av not in names:
            err(f"ENGINE {av}: avversario non è un modulo canonico")
        for sc in ("forte", "pari", "debole"):
            s = e.get(sc)
            if not s:
                err(f"ENGINE {av}: scenario {sc} mancante")
                continue
            for field in ("mod", "alt"):
                if s.get(field) and s[field] not in names:
                    err(f"ENGINE {av}/{sc}: {field}={s[field]!r} non è un modulo canonico")
            mod = byname.get(s.get("mod"))
            if mod:
                pos = set(mod["positions"])
                for k, v in (s.get("fr") or {}).items():
                    if k not in pos:
                        err(f"ENGINE {av}/{sc}: freccia {k} non esiste nel {s['mod']}")
                    if v not in ARROW_VALUES:
                        err(f"ENGINE {av}/{sc}: valore freccia anomalo {v!r}")
            for field, vocab in ENG_VOCAB.items():
                if s.get(field) not in vocab:
                    err(f"ENGINE {av}/{sc}: {field}={s.get(field)!r} fuori vocabolario")
            if s.get("fuo") == "SI" and s.get("press") == "Basso":
                err(f"ENGINE {av}/{sc}: fuorigioco SI con pressing basso")
            if s.get("ctrl") == "SI" and s.get("men") in ("Offensiva", "Molto Offensiva"):
                err(f"ENGINE {av}/{sc}: contropiede SI con mentalità offensiva")
    return avs


def check_matrix_quick(E, M, Q, avs):
    eng = {e["av"]: e for e in E}
    opps = {m["opponent"] for m in M}
    if opps != avs:
        err(f"MATRIX: copertura diversa dall'engine (solo matrix: {sorted(opps - avs)}, solo engine: {sorted(avs - opps)})")
    for m in M:
        e = eng.get(m["opponent"])
        if not e:
            continue
        expect = {
            "counter_offensive": e["debole"]["mod"],
            "counter_neutral": e["pari"]["mod"],
            "counter_defensive": e["forte"]["mod"],
        }
        for k, v in expect.items():
            if m.get(k) != v:
                err(f"MATRIX {m['opponent']}: {k}={m.get(k)!r} ma engine dice {v!r}")
        if m.get("category") != e.get("cat"):
            err(f"MATRIX {m['opponent']}: categoria {m.get('category')!r} != engine {e.get('cat')!r}")
    mm = {m["opponent"]: m for m in M}
    for q in Q:
        m = mm.get(q["av"])
        if not m:
            err(f"QUICK {q['av']}: avversario assente dalla matrice")
            continue
        if (q["off"], q["neu"], q["dif"]) != (m["counter_offensive"], m["counter_neutral"], m["counter_defensive"]):
            err(f"QUICK {q['av']}: counter diversi dalla matrice")
        if q.get("cat") != m.get("category"):
            err(f"QUICK {q['av']}: categoria diversa dalla matrice")


def check_arrow_tactics(A, F):
    ids = {f["id"]: f for f in F}
    for a in A:
        f = ids.get(a.get("formation_id"))
        if not f:
            err(f"ARROW_TACTICS {a.get('formation')}: formation_id {a.get('formation_id')!r} inesistente")
            continue
        for token in (a.get("arrows") or "").split():
            p = token.rstrip("↑↓—")
            if p and p not in f["positions"]:
                err(f"ARROW_TACTICS {a['formation']}: posizione {p} non presente nel modulo")


def check_accents(data):
    def walk(obj, in_it, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, in_it or str(k).endswith("_it") or k == "w", f"{path}.{k}")
        elif isinstance(obj, list):
            for i, x in enumerate(obj):
                walk(x, in_it, f"{path}[{i}]")
        elif isinstance(obj, str):
            if MOJIBAKE_RX.search(obj):
                err(f"mojibake (encoding corrotto) in {path}: {obj[:80]!r}")
            if in_it:
                m = ACCENT_RX.search(obj)
                if m:
                    warn(f"accento mancante in {path}: ...{obj[max(0, m.start()-20):m.end()+20]}...")
    for var, d in data.items():
        walk(d, False, var)


def main():
    # 1. server.py deve restare la fonte di verità: parse + confronto col bundle
    try:
        assigns = extract_assignments()
    except Exception as exc:
        print(f"ERRORE FATALE: impossibile estrarre i dataset da server.py: {exc}")
        return 1
    data = {}
    for var, fname in DATASETS.items():
        srv = assigns[var][0]
        js = load_json(fname)
        if srv != js:
            err(f"SYNC: {var} in server.py diverso da {fname}.json (esegui tools/sync_data.py)")
        data[var] = js

    F = data["FORMATIONS"]
    byname = {f["name"]: f for f in F}
    names = check_formations(F)
    avs = check_engine(data["COUNTER_ENGINE"], names, byname)
    check_matrix_quick(data["COUNTER_ENGINE"], data["MATCHUP_MATRIX"], data["COUNTER_QUICK"], avs)
    check_arrow_tactics(data["ARROW_TACTICS"], F)
    check_accents(data)

    for w in WARNINGS:
        print(f"AVVISO : {w}")
    for e in ERRORS:
        print(f"ERRORE : {e}")
    print(f"\n{len(ERRORS)} errori, {len(WARNINGS)} avvisi su {sum(len(v) for v in data.values())} voci in {len(data)} dataset.")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())

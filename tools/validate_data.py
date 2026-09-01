# -*- coding: utf-8 -*-
"""Validatore delle invarianti dei dataset tattici.

Uso:  python tools/validate_data.py
Esce con codice 1 se trova errori. Codifica le regole emerse dagli audit:
ogni regressione futura (frecce orfane, contraddizioni, vocabolari sporchi,
matrice disallineata) viene intercettata qui invece che dall'utente in app.
"""
import io
import json
import os
import re
import sys
import unicodedata

from datasets import DATASETS, ROOT, extract_assignments, load_json

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
PASSING_STYLE_EN = {"Short", "Long", "Mixed"}
PASSING_STYLE_IT = {"Palla corta", "Palla lunga", "Misto", "Corti", "Lunghi", "Misti"}
PASSING_TYPE_EN = {"Down Both Flanks", "Through the Middle", "Mixed", "Right Flank", "Left Flank"}
PASSING_TYPE_IT = {"Per entrambe le fasce", "Entrambe fasce", "Per il centro", "Misto", "Fascia destra", "Fascia sinistra", "Fasce", "Centro"}
SHOOTING_EN = {"Normal", "Shoot on Sight", "Work into Box"}
SHOOTING_IT = {"Normale", "Tiro a vista", "Strategia in area"}
LOST_POSS_EN = {"Reaggression", "Regroup"}
LOST_POSS_IT = {"Riaggressione", "Raggruppamento"}
WON_POSS_EN = {"Counter-attack", "Concentrate Actions"}
WON_POSS_IT = {"Contropiede", "Concentr. azioni"}
DEF_LINE_EN = {"Offside Trap", "Track Opponent"}
DEF_LINE_IT = {"Trapp. fuorig.", "Tracc. avvers."}
# etichette verificate a schermo (dropdown Stile contrasti, TATTICHE): Ai
# piedi / Normale / Aggressivo, non piu' Facile / Normale / Duro
TACKLING_EN = {"Stay on Feet", "Normal", "Aggressive"}
TACKLING_IT = {"Ai piedi", "Normale", "Aggressivo"}
MARKING_EN = {"Zonal", "Man-to-Man"}
MARKING_IT = {"Zonale", "Uomo a Uomo"}
# etichetta di marc (ENGINE) verificata sullo schermo del gioco il 26/08/2026
# (schermata TATTICHE) — diversa da MARKING_IT, che vale per FORMATIONS.marking_it.
MARKING_REAL_IT = {"A zona", "A uomo"}
# tend_cross (tendenza cross) e' uno SLIDER a tacche 1-2-3 dall'aggiornamento
# 2027, non piu' un menu chiuso: validato a parte in check_engine, non qui.
CROSSING_LEVELS = {1, 2, 3}

ENG_VOCAB = {
    "tend_tiro": SHOOTING_IT,
    "stile_pass": PASSING_STYLE_IT,
    "tipo_pass": PASSING_TYPE_IT,
    "poss_perso": LOST_POSS_IT,
    "poss_ottenuto": WON_POSS_IT,
    "men": MENTALITY_IT,
    "marc": MARKING_REAL_IT,
    "press": PRESSING_IT,
    "linea_dif": DEF_LINE_IT,
    "cont": TACKLING_IT,
}
# mojibake: UTF-8 letto come Latin-1/cp1252 ("Ã¬", "â€"). Mai legittimo nei dati.
MOJIBAKE_RX = re.compile(r"Ã|â€|Â°|Å")
# parole italiane con accento perso (regressione tipica dei generatori)
ACCENT_RX = re.compile(
    r"\b(piu|perche|puo|cosi|mentalita|abilita|velocita|qualita|superiorita|"
    r"staticita|profondita|difficolta|intensita|capacita|possibilita|densita|"
    r"priorita|disponibilita|novita|proprieta|attivita|liberta)\b|"
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
        blocks = []
        if "recommended_tactics" in f and f["recommended_tactics"]:
            blocks.append(("recommended_tactics", f["recommended_tactics"]))
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
                ("passing_style", PASSING_STYLE_EN), ("passing_style_it", PASSING_STYLE_IT),
                ("tackling", TACKLING_EN), ("tackling_it", TACKLING_IT),
                ("marking", MARKING_EN), ("marking_it", MARKING_IT),
                ("passing_type", PASSING_TYPE_EN), ("passing_type_it", PASSING_TYPE_IT),
                ("shooting_tendency", SHOOTING_EN), ("shooting_tendency_it", SHOOTING_IT),
                ("lost_possession", LOST_POSS_EN), ("lost_possession_it", LOST_POSS_IT),
                ("won_possession", WON_POSS_EN), ("won_possession_it", WON_POSS_IT),
                ("defensive_line", DEF_LINE_EN), ("defensive_line_it", DEF_LINE_IT),
            ]:
                if field in s and s[field] not in vocab:
                    err(f"FORMATIONS {n}/{sc}: {field}={s[field]!r} fuori vocabolario")
            # tend_cross e' uno slider a tacche 1-2-3 (aggiornamento 2027), non un menu chiuso
            for field in ("crossing_tendency", "crossing_tendency_it"):
                if field in s and s[field] not in CROSSING_LEVELS:
                    err(f"FORMATIONS {n}/{sc}: {field}={s[field]!r} fuori scala 1-3")
            if (s.get("defensive_line") == "Offside Trap" or s.get("offside_trap") is True) and s.get("pressing") == "Low":
                err(f"FORMATIONS {n}/{sc}: fuorigioco ON con pressing basso")
            if (s.get("won_possession") == "Counter-attack" or s.get("counter_attack") is True) and s.get("mentality") in ("Attacking", "Hard Attacking"):
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
                elif s.get(field) and av in (byname[s[field]].get("vulnerable_to") or []):
                    err(f"ENGINE {av}/{sc}: {field}={s[field]!r} è dichiarato VULNERABILE a {av}: counter contraddetto")
            # il counter offensivo dovrebbe essere confermato dal reverse-lookup
            if sc == "debole" and s.get("mod") in byname:
                m2 = byname[s["mod"]]
                supported = (av in (m2.get("effective_against") or [])
                             or s["mod"] in (byname.get(av, {}).get("vulnerable_to") or []))
                if not supported:
                    warn(f"ENGINE {av}/debole: counter {s['mod']!r} non confermato dal reverse-lookup")
            mod = byname.get(s.get("mod"))
            if mod:
                pos = set(mod["positions"])
                for k, v in (s.get("fr") or {}).items():
                    if k not in pos:
                        err(f"ENGINE {av}/{sc}: freccia {k} non esiste nel {s['mod']}")
                    if v not in ARROW_VALUES:
                        err(f"ENGINE {av}/{sc}: valore freccia anomalo {v!r}")
            # frecce dell'alternativa coerenti con le posizioni dell'alt
            alt = byname.get(s.get("alt"))
            if "alt_fr" in s and alt:
                apos = set(alt["positions"])
                for k, v in (s.get("alt_fr") or {}).items():
                    if k not in apos:
                        err(f"ENGINE {av}/{sc}: alt_fr {k} non esiste nel {s['alt']}")
                    if v not in ARROW_VALUES:
                        err(f"ENGINE {av}/{sc}: valore alt_fr anomalo {v!r}")
            for field, vocab in ENG_VOCAB.items():
                if s.get(field) not in vocab:
                    err(f"ENGINE {av}/{sc}: {field}={s.get(field)!r} fuori vocabolario")
            # tend_cross e' uno slider a tacche 1-2-3 (aggiornamento 2027), non un menu chiuso
            if s.get("tend_cross") not in CROSSING_LEVELS:
                err(f"ENGINE {av}/{sc}: tend_cross={s.get('tend_cross')!r} fuori scala 1-3")
            if s.get("linea_dif") == "Trapp. fuorig." and s.get("press") == "Basso":
                err(f"ENGINE {av}/{sc}: fuorigioco SI con pressing basso")
            if s.get("poss_ottenuto") == "Contropiede" and s.get("men") in ("Offensiva", "Molto Offensiva"):
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


RUOLI_NOTI = {
    "gk", "dl", "dc", "dr", "dmc", "mc", "ml", "mr",
    "aml", "amc", "amr", "st",
}


def _normalizza_testo(value):
    testo = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in testo if not unicodedata.combining(c)).casefold().strip()


def _corrisponde_giocatore(nome_completo, valore_disposizione):
    nome = _normalizza_testo(nome_completo)
    cognome = nome.rsplit(" ", 1)[-1]
    valore = _normalizza_testo(valore_disposizione)
    ultima_parola = valore.rsplit(" ", 1)[-1]
    return valore in (nome, cognome) or ultima_parola in (nome, cognome)


def check_stili(stili=None, disposizione=None):
    """Verifica che ogni stile sia acceso dall'assetto definitivo."""
    if stili is None:
        stili_path = os.path.join(ROOT, "dossier", "stili_gioco.json")
        if not os.path.exists(stili_path):
            return
        with io.open(stili_path, encoding="utf-8") as f:
            stili = json.load(f).get("stili", [])
    if disposizione is None:
        tattiche_path = os.path.join(ROOT, "dossier", "TATTICHE.json")
        if not os.path.exists(tattiche_path):
            return
        with io.open(tattiche_path, encoding="utf-8") as f:
            disposizione = json.load(f).get("assetto_definitivo", {}).get("disposizione", {})

    attivi = 0
    for stile in stili:
        giocatore = stile.get("giocatore", "?")
        nome_stile = stile.get("stile", "?")
        effetto = stile.get("effetto", "?")
        ruoli_richiesti = stile.get("ruoli_richiesti") or []
        caselle = [
            (casella, _normalizza_testo(casella), giocatore_disposto)
            for casella, giocatore_disposto in disposizione.items()
            if _corrisponde_giocatore(giocatore, giocatore_disposto)
        ]
        if not caselle:
            warn(f"STILI: {giocatore} ({nome_stile}, {effetto}) è in panchina")
            continue

        ruolo_richiesto = {_normalizza_testo(ruolo) for ruolo in ruoli_richiesti}
        ruolo_casella = {"punta": "st"}.get(caselle[0][1], caselle[0][1])
        if ruolo_casella in RUOLI_NOTI and ruolo_casella in ruolo_richiesto:
            attivi += 1
            continue

        casella, ruolo, _ = caselle[0]
        if ruolo not in RUOLI_NOTI and ruolo != "punta":
            warn(f"STILI: {giocatore} ({nome_stile}, {effetto}) è nella casella {casella}, non interpretabile")
            continue
        caselle_accensione = ", ".join(ruoli_richiesti)
        err(f"STILI: {giocatore} ({nome_stile}, {effetto}) è in {casella}; "
            f"lo stile richiede una casella tra {caselle_accensione}")

    print(f"stili attivi: {attivi}/{len(stili)}")


# --- dossier: protocollo di cattura (vedi dossier/PROTOCOLLO-CATTURA.md) ---
# Forcing function della fermata 1: un referto raccolto col protocollo non entra
# nel dossier senza i dati pre-partita. Senza questi campi l'analisi resta
# descrittiva, perche' registra dove il gioco e' finito e non cosa era stato
# impostato al fischio d'inizio.
COMPETIZIONI = {"campionato", "elite", "coppa", "amichevole"}
CAMPO = {"casa", "trasferta"}
REGIMI = {"A", "B", "C"}
# Etichette LETTE DALLO SCHERMO del gioco il 26/08/2026 (schermata TATTICHE).
# Non coincidono con quelle dei dataset dell'app: il gioco dice "Al centro" dove
# formations.json dice "Per il centro", "A zona" dove dice "Zonale", e
# "Concent. azioni" con una erre sola. Qui valgono quelle del gioco: sono le
# uniche che l'utente puo' davvero leggere e trascrivere.
# Pressing e Tendenza cross sono SLIDER a tacche, non menu: valore libero.
IMPOSTAZIONI_REALI = {
    'tend_tiro': {'Strategia in area', 'Tiro a vista', 'Normale'},
    'stile_pass': {'Palla corta', 'Palla lunga', 'Misto'},
    # menu aperto e letto il 26/08: cinque voci, 'Normale' e non 'Misto'
    'tipo_pass': {'Al centro', 'Entrambe fasce', 'Fascia destra',
                  'Fascia sinistra', 'Normale'},
    'tend_cross': None,
    'poss_perso': {'Riaggressione', 'Raggruppamento'},
    'poss_ottenuto': {'Concent. azioni', 'Contropiede'},
    'men': {'Molto Difensiva', 'Difensiva', 'Normale', 'Offensiva', 'Molto Offensiva'},
    'marc': MARKING_REAL_IT,
    'press': None,
    'linea_dif': {'Tracc. avvers.', 'Trapp. fuorig.'},
    'cont': TACKLING_IT,
}


def check_dossier():
    """Valida dossier/referti.json contro il protocollo di cattura."""
    path = os.path.join(ROOT, "dossier", "referti.json")
    if not os.path.exists(path):
        return 0
    with io.open(path, encoding="utf-8") as f:
        referti = json.load(f)
    for i, r in enumerate(referti):
        eti = "REFERTI[%d] %s" % (i, r.get("avversario") or "?")
        proto = r.get("protocollo")
        if proto is None:
            err("%s: campo 'protocollo' mancante. Metti 1 per i referti storici, "
                "2 per quelli raccolti col protocollo di cattura." % eti)
            continue
        if proto not in (1, 2):
            err("%s: protocollo=%r fuori dai valori ammessi (1, 2)" % (eti, proto))
            continue
        if proto == 1:
            continue  # referti storici: esentati, non sono ricostruibili

        # fermata 1 - i sei killer item
        if r.get("competizione") not in COMPETIZIONI:
            err("%s: competizione=%r, attesa una di %s"
                % (eti, r.get("competizione"), sorted(COMPETIZIONI)))
        if r.get("casa_trasferta") not in CAMPO:
            err("%s: casa_trasferta=%r. Senza, il diagramma a zone non e' orientabile."
                % (eti, r.get("casa_trasferta")))
        if r.get("regime_dichiarato") not in REGIMI:
            err("%s: regime_dichiarato=%r, atteso A, B o C, scritto prima del risultato."
                % (eti, r.get("regime_dichiarato")))
        for campo in ("gen_milan", "gen_avversario", "equilibrio_formazione"):
            if not isinstance(r.get(campo), (int, float)):
                err("%s: %s mancante o non numerico" % (eti, campo))
        imp = r.get("impostazioni")
        if not isinstance(imp, dict):
            err("%s: blocco 'impostazioni' mancante (gli 11 parametri al calcio d'inizio)" % eti)
        else:
            for k, vocab in IMPOSTAZIONI_REALI.items():
                if k not in imp:
                    err("%s/impostazioni: parametro %s mancante" % (eti, k))
                elif vocab is not None and imp[k] not in vocab:
                    err("%s/impostazioni: %s=%r fuori vocabolario" % (eti, k, imp[k]))
        if not r.get("frecce"):
            warn("%s: frecce non annotate. Si vedono solo prima del fischio d'inizio; "
                 "quelle nella schermata FORMAZIONI sono le sostituzioni." % eti)
    return len(referti)


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
    check_stili()
    n_referti = check_dossier()

    for w in WARNINGS:
        print(f"AVVISO : {w}")
    for e in ERRORS:
        print(f"ERRORE : {e}")
    print(f"\n{len(ERRORS)} errori, {len(WARNINGS)} avvisi su {sum(len(v) for v in data.values())} voci in {len(data)} dataset + {n_referti} referti.")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())

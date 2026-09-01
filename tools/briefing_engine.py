# -*- coding: utf-8 -*-
"""Motore briefing — la 'scheda allenatore' per ogni avversario.

Per decidere in fretta, un allenatore deve sapere 4 cose sull'avversario:
1. MINACCIA  — da dove segna (struttura offensiva reale del modulo)
2. ZONA      — dove lascia spazio (debolezza strutturale da attaccare)
3. DUELLI    — i 2-3 duelli individuali che decidono la partita
4. PIANO B   — cosa cambiare se il piano A non funziona

Derivazione deterministica dalle posizioni reali del modulo avversario e del
counter consigliato: stesso approccio a principi verificati di arrows_engine.
Le debolezze curate in FORMATIONS (weaknesses_it, verificate con le fonti)
vengono citate quando disponibili.
"""
from collections import Counter as Cnt


def parse(positions):
    c = Cnt(positions)
    return {
        "dl": c["DL"], "dc": c["DC"], "dr": c["DR"],
        "dif": c["DL"] + c["DC"] + c["DR"],
        "dmc": c["DMC"] + c["DML"] + c["DMR"],
        "ml": c["ML"], "mc": c["MC"], "mr": c["MR"],
        "mid": c["ML"] + c["MC"] + c["MR"],
        "aml": c["AML"], "amc": c["AMC"], "amr": c["AMR"],
        "am": c["AML"] + c["AMC"] + c["AMR"],
        "st": c["ST"],
        "wide_att": c["AML"] + c["AMR"],
        "wide_mid": c["ML"] + c["MR"],
        "fullbacks": c["DL"] + c["DR"],
    }


def minaccia(op):
    """Da dove segna l'avversario."""
    parts = []
    if op["st"] >= 2:
        parts.append(f"{op['st']} punte in area")
    elif op["st"] == 1 and op["amc"]:
        parts.append("punta + trequartista tra le linee")
    elif op["st"] == 1:
        parts.append("punta unica di riferimento")
    else:
        parts.append("nessuna punta fissa: inserimenti dei trequartisti")
    if op["wide_att"] >= 2:
        parts.append("ali alte che tagliano dentro")
    elif op["wide_att"] == 1:
        parts.append("un'ala alta da raddoppiare")
    if op["amc"] >= 2:
        parts.append(f"{op['amc']} AMC che affollano la trequarti")
    if op["wide_mid"] >= 2 and op["wide_att"] == 0:
        parts.append("spinta degli esterni di centrocampo")
    if op["fullbacks"] >= 2 and op["dif"] == 3:
        parts.append("terzini che si sovrappongono")
    s = "; ".join(parts[:3])
    return s[:1].upper() + s[1:]


def zona(op):
    """Dove l'avversario lascia spazio (da attaccare)."""
    zones = []
    if op["dif"] == 3 and op["fullbacks"] == 0 and op["wide_mid"] == 0:
        zones.append("fasce completamente scoperte: nessun terzino né esterno")
    elif op["dif"] == 3:
        zones.append("corsie esterne dietro i laterali che salgono")
    if op["dmc"] == 0 and op["mc"] <= 1:
        zones.append("nessuno schermo davanti alla difesa: trequarti libera")
    elif op["dmc"] == 0 and op["mc"] >= 2:
        zones.append("niente DMC di ruolo: porta fuori i loro MC e attacca tra le linee")
    if op["mid"] + op["dmc"] <= 2:
        zones.append("centrocampo in inferiorità numerica")
    # fonte: contro il bus non pressare alto (consuma condizione) — aggirare
    if op["dif"] >= 5 and op["am"] + op["st"] <= 2:
        zones.append("muro centrale: aggiralo con passaggi sulle fasce e mentalità su Offensiva, senza pressing alto prolungato")
    if op["dif"] == 4 and op["dc"] == 2 and op["st"] == 0:
        zones.append("area piccola difendibile: nessuna punta da marcare")
    if not zones:
        zones.append("modulo equilibrato: colpisci nelle transizioni, non in posizione")
    s = "; ".join(zones[:2])
    return s[:1].upper() + s[1:]


def duelli(op, cn):
    """I duelli individuali che decidono la partita (counter vs avversario)."""
    d = []
    # i miei difensori vs le loro punte (fonte: mai 2v2 secco, scala un terzino per il 3v2)
    if op["st"] >= 2:
        if cn["dc"] > op["st"]:
            d.append(f"i tuoi {cn['dc']} DC contro le loro {op['st']} punte: tieni un uomo libero")
        elif cn["fullbacks"] >= 1:
            d.append(f"{cn['dc']} DC contro {op['st']} punte: scala un terzino in linea per il 3v2, mai 2v2 secco")
        else:
            d.append(f"{cn['dc']} DC contro {op['st']} punte: marcatura stretta, niente 1v1")
    elif op["st"] == 1:
        d.append("un DC sulla punta, l'altro a coprire lo spazio")
    # il mio schermo vs il loro trequartista
    if op["amc"] and cn["dmc"]:
        d.append("il tuo DMC sul loro AMC: vincere questo duello spegne la manovra")
    elif op["amc"] and not cn["dmc"]:
        d.append("nessuno schermo sul loro AMC: un MC deve abbassarsi")
    # le mie ali vs i loro terzini/braccetti
    if cn["wide_att"] >= 2 and op["dif"] == 3:
        d.append("le tue ali contro i braccetti larghi: 1v1 da vincere sempre")
    elif cn["wide_att"] >= 2 and op["fullbacks"] >= 2:
        d.append("ali veloci sui loro terzini: costringili a restare bassi")
    # centrocampo
    mid_mine = cn["mid"] + cn["dmc"]
    mid_theirs = op["mid"] + op["dmc"]
    if mid_mine > mid_theirs:
        d.append(f"centrocampo {mid_mine}v{mid_theirs}: fai girare palla, il possesso è tuo")
    elif mid_mine < mid_theirs:
        d.append(f"centrocampo {mid_mine}v{mid_theirs}: non palleggiare, verticalizza subito")
    return d[:3]


def piano_b(e):
    """Cosa cambiare se il piano A non funziona (dai 3 scenari dell'engine)."""
    alt = e["pari"].get("alt")
    off_mod = e["debole"]["mod"]
    dif_mod = e["forte"]["mod"]
    steps = []
    if alt and alt != e["pari"]["mod"]:
        steps.append(f"se il {e['pari']['mod']} non morde, passa al {alt}")
    if dif_mod != e["pari"]["mod"]:
        steps.append(f"in vantaggio all'80': chiudi col {dif_mod} e imposta Contropiede")
    if off_mod != e["pari"]["mod"]:
        steps.append(f"sotto di un gol: {off_mod}, mentalità su Offensiva e pressing alto")
    return steps[:2]


def build_brief(opponent_positions, counter_positions, engine_entry, opponent_weaknesses=None):
    op = parse(opponent_positions)
    cn = parse(counter_positions)
    brief = {
        "minaccia": minaccia(op),
        "zona": zona(op),
        "duelli": duelli(op, cn),
        "piano_b": piano_b(engine_entry),
    }
    # se il modulo ha debolezze curate/verificate, la prima rafforza la zona
    if opponent_weaknesses:
        brief["zona"] = opponent_weaknesses[0].rstrip(".") + " — " + brief["zona"][0].lower() + brief["zona"][1:]
    return brief

# -*- coding: utf-8 -*-
"""Motore frecce tattico — unica fonte di verità per le frecce dei counter.

Le frecce (movimenti dei giocatori) in Top Eleven non sono arbitrarie: seguono
principi tattici precisi, ricavati dalle fonti (notebook 7b0eba98 + MY_PLAYBOOK).
Applicando QUESTO motore sia al modulo principale (`fr`) sia all'alternativa
(`alt_fr`), entrambi sono prodotti dallo stesso processo verificato: niente piu'
"uno curato a mano, l'altro generato".

Principi codificati (freccia ROSSA ↑ = avanza/attacca, BLU ↓ = arretra/copre):
- GK e DC: mai frecce (restano in posizione).
- DMC / DML / DMR: ↓ di default — stopper avanzato, +clean sheet (fonte MY_PLAYBOOK);
  sale a — solo nello scenario offensivo se l'avversario gioca a 5 (serve spinta).
- DL / DR (terzini): ↓ in difesa; ↑ in attacco SOLO se mancano ali alte (AML/AMR)
  che diano gia' ampiezza; — nel neutro.
- ML / MR (esterni di centrocampo): ↑ in attacco e neutro (spingono sulle fasce);
  — in difesa.
- MC (mediani centrali): — sempre (equilibrio, niente sovraccarico centrale).
- AML / AMR (ali offensive): ↑ sempre — sono l'arma offensiva e la ripartenza,
  specie contro la difesa a 3 (fasce scoperte).
- AMC (trequartista): ↑ in attacco (si inserisce); — altrimenti (resta a schermo).
- ST: — (la punta e' il riferimento; in Top Eleven raramente porta una freccia).
"""

UP, DOWN, DASH = "↑", "↓", "—"

NEVER = {"GK", "DC"}


def arrows_for(positions, scenario, opp_defense=4):
    """positions: lista codici; scenario: 'forte'(dif)|'pari'(neu)|'debole'(off);
    opp_defense: n. difensori dell'avversario (3/4/5). Ritorna {pos: freccia}."""
    pos = set(positions)
    has_high_wide = ("AML" in pos) or ("AMR" in pos)
    fr = {}
    for p in pos:
        if p in NEVER:
            continue
        if p in ("DMC", "DML", "DMR"):
            # schermo difensivo, tranne spinta vs bus a 5 quando attacchi
            fr[p] = DASH if (scenario == "debole" and opp_defense == 5) else DOWN
        elif p in ("DL", "DR"):
            if scenario == "forte":
                fr[p] = DOWN
            elif scenario == "debole" and not has_high_wide:
                fr[p] = UP            # danno ampiezza se non ci sono ali alte
            else:
                fr[p] = DASH
        elif p in ("ML", "MR"):
            fr[p] = DASH if scenario == "forte" else UP
        elif p == "MC":
            fr[p] = DASH
        elif p in ("AML", "AMR"):
            fr[p] = UP               # arma offensiva / ripartenza, sempre
        elif p == "AMC":
            fr[p] = UP if scenario == "debole" else DASH
        elif p == "ST":
            fr[p] = DASH
    if not fr:                        # difesa garantita: niente sezione vuota
        fr[sorted(pos - {"GK"})[0]] = DASH
    return fr

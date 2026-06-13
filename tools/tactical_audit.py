# -*- coding: utf-8 -*-
"""Motore di regole tattiche: valuta la sensatezza di ogni counter dell'engine
secondo i principi consolidati di Top Eleven 2026 (dominio del centrocampo,
larghezza vs difese strette, attacco alle fasce vs difesa a 3, ecc.).

Non e' un validatore bloccante: produce un report di QUALITA' tattica con
severita' (ALTA/MEDIA), per individuare i counter da rivedere o verificare
con le fonti. Uso:  python tools/tactical_audit.py [--severity ALTA]
"""
import sys
from collections import Counter as Cnt

from datasets import load_json


def parse(positions):
    """Scompone un modulo nelle sue linee."""
    c = Cnt(positions)
    dif = c["DL"] + c["DC"] + c["DR"]
    dmc = c["DMC"]
    mid = c["ML"] + c["MC"] + c["MR"]
    mid_central = c["MC"]
    am = c["AML"] + c["AMC"] + c["AMR"]
    am_central = c["AMC"]
    st = c["ST"]
    wide = c["ML"] + c["MR"] + c["AML"] + c["AMR"]
    central_engine = dmc + mid_central + am_central     # spina dorsale centrale
    attack = am + st                                     # potenziale offensivo
    return {
        "dif": dif, "dmc": dmc, "mid": mid, "am": am, "st": st,
        "wide": wide, "central": central_engine, "attack": attack,
        "has_high_wide": (c["AML"] + c["AMR"]) > 0,
    }


def audit():
    F = load_json("formations")
    E = load_json("counterEngine")
    byname = {f["name"]: f for f in F}

    def P(name):
        return parse(byname[name]["positions"])

    findings = []  # (severita', av, scenario, messaggio)

    for e in E:
        av = e["av"]
        ap = P(av)
        for sc, label in (("debole", "OFF"), ("pari", "NEU"), ("forte", "DIF")):
            s = e[sc]
            mod = s["mod"]
            cp = P(mod)

            # R1 - dominio del centrocampo centrale.
            # Eccezioni (principi dalle fonti): contro una difesa a 3 la partita
            # si vince per ampiezza alta, non al centro; e nello scenario difensivo
            # ci si chiude di proposito, non si contende il centrocampo.
            cdiff = cp["central"] - ap["central"]
            # contro una difesa a 3 bastano 2 giocatori larghi (anche ML/MR) per
            # sfruttare le corsie scoperte dai braccetti
            wins_on_flanks = ap["dif"] == 3 and cp["wide"] >= 2
            if cdiff <= -2 and cp["wide"] <= ap["wide"] and label != "DIF" and not wins_on_flanks:
                findings.append(("ALTA", av, label,
                    f"counter {mod}: centro {cp['central']} vs {ap['central']} dell'avversario "
                    f"(-{abs(cdiff)}) e nessun vantaggio sulle fasce -> rischia di perdere il centrocampo"))

            # R2 (INFO) - vs difesa a 3 un counter del tutto stretto rinuncia alle
            # fasce scoperte. Euristica debole: non distingue 3-pure/3N/3W, quindi
            # e' un suggerimento di miglioria, non un errore.
            if ap["dif"] == 3 and cp["wide"] == 0:
                findings.append(("INFO", av, label,
                    f"counter {mod}: avversario a 3 ma counter tutto centrale (nessuna corsia) "
                    f"-> valutare un'opzione piu' larga"))

            # R3 - vs difesa a 5: il counter difensivo e' poco utile (chi gioca a 5 non attacca)
            if ap["dif"] == 5 and label == "DIF" and cp["attack"] <= 2 and cp["dif"] >= 5:
                findings.append(("MEDIA", av, label,
                    f"counter {mod}: contro una difesa a 5 un assetto altrettanto chiuso "
                    f"(attacco {cp['attack']}) raramente sblocca la partita"))

            # R4 - coerenza mentalita'/categoria
            men = s.get("men", "")
            if label == "OFF" and men in ("Difensiva", "Molto Difensiva"):
                findings.append(("ALTA", av, label,
                    f"scenario offensivo (squadra piu' debole) ma mentalita' {men}"))
            # eccezione: contro una difesa a 5 (bus) attaccare e' corretto anche
            # da sfavoriti, perche' l'avversario rinuncia a fare gioco (fonti)
            if label == "DIF" and men in ("Offensiva", "Molto Offensiva") and ap["dif"] < 5:
                findings.append(("ALTA", av, label,
                    f"scenario difensivo (avversario piu' forte) ma mentalita' {men}"))

        # R5 (INFO) - inversione struttura off/dif. Metrica grezza (am+st sottostima
        # i moduli a 2 punte con centrocampo folto), quindi solo informativa: il vero
        # indicatore d'intento e' la mentalita', gia' verificata da R4.
        off_at = P(e["debole"]["mod"])["attack"]
        dif_at = P(e["forte"]["mod"])["attack"]
        if off_at < dif_at:
            findings.append(("INFO", av, "OFF/DIF",
                f"il counter offensivo {e['debole']['mod']} (attacco {off_at}) ha meno trequartisti/punte "
                f"del difensivo {e['forte']['mod']} (attacco {dif_at}) - verificare la mentalita'"))

        # R6 - tripletta identica: poca varieta'
        if len({e["forte"]["mod"], e["pari"]["mod"], e["debole"]["mod"]}) == 1:
            findings.append(("INFO", av, "ALL",
                f"stesso modulo {e['forte']['mod']} per tutti e 3 gli atteggiamenti (poca varieta')"))

    return findings


def main():
    want = None
    if "--severity" in sys.argv:
        want = sys.argv[sys.argv.index("--severity") + 1]
    findings = audit()
    order = {"ALTA": 0, "MEDIA": 1, "INFO": 2}
    findings.sort(key=lambda x: (order.get(x[0], 9), x[1]))
    counts = Cnt(f[0] for f in findings)
    for sev, av, sc, msg in findings:
        if want and sev != want:
            continue
        print(f"[{sev:5s}] {av} / {sc}: {msg}")
    print(f"\nTotale: {dict(counts)}")


if __name__ == "__main__":
    main()

"""Consultazione dati calcio reali via TheSportsDB (chiave di test gratuita, nessuna registrazione).

Strumento di sola lettura per ispirazione tattica: NON tocca i dataset dell'app
(l'engine resta la fonte di verita' dei counter). I risultati vengono salvati
in tools/football_cache/ come riferimento.

Uso tipico:
  py tools/fetch_football.py squadra "AC Milan"     # info squadra (stadio, campionato, descrizione)
  py tools/fetch_football.py rosa "AC Milan"        # rosa giocatori con ruolo
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# La console Windows usa cp1252: forza UTF-8 per nomi e descrizioni con caratteri speciali.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Chiave di test pubblica di TheSportsDB; sostituibile via variabile d'ambiente.
API_KEY = os.environ.get("THESPORTSDB_KEY", "123")
BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"
CACHE_DIR = Path(__file__).resolve().parent / "football_cache"


def _fetch(endpoint, **params):
    url = f"{BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def _salva(nome, dati):
    CACHE_DIR.mkdir(exist_ok=True)
    percorso = CACHE_DIR / f"{nome}.json"
    percorso.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    return percorso


def cmd_squadra(nome):
    dati = _fetch("searchteams.php", t=nome)
    squadre = dati.get("teams") or []
    if not squadre:
        sys.exit(f"Nessuna squadra trovata per '{nome}'.")
    s = squadre[0]
    print(f"{s['strTeam']} ({s.get('strCountry', '?')})")
    print(f"  Campionato: {s.get('strLeague', '?')}")
    print(f"  Stadio: {s.get('strStadium', '?')} ({s.get('intStadiumCapacity', '?')} posti)")
    if s.get("strDescriptionIT") or s.get("strDescriptionEN"):
        descr = s.get("strDescriptionIT") or s["strDescriptionEN"]
        print(f"  {descr[:300]}...")
    percorso = _salva(f"squadra_{s['strTeam'].replace(' ', '_')}", s)
    print(f"\nSalvato in {percorso}")


def cmd_rosa(nome):
    # searchplayers.php per squadra richiede chiave premium: si passa dall'ID squadra.
    squadre = _fetch("searchteams.php", t=nome).get("teams") or []
    if not squadre:
        sys.exit(f"Nessuna squadra trovata per '{nome}'.")
    dati = _fetch("lookup_all_players.php", id=squadre[0]["idTeam"])
    giocatori = dati.get("player") or []
    if not giocatori:
        sys.exit(f"Nessun giocatore disponibile per '{nome}' con la chiave di test.")
    per_ruolo = {}
    for g in giocatori:
        per_ruolo.setdefault(g.get("strPosition", "Sconosciuto"), []).append(g["strPlayer"])
    for ruolo, nomi in sorted(per_ruolo.items()):
        print(f"{ruolo}:")
        for n in nomi:
            print(f"  - {n}")
    percorso = _salva(f"rosa_{nome.replace(' ', '_')}", giocatori)
    print(f"\nSalvato in {percorso}")


def main():
    p = argparse.ArgumentParser(description="Dati calcio reali via TheSportsDB (sola lettura)")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("squadra", help="info squadra").add_argument("nome")
    sub.add_parser("rosa", help="rosa giocatori").add_argument("nome")
    args = p.parse_args()

    if args.comando == "squadra":
        cmd_squadra(args.nome)
    else:
        cmd_rosa(args.nome)


if __name__ == "__main__":
    main()

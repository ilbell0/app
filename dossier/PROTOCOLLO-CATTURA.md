# Protocollo di cattura dati — partite Top Eleven 2027

Formato **DO-CONFIRM**: gioca come fai sempre, poi ti fermi e verifichi.
Non è una guida: è una rete. Due fermate, 11 voci, ~90 secondi in totale.

Progettato con il metodo di Gawande (*The Checklist Manifesto*): solo le voci
che **sono state davvero saltate** nei primi 10 referti. Tutto ciò che fai
sempre da solo è deliberatamente assente.

---

## FERMATA 1 — prima di premere "Gioca"

Punto di non ritorno: dopo il fischio d'inizio le impostazioni pre-partita e le
frecce non sono più recuperabili. Sei voci, ~60 secondi.

1. **Competizione e campo** — campionato / Elite / coppa / amichevole, e
   casa o trasferta. Senza il campo, il diagramma a zone è illeggibile.
2. **Screenshot schermata Tattiche** — tutti e 11 i parametri, le tre fasi.
3. **Screenshot formazione con le frecce** — le frecce si vedono solo ora.
   Quelle rosse nella schermata FORMAZIONI a fine partita sono le sostituzioni.
4. **GEN mio, GEN avversario, equilibrio di formazione** — i tre numeri.
5. **Screenshot anteprima avversario** — modulo e giocatori migliori.
6. **Regime dichiarato: A, B o C** — scritto **prima** di vedere il risultato.

La voce 6 è la più importante e la meno ovvia. Una previsione annotata prima
dell'esito è l'unica cosa che rende il dossier verificabile invece che
descrittivo. Senza, ogni analisi resta una spiegazione costruita a posteriori
su un risultato già noto.

## FERMATA 2 — a fine partita, prima di chiudere

Sei voci, ~40 secondi.

1. **Referto** — risultato e marcatori.
2. **Scheda STATISTICHE** — possesso, tiri, duelli, passaggi, falli, intercetti.
3. **Origine di ogni gol** - azione, corner, punizione o rigore. Nei dieci
   referti storici non c e: sappiamo chi ha segnato e quando, non da dove. Con
   130 gol stagionali, se il 15% nascesse da palla inattiva sarebbero venti gol
   invisibili; e se i piazzati non producono nulla, ottimizzare i battitori e
   tempo perso. Bastano tre o quattro partite per saperlo.
4. **Scheda OCCASIONI** — è quella dimenticata contro lo Skogens: la peggiore
   sconfitta del campione ha i tiri e i corner ignoti per sempre.
5. **Diagramma a zone di entrambe le squadre** — non solo del Milan.
6. **Mentore avversario** — visibile soltanto dopo il calcio d'inizio.

---

## Forcing function

**Attivo in `tools/validate_data.py`** (funzione `check_dossier`). Gira a ogni
`.	p.ps1 check`, e fallisce con codice 1 se un referto non e' in regola.

Ogni referto deve dichiarare il campo `protocollo`:

- `1` — referto storico, esentato. I dieci esistenti sono gia' marcati cosi:
  non sono ricostruibili a posteriori.
- `2` — raccolto col protocollo. Deve avere tutti i campi della fermata 1.

Schema di un referto `protocollo: 2`:

```json
{
  "protocollo": 2,
  "avversario": "NomeSquadra",
  "competizione": "campionato",
  "casa_trasferta": "casa",
  "regime_dichiarato": "B",
  "gen_milan": 122.0,
  "gen_avversario": 110.0,
  "equilibrio_formazione": 9.8,
  "frecce": { "AMC": "su", "MR": "giu" },
  "impostazioni": {
    "tend_tiro": "Strategia in area", "stile_pass": "Palla corta",
    "tipo_pass": "Per il centro", "tend_cross": "Normale",
    "poss_perso": "Riaggressione", "poss_ottenuto": "Concentr. azioni",
    "men": "Offensiva", "marc": "Zonale", "press": "Alto",
    "linea_dif": "Trapp. fuorig.", "cont": "Normale"
  }
}
```

Gli undici parametri sono validati contro gli stessi vocabolari dell'app, quindi
un valore inventato viene respinto. `tend_cross` e' libero: e' uno slider, non
una lista. Le frecce mancanti danno un avviso, non un errore: se non le hai
annotate prima del fischio d'inizio non le recuperi piu'.

Il controllo meccanico e' la parte che funziona. La buona volonta' no: e' gia'
stata provata per dieci partite.

## Selezione delle partite

**Referti presi in ordine dal calendario, non scelti.** È la selezione a monte
che ha viziato tutta l'analisi finora: il dossier contiene il 100% delle
sconfitte e il 22% delle vittorie. Se salti una partita, annota che l'hai
saltata e perché.

## Regola di manutenzione

Alla decima partita raccolta col protocollo, rileggi questa pagina e chiediti
**cosa togliere**, non cosa aggiungere. Se una voce non è mai servita a niente,
esce. Se una fermata supera i 90 secondi, non verrà più eseguita.

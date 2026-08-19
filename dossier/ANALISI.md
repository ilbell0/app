# Dossier AC Milan — analisi verificata

Dati della squadra del proprietario del progetto (Top Eleven 2027, UI italiana).
Questa cartella è la **memoria fra sessioni**: prima esisteva solo nella cronologia
di una conversazione e sarebbe andata persa.

Ogni numero qui sotto è stato **ricalcolato dai file JSON di questa cartella**.
Dove un dato manca, è scritto che manca.

## File

| file | contenuto |
|---|---|
| `referti.json` | 8 referti partita completi (4 schede: generale, occasioni, passaggi, duelli) |
| `formazioni.json` | 18 schermate formazione (9 partite × 2 squadre) con posizioni sulla griglia |
| `mentori.json` | 6 schede mentore lette dal gioco |
| `rosa.json` | rosa derivata dalle formazioni: ruoli, presenze, voto medio, corsia prevalente |
| `analisi.json` | gli aggregati qui sotto, in forma leggibile da un programma |

## Il risultato che regge: incanalare il gioco al centro

È la correlazione più forte nei dati, su 8 partite.

| attacco centrale del Milan | partite | gol fatti | gol subiti |
|---|---|---|---|
| **≥ 60%** | 5 | **3,4** | **1,4** |
| < 60% | 3 | 2,0 | 3,7 |

Le cinque partite sopra il 60% sono Benfica (68%, 4-0), Bitlis Tatvan (75%, 4-2),
Ivana FC (62%, 3-2), FV L.A. (60%, 1-2), Napoli (76%, 5-1).
Le tre sotto sono Manchester United (0%, 0-7), Soyyigit (39%, 5-4), Steinbach (35%, 1-0).

**Attenzione a non invertire causa ed effetto.** Non è dimostrato che *impostare*
il gioco al centro produca quel rendimento: il dato registra dove il gioco è
*finito*, non cosa era stato impostato prima del fischio d'inizio. Con il Manchester
United (GEN −18,3) lo 0% centrale è più probabilmente una conseguenza della
superiorità avversaria che una scelta. Serve annotare le impostazioni tattiche al
calcio d'inizio per sciogliere il dubbio.

## Dove ci attaccano

Distribuzione media degli attacchi avversari, normalizzata sulle fasce del Milan.

| sinistra | centro | destra |
|---|---|---|
| 22,0 | **52,0** | 26,2 |

Il centro assorbe **metà** degli attacchi in ogni partita. Le due fasce sono
sostanzialmente simmetriche: la destra prende 4 punti più della sinistra, uno
scarto reale ma modesto, non un varco.

> **Correzione rispetto a un'analisi precedente.** In una sessione anteriore era
> circolato il numero "corsia destra −7,4, la più attaccata". Ricalcolato in tre
> modi diversi sui dati persistiti, **non si riproduce**: il differenziale di
> attacco dà destra +0,9, quello dei duelli vinti dà destra +3,4, e la
> distribuzione avversaria dà il centro come corsia dominante. Il numero veniva da
> un calcolo non conservato. **Non usarlo.**

Resta vero il fatto *strutturale*: Reynisson e Bone occupano entrambi la corsia
destra (`riga_prevalente: bassa` per tutti e due in `rosa.json`). Ma nei dati non
si misura una perdita difensiva su quel lato. È una configurazione da tenere
d'occhio, non un problema accertato.

## Regola di orientamento — indispensabile per leggere i diagrammi

La riga in alto del diagramma **non è sempre la stessa fascia**:

- squadra di **casa** → attacca verso destra → riga alta = fascia **SINISTRA**
- squadra in **trasferta** → attacca verso sinistra → riga alta = fascia **DESTRA**

Confrontare più partite senza normalizzare significa sommare fasce opposte.
Per stabilire il verso, cerca un ruolo monolaterale (DL, DR, ML, MR) nella
formazione: se il DL sta in alto, allora in alto è sinistra.

I diagrammi a zone sono **distribuzioni**, non percentuali di successo: le tre
corsie sommano sempre a 100. "6% di duelli vinti in quella zona" significa che
il 6% dei duelli vinti è avvenuto lì, non che se ne vince il 6%.

## Leggere un giocatore

Ignora il GEN complessivo e guarda il **blocco del ruolo**: un terzino con DIFESA
149 e ATTACCO 87 mostra GEN 118, ma come difensore vale 149. La media è zavorrata
da attributi che nel suo ruolo non contano. Vale anche per i portieri: conta il
blocco "Difesa della porta", non il totale.

## Buchi noti nei dati

Da colmare prima di trarre conclusioni più forti:

1. **Skogens IF 0-5 non è in `referti.json`.** Analizzata dagli screenshot ma mai
   trascritta. È l'anomalia più interessante del campione — GEN quasi pari (−0,9)
   e sconfitta pesante — e attualmente manca. Gli aggregati qui sopra sono su 8
   partite, non 9. Alcune cifre citate in passato (1,5 fatti / 4,0 subiti sotto il
   60% centrale) includevano lo Skogens e quindi non corrispondono a questi file.
2. **`gen` è `null` per tutti i 19 giocatori** in `rosa.json`: la schermata
   formazione non lo espone. Serve la scheda del singolo giocatore.
3. **Impostazioni tattiche al calcio d'inizio mai registrate.** Senza, la
   correlazione centrale resta descrittiva e non diventa una leva.
4. **`intercetti` mancante in 4 referti, `parate` in 3** — screenshot tagliati
   sull'ultima riga.
5. **Referto FV L.A.: attacchi avversari 0/100/0.** Lettura degenere, da
   riverificare sull'immagine originale.
6. **Forza dell'avversario assente** per diverse partite.

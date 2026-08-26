# Dossier AC Milan — analisi verificata

> ## Avvertenza sul campione — leggere prima di tutto il resto
>
> **Questo dossier non e' un campione rappresentativo della stagione.**
>
> La schermata "Statistiche stagionali" del club dice: 21 partite, 18 vittorie,
> 0 pareggi, 3 sconfitte, **130 gol fatti e 23 subiti** (6,2 e 1,1 a partita).
> I 10 referti qui dentro fanno 29 gol fatti e 24 subiti (2,9 e 2,4).
>
> | | dossier (10) | stagione (21) |
> |---|---|---|
> | gol fatti a partita | 2,9 | **6,2** |
> | gol subiti a partita | 2,4 | **1,1** |
> | quota sconfitte | **30%** | 14% |
> | sconfitte catturate | **3 su 3 = 100%** | |
> | vittorie catturate | 7 su 18 = 39% | |
>
> Il campione contiene **quasi il 100% degli eventi negativi e il 22% di quelli
> positivi**: il negativo e' sovrarappresentato di circa **4,7 volte**. Il GEN
> medio degli avversari qui dentro e' 118,1 contro 116,6 del Milan: sono quasi
> solo partite alla pari o in svantaggio, mentre la stagione e' fatta in
> maggioranza di avversari nettamente inferiori.
>
> **Cosa ne consegue.** Ogni confronto "vittorie contro sconfitte" costruito su
> questi dati e' in parte **tautologico**: avendo catturato tutte le sconfitte
> della stagione, qualunque metrica che distingue le partite perse da quelle
> vinte apparira' come una scoperta. Le medie per partita sottostimano l'attacco
> di oltre il 50% e sovrastimano i gol subiti di 2,2 volte.
>
> Non e' nemmeno chiuso **se questi 10 referti appartengano alla stagione delle
> 21 partite**: i 24 gol subiti qui superano i 23 dell'intera stagione, e nessuna
> esclusione di una o tre partite riconcilia i 130 gol fatti. Serve l'etichetta
> di competizione su ciascun referto.
>
> Resta valido, perche' e' geometria e non statistica: la **regola di
> orientamento** del diagramma. E restano ritirate, a maggior ragione, le
> ipotesi gia' segnate come ritirate.



Dati della squadra del proprietario del progetto (Top Eleven 2027, UI italiana).
Questa cartella è la **memoria fra sessioni**.

Ogni numero qui sotto è **ricalcolato dai file JSON di questa cartella**, su
**10 partite**. Dove un dato manca, è scritto che manca.

## File

| file | contenuto |
|---|---|
| `referti.json` | 10 referti partita |
| `formazioni.json` | 18 schermate formazione (9 partite × 2 squadre) con posizioni e GEN squadra |
| `mentori.json` | 6 schede mentore lette dal gioco |
| `rosa.json` | rosa derivata: ruoli, presenze, voto medio, corsia prevalente |
| `analisi.json` | gli aggregati qui sotto, in forma leggibile da un programma |
| `PROMPT-AVVERSARIO.txt` | prompt pronto da incollare con lo screenshot di un avversario |
| `PROTOCOLLO-CATTURA.md` | checklist a due fermate per registrare le partite nuove |

## Il risultato più solido: incanalare il gioco al centro

| attacco centrale del Milan | partite | gol fatti | gol subiti |
|---|---|---|---|
| **≥ 60%** | 6 | **3,8** | **1,3** |
| < 60% | 4 | 1,5 | 4,0 |

Sopra il 60%: Efthymis 93% (6-1), Napoli 76% (5-1), Bitlis 75% (4-2), Benfica 68%
(4-0), Ivana 62% (3-2), FV L.A. 60% (1-2).
Sotto: Skogens 40% (0-5), Soyyigit 39% (5-4), Steinbach 35% (1-0), Manchester
United 0% (0-7).

Il caso estremo conferma la direzione: **93% centrale contro l'Efthymis FC, 6-1**,
con 17 tiri a 1.

> **Attenzione: questo confronto e' in gran parte tautologico.** Il gruppo "sotto
> il 60%" e' composto per tre quarti dalle sconfitte, e il dossier contiene
> **tutte e tre** le sconfitte della stagione insieme a meno di meta' delle
> vittorie. Stai in buona parte confrontando le partite perse con quelle vinte e
> chiamando "centro" la differenza. Non e' solo un dubbio di causalita': e' un
> problema di **selezione del campione**.
>
> L'identita' centrale resta sostenuta da argomenti **indipendenti da questa
> tabella**: zero occasioni da cross in 7 partite su 9, il capocannoniere che
> segna 39 gol da AMC, e la quota di assist del rifinitore destro identica fra
> campione e stagione (20,8% contro 22,3%). Usa quelli, non i numeri qui sopra.

**Resta un dubbio di causalità.** Il dato registra dove il gioco è *finito*, non
cosa era stato impostato al fischio d'inizio. Con il Manchester United (GEN −18,3)
lo 0% centrale è più probabilmente una conseguenza della superiorità avversaria
che una scelta. Servono le impostazioni annotate prima della partita.

## I duelli sono la leva

A parità di GEN, è la variabile che separa i risultati opposti:

| partita | GEN Milan / avv. | duelli vinti | esito |
|---|---|---|---|
| Efthymis FC | — | **75% – 42%** | 6-1 |
| Napoli | 119,0 / 120,5 | **71 – 56** | 5-1 |
| FV L.A. | 117,3 / 127,4 | 65 – 64 | 1-2 |
| Skogens IF | 119,0 / 119,9 | 69% – **82%** | 0-5 |

Napoli e Skogens hanno lo stesso deficit di GEN — un punto e mezzo, un punto — ed
esiti opposti. Nella vittoria domini i duelli, nella sconfitta li perdi.

**Non è dimostrato che `Stile contrasti: Duro` faccia salire quel numero.** Contro
l'Efthymis il 75% è stato ottenuto con `Normale`, facendo **meno falli
dell'avversario** (15 contro 23). L'ipotesi che servisse il contrasto duro è stata
proposta e ritirata.

## La corsia destra: il caso Skogens

| media 10 partite | sinistra | centro | destra |
|---|---|---|---|
| dove ci attaccano | 21,4 | **51,3** | 27,5 |

In media il centro assorbe metà degli attacchi e le fasce sono quasi simmetriche.
**Ma la media nasconde il caso peggiore.**

> **Correzione di una correzione.** In una prima analisi era circolato il numero
> "corsia destra −7,4, la più attaccata". Non è riproducibile e resta da non usare.
> In una seconda analisi ho concluso che **nessuna corsia fosse sfondata** — e
> quella conclusione era prematura, perché il referto dello Skogens IF non era
> ancora stato trascritto. Contro lo Skogens la corsia **destra ha assorbito il
> 55% degli attacchi**, il valore più alto del campione, e la partita è finita
> **0-5**.

Quindi: nessuna fragilità *cronica* sulla destra, ma la peggiore sconfitta del
campione è arrivata proprio da lì. Va trattata come uno scenario possibile contro
avversari che sanno cercarla, non come un difetto permanente.

Il contorno di quella partita: mentore avversario **Rubén Herrera** (contropiede),
possesso Milan **54%**, intercetti **4 contro 18**. Avevi la palla e la perdevi in
uscita; loro ripartivano sulla tua destra.

## Regola di orientamento — indispensabile

La riga in alto del diagramma **non è sempre la stessa fascia**:

- squadra di **casa** → attacca verso destra → riga alta = fascia **SINISTRA**
- squadra in **trasferta** → attacca verso sinistra → riga alta = fascia **DESTRA**

Per stabilire il verso, cerca un ruolo monolaterale (DL, DR, ML, MR) nella
formazione: se il DL sta in alto, allora in alto è sinistra.

I diagrammi a zone sono **distribuzioni**: le tre corsie sommano sempre a 100.

## Ipotesi cadute

- **"Palla corta perché i palloni lunghi fanno perdere."** Nasceva dal confronto
  Napoli (0 lanci lunghi, vinta) / FV L.A. (9, persa). Contro l'Efthymis il Milan
  ha giocato il **36% di palloni lunghi e vinto 6-1**, con precisione passaggi 75%
  contro 40%. Contava la qualità del passaggio, non la lunghezza.
- **"Contrasti Duro per alzare i duelli."** Vedi sopra.

## Leggere un giocatore

Ignora il GEN complessivo e guarda il **blocco del ruolo**: un terzino con DIFESA
149 e ATTACCO 87 mostra GEN 118, ma come difensore vale 149. Vale anche per i
portieri: conta il blocco "Difesa della porta", non il totale.

## Buchi noti nei dati

1. **Scheda OCCASIONI dello Skogens mai fotografata**: tiri, corner e precisione
   di quella partita restano ignoti.
2. **`gen` è `null` per tutti i 19 giocatori** in `rosa.json`: la schermata
   formazione non lo espone. Unico GEN individuale noto: **Michos 150**.
3. **Impostazioni tattiche al calcio d'inizio mai registrate.** Senza, la
   correlazione centrale resta descrittiva e non diventa una leva.
4. **`intercetti` mancante in 4 referti, `parate` in 3.**
5. **Referto FV L.A.: attacchi avversari 0/100/0.** Lettura degenere.
6. **Forza dell'avversario assente** per diverse partite.

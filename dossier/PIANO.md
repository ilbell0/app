# Piano per rimettere a posto la squadra

Scritto il 26/08/2026, dopo l'esplorazione completa dell'applicazione.
Fonti: `app_mappa.json`, `stili_gioco.json`, `assetto_corrente.json`, `attributi.json`.

## Dove sei davvero

| | |
|---|---|
| Campionato | **2°**, 15 partite, 14V-0P-1S, differenza reti **+100** (la migliore) |
| Capolista | Skogens IF, **15 vittorie su 15**, +99, 3 punti avanti |
| L'unica sconfitta | contro lo Skogens, **0-5** |
| Carriera Classificato | 226 partite, **38% di vittorie**, 578 gol |
| GEN | 124,4 · equilibrio 9,9 · livello club 123 · età media 24,8 |

**Le due cifre non si contraddicono.** Il 14-su-15 misura un campionato con molti
avversari deboli; il 38% misura partite contro pari livello. La verità operativa
e' la seconda: **contro chi vale quanto te, perdi piu' di quanto vinci.**

E il problema ha un nome: **Skogens IF**. E' l'unico che ti ha battuto in
campionato, lo ha fatto 5-0, ed e' imbattuto. Tutto il resto del piano serve a
quella partita.

## I quattro problemi veri

### 1. Bone spreca uno stile Avanzato ×3

Ha **FALSA ALA**, livello Avanzato, effetto ×3. Lo stile richiede **ML o MR**.
Lui gioca **AMR**: icona grigia, spento, zero effetto.

E' l'unico difetto strutturale dell'assetto. Gli altri quattro stili sono
attivi: Sacchetti (Falso Nueve, **Maestro ×4**), Michos (Regista ×2), Romero
(Da area ad area ×2), Micheltorena (Comandante d'area ×2).

**Il vincolo**: Romero richiede `MC` e soltanto quello. Michos accetta MC o DMC.
Sacchetti accetta ST o AMC. Quindi serve un modulo con `MC` + `MC/DMC` + `ML o
MR` + `ST/AMC`.

Il `4-4-1-1` (`ML MC MC MR AMC ST`) li accende tutti e cinque. Il prezzo e' che
Gabay sale a ML, il posto di `DL` va a Portillo e il secondo `DC` a **Sadin**
(Passaggio 53, Creativita' 12), che rompe la costruzione dal basso.

**Non e' una decisione da prendere a tavolino.** Uno stile ×3 contro una
prima uscita peggiore: si misura, non si deduce. Vedi il punto Metodo.

### 2. Non hai attaccanti, e ce n'e' uno disponibile ora

L'unico ST puro in rosa e' **Onisei, GEN 45**. Sacchetti e Garcia sono AMC/AML
prestati al ruolo.

Nel **Centro Giovani Talenti**, in scadenza tra 1g 13h: **F. Costantini, ST, 5,5
stelle, 59 token**. Ne hai **44**. Mancano 15, e la sezione GRATIS del negozio
offre solo incarichi pubblicitari: non li recuperi in tempo senza spendere.

**Decisione richiesta**: 15 token valgono un ST da 5,5 stelle a 17 anni? Se la
risposta e' si', e' l'acquisto piu' sensato disponibile — molto piu' dello
scambio proposto dall'assistente (Montaroup 101 → Henriquez 112 per 759M **+ 77
token**, che non puoi permetterti e migliora una riserva).

### 3. Gradi Giocatore: il potenziamento che stai ignorando

Incremento **permanente** degli attributi chiave.

| grado | token | incremento | giocatori idonei |
|---|---|---|---|
| Raro | 290 | +10 | 1 |
| **Elite** | 47 | **+30** | **8** |
| Stellare | 6 | +50 | 7 |
| Maestro | 19 | +80 | 3 |
| Epico | 14 | +120 | 0 |

Otto giocatori idonei al grado Elite, +30 permanenti ciascuno. **Da chiarire se
il numero e' quanti token possiedi o il costo unitario** — e' la prima cosa da
verificare, perche' cambia completamente la portata della mossa.

### 4. L'affiatamento e' a 38 su 48

Lo dice la checklist di preparazione del gioco stesso. Insieme a: 3 ammoniti fra
i titolari, titolari non riposati, morale migliorabile. Hai **7 sessioni di
allenamento** disponibili e **22 recuperi condizione** e **8 booster morale**.

Nel Campus, il **Lab. Esercizi e' a livello 8** — la struttura piu' arretrata di
tutte (Stadio 15, Vivaio 17, Terapie 11). Presiede all'allenamento.

## Cosa fare, in ordine

1. **Oggi, partita con oussama Fc** (GEN 64,9, segna 0,1 gol a partita): regime
   A, turnover totale. Non sprecare condizione dei titolari: stasera alle 21:52
   c'e' un'amichevole e i titolari hanno 3 ammoniti.
2. **Verificare i Gradi Giocatore**: token posseduti o costo? Se hai davvero 47
   token Elite, otto potenziamenti da +30 permanenti valgono piu' di qualsiasi
   acquisto sul mercato.
3. **Decidere su Costantini** entro 1g 13h.
4. **Spendere le 7 sessioni di allenamento** per alzare l'affiatamento da 38/48.
5. **Alzare il Lab. Esercizi**, la struttura che frena tutto il resto.
6. **Testare il 4-4-1-1** con il metodo qui sotto, non prima.

## Metodo: come si decide, d'ora in poi

Il protocollo di cattura e' operativo e il primo referto `protocollo: 2` e'
gia' registrato (oussama Fc, regime **A** dichiarato prima del risultato).

Per la questione Bone, l'esperimento e' questo:

- Due partite contro avversari di forza simile, entrambe in regime B.
- Partita 1: `4-1-2-3` attuale, Bone AMR, Falsa Ala spenta.
- Partita 2: `4-4-1-1`, Bone MR, Falsa Ala attiva, Sadin DC.
- Tutto il resto identico: stessi undici parametri, stesso mentore.
- Confronta tiri, occasioni, duelli, gol subiti.

**Usa i quattro slot modulo** (`MODULI DELLA ROSA`, pulsante in basso a sinistra
in FORMAZIONE): slot 1 la baseline, slot 2 la variante. Si alternano in un
click, senza rifare la formazione ogni volta.

## Quello che l'app ti da' gratis e non stavi usando

- **L'Anteprima Partita** espone modulo, XI completo con qualita', forma e
  reparti dell'avversario **prima del calcio d'inizio**. Il `PROMPT-AVVERSARIO`
  del dossier chiedeva di dedurre da uno screenshot cio' che e' gia' scritto li'.
- La scheda **Preparazione** e' una checklist pre-partita del gioco stesso:
  ammoniti, infortunati, riposo, morale, affiatamento, con i pulsanti per
  correggere ciascuna voce.
- Il **meteo** e' esposto e non e' mai stato registrato in nessun referto.

## Buchi rimasti

- **Le frecce tattiche non sono state trovate.** I quattro toggle della barra
  destra in FORMAZIONE sono viste (ruoli, condizione e morale, due
  sovrapposizioni), non impostazioni. Il protocollo ne chiede l'annotazione: o
  stanno altrove, o in questa versione non esistono.
- **Gradi Giocatore**: significato del numero accanto a ogni grado.
- Le sconfitte **1-3 (Villagers)** e **0-5 (FC Hooligan)** del 25-26/8 non sono
  di campionato. Manca l'etichetta di competizione: vanno identificate.

## Aggiornamento del 26/08, dopo l'esplorazione completa

### Il capitano e' in panchina

Calci piazzati (ROSA > FORMAZIONE > quarto quadratino, meta' scarpa):

| incarico | assegnato a | |
|---|---|---|
| Angoli D e S | Bone | corretto, Cross 180 |
| Punizioni D e S | Sacchetti | corretto, Tiro 240 |
| Rigori | Sacchetti | corretto, Finalizzazione 234 |
| **Capitano** | **Sadin** | **da cambiare: GEN 99, non titolare** |

I tiratori sono assegnati bene. Il capitano no: **Sadin non e' in formazione**,
quindi qualunque effetto abbia la fascia, in campo non c'e'. I candidati sono
**Michos (152)** o **Sacchetti (151)**: i due piu' forti, titolari fissi,
entrambi con uno stile di gioco attivo.

### I quattro slot sono tutti occupati

| slot | modulo |
|---|---|
| 1 | 4-1-2-3 Offensiva (= rosa attuale) |
| 2 | 3-4-2-1 Offensiva |
| 3 | 4-1-2-3 Offensiva (duplicato del modulo in uso) |
| 4 | 4-2-3-1 Offensiva |

Per provare il 4-4-1-1 bisogna sovrascriverne uno. Il candidato naturale e' il
**3**, che duplica quello gia' presente nello slot 1.

Ricorda che ogni slot salva **cinque** cose: formazione, modulo, mentalita' dei
giocatori, tiratori dei calci piazzati e tattiche.

### Il modulo si cambia trascinando

Non esiste un selettore: si spostano i giocatori dentro il campo in FORMAZIONE e
il gioco riconosce il modulo risultante.

# Handoff — stato della discussione su AC Milan (Top Eleven 2027)

Documento di passaggio di consegne. Leggi anche `SISTEMA.md` e `ANALISI.md`.
Aggiornato al 20/08/2026.

## 1. Il dato nuovo: le qualità individuali

Fino a ieri `rosa.json` aveva `gen: null` per tutti e 19 i giocatori. Dalla
schermata **ROSA → Titolari** (colonne DIF / ATT / FIS / QUALITÀ) ora si leggono.
**Non sono ancora state scritte nei file JSON: è il primo lavoro da fare.**

| giocatore | ruoli | DIF | ATT | FIS | QUALITÀ |
|---|---|---|---|---|---|
| N. Michos | MC/DMC | 168 | 142 | 143 | **151** |
| S. Sacchetti | AMC/ST | 119 | **196** | 133 | **149** |
| J. Bone | MR/AMR/AMC | 117 | 156 | 131 | **135** |
| D. Romero | DMC/MC | **173** | 101 | 117 | **131** |
| Þ. Reynisson | DR/DC | 150 | 88 | 117 | 119 |
| C. Micheltorena | GK | – | – | 99 | 118 |
| M. Gómez Vara | MC/AMC/AMR | 135 | 136 | 82 | 118 |
| J. Portillo | DL/DC | 131 | 96 | 102 | 110 |
| R. García | AMR/ST/AML | 90 | 128 | 108 | 108 |
| P. Boncompagni | MC | 111 | 100 | 99 | 103 |
| O. Gabay | DL/ML/AML | 107 | 100 | 96 | 101 |
| A. Montaroup | AMC | 89 | 113 | 98 | 100 |
| G. Sadin | DR/DC/DL | 153 | 61 | 83 | 99 |
| D. McLoughlin | AMC/AML | 73 | 115 | 95 | 94 |
| M. Matias | GK | – | – | 62 | 92 |
| M. Willis | DMC/DC/MC | 116 | 66 | 81 | 88 |
| J. Hernández | MR/DR | 83 | 88 | 80 | 84 |
| C. Kim | DL | 100 | 62 | 74 | 79 |

Statistiche stagionali notevoli: **Sacchetti 43 gol**, **Bone 32 assist e 18 gol**,
**Gómez Vara 10 gol e 10 assist**, **Gabay 23 assist**.

## 2. Il sistema in vigore: tre regimi

Il criterio e' il **differenziale** di GEN, non il valore assoluto dell'avversario.

| differenziale | cosa fare |
|---|---|
| sei molto sopra (avversario sotto 100 GEN) | **turnover totale**, il modulo e' irrilevante |
| pari o leggermente sopra | **4-3-3 titolare**, Mentalita' Offensiva |
| sei sotto di piu' di 3 punti | **4-1-4-1 blocco basso**, Difensiva, Pressing Basso, Contropiede |

Dettaglio completo, con gli undici e tutti gli 11 parametri per ciascun regime,
in `SISTEMA.md`.

**Il motivo del regime C**: contro squadre piu' forti il possesso non aiuta. Contro
lo Skogens il Milan aveva il **54% di possesso** e ha perso **0-5**; con FV L.A.
possesso 50-50, persa 1-2.

## 3. Cosa e' stato RITIRATO — non riproporlo

Elenco di ipotesi mie che i dati hanno smentito. Se ricompaiono, e' un errore.

- **"Corsia destra −7,4, la piu' attaccata."** Numero mai riproducibile.
- **"Compra un portiere."** Micheltorena subisce **1,1 gol a partita** in stagione.
  Il suo 6,21 di voto medio veniva da un campione fatto solo di partite difficili.
- **"Compra una punta."** Sacchetti fa **43 gol da AMC**. La punta c'e' gia'.
- **"Stile contrasti Duro per alzare i duelli."** Il 75% di duelli vinti contro
  l'Efthymis e' arrivato con `Normale`, facendo meno falli dell'avversario.
- **"Palla corta perche' i lanci lunghi fanno perdere."** Contro l'Efthymis: 36%
  di palloni lunghi e vittoria 6-1.
- **"Il gioco centrale rende (3,8 gol contro 1,5)."** Confronto in gran parte
  **tautologico** (vedi punto 4), e smentito da tre casi: 9-0 col Steinbach al 31%
  centrale, 12-0 col Bad Lausick, 7-0 col Babylon al 55%.
- **"Il modulo e' il 4-1-2-1-2."** L'assetto reale della squadra e' il **4-3-3**,
  e ha prodotto 18 vittorie su 21.

## 4. Il difetto del campione — leggere prima di analizzare

`referti.json` contiene **10 partite su oltre 30 giocate**, e include **tutte e tre
le sconfitte** della stagione con meno di meta' delle vittorie. Il negativo e'
sovrarappresentato di circa **4,7 volte**.

Conseguenza: **ogni confronto vittorie/sconfitte costruito su questo campione e'
in parte tautologico.** Avendo catturato tutte le sconfitte, qualunque metrica che
le distingue dalle vittorie sembrera' una scoperta.

Inoltre la stagione e' **bimodale**: gli avversari vanno da GEN **20,5**
(FC Bad Lausick, difesa 7,1, club abbandonato) a **132,0** (Manchester United).
Le medie stagionali — 6,2 gol fatti a partita — non descrivono nessuna partita
reale. **Non mescolare le due popolazioni.**

Nel calendario, l'**icona con due sagome** marca le **amichevoli**: non contano
nelle statistiche stagionali. Il 5-1 col Napoli era un'amichevole.

## 5. Questione aperta: l'equilibrio di formazione

Il gioco espone un indicatore **"Equilibrio di formazione"** da 0 a 10, che misura
quanto sono **simili fra loro** le qualita' degli undici in campo. Dichiara di
migliorare le probabilita' di possesso.

Stato attuale: **GEN 122,0 con equilibrio 9,8**.

L'utente vuole arrivare a **10,0**, esplicitamente anche a costo del GEN.
La formazione con la dispersione minima ottenibile e' un **4-3-2-1**:

> Matias (92) — Portillo (110), Willis (88), Sadin (99), Reynisson (119) —
> Gabay (101), Boncompagni (103), Gómez Vara (118) — McLoughlin (94),
> Montaroup (100) — García (108)

Scarto 31 punti invece di 52; GEN atteso ~103. Restano fuori i quattro migliori
(Michos 151, Sacchetti 149, Bone 135, Romero 131), che sono esattamente quelli che
rompono l'equilibrio.

**Non e' verificato che dia 10,0**: la formula non e' pubblica.

**Esperimento proposto e non ancora eseguito**: giocare una partita con questo
undici e una con quello da GEN 122 contro avversari di forza simile, e confrontare
possesso, duelli e risultato. Servirebbe a capire quanto pesa davvero l'equilibrio.

## 6. Cosa manca nei dati

1. **Le impostazioni tattiche al calcio d'inizio** — mai registrate in nessuna
   partita. Senza, ogni correlazione resta descrittiva.
2. **Le frecce** — la schermata FORMAZIONI non le mostra: le frecce rosse che vi
   compaiono sono le **sostituzioni**. Vanno annotate prima del fischio d'inizio.
3. **L'etichetta di competizione** per ogni referto. I 10 referti attuali mescolano
   campionato, Campionato Elite, coppa e amichevoli.
4. **Referti presi in ordine dal calendario**, non scelti dall'utente: e' la
   selezione a monte che ha viziato tutta l'analisi.
5. Scheda OCCASIONI dello Skogens, mai fotografata.
6. Le qualita' individuali del punto 1, da scrivere in `rosa.json`.

## 7. Seconda squadra (esperimenti)

L'utente gestisce un secondo club per prove. Rosa molto diversa: un solo
fuoriclasse (**P. Ivanov, AMC, qualita' 135, ATT 154**), due terzini nuovi da 95
(Starbuck DL, da Silva DR), **Rodrigues MC 105** e **Bouchaala DMC 95**, e due
difensori centrali deboli (El Saidi 50, Ricci 52).

Assetto consigliato: **4-1-2-1-2 a rombo**, con i terzini a dare l'ampiezza che il
rombo non ha. Prossimo acquisto indicato: **un difensore centrale**.

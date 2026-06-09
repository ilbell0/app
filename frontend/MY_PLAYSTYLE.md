# Il mio modo di giocare — Tiki-Taka Possessivo

> **Stato: BOZZA v0.1** — base da correggere e personalizzare insieme.
> Compilata da Claude il 2026-06-10 partendo dalle 2 stories tiki-taka già nei dataset (`tiki-taka-fanatic`, `tiki-taka-barca`), dalle `META_TACTICS` trending del 2026 e dalla conoscenza calcistica del Barça 2010/11.
> Ogni voce ha **[CONFERMARE]**, **[INTEGRARE]** o **[FISSO]** così sai cosa devi rivedere.

---

## 0. Indice categorie

1. [Filosofia & Identità](#1-filosofia--identità)
2. [DNA della rosa (ruoli per posizione)](#2-dna-della-rosa)
3. [Repertorio moduli](#3-repertorio-moduli)
4. [Setup tattico base](#4-setup-tattico-base)
5. [Frecce & movimenti](#5-frecce--movimenti)
6. [Le 4 fasi di gioco](#6-le-4-fasi-di-gioco)
7. [Playbook scenari di partita](#7-playbook-scenari-di-partita)
8. [Counter ai moduli ostici](#8-counter-ai-moduli-ostici)
9. [Sostituzioni & cambi a partita in corso](#9-sostituzioni--cambi-a-partita-in-corso)
10. [Ritmo stagionale & token](#10-ritmo-stagionale--token)
11. [Errori da NON fare (autoregole)](#11-errori-da-non-fare)
12. [KPI — sto giocando il mio stile?](#12-kpi)
13. [Checklist pre-partita 60 secondi](#13-checklist-pre-partita)

Sezione finale: [Spunti & migliorie strutturali](#spunti--migliorie-strutturali)

---

## 1. Filosofia & Identità

**Idea cardine**: il possesso è una forma di difesa. Se ho la palla, l'avversario non segna.

Tre principi non negoziabili **[CONFERMARE]**:
- **Pazienza > fretta**: 25+ passaggi per azione, vincere 1-0 al 88° è perfetto.
- **Il numero non conta**: 75% possesso e 18-3 nei tiri possono finire 1-0. Va bene così.
- **Stancare l'avversario**: nel secondo tempo crolla, ed è lì che decido la partita.

Inspirazione: **Barcellona 2010/11 di Guardiola** (vedere story `tiki-taka-barca` nel dataset). Modelli di riferimento: `realTeams.json` → "Pep City", "Pep Bayern".

---

## 2. DNA della rosa

Profilo titolari ideali (rosa ≥ 6 stelle). Riferimenti `playerRoles.json` e `specialAbilities.json` già nell'app.

| Posizione | Ruolo (PLAYER_ROLES) | Attributi chiave | Abilità speciali da cercare |
|---|---|---|---|
| GK | Sweeper Keeper | Riflessi, Uscite, Posizionamento | One-on-One (parate uno-contro-uno) |
| DC sinistro | Ball-Playing Defender ("Piqué") | Passaggio, Marcatura, Creatività | Playmaker |
| DC destro | No-Nonsense Centre-Back | Contrasto, Marcatura, Forza | Defensive Wall |
| DL / DR | Full-Back (NO Wing-Back) | Marcatura, Velocità, Resistenza | — |
| DMC | Deep-Lying Playmaker ("Busquets") | Passaggio, Posizionamento, Visione | Playmaker, Anchor Man |
| MC sinistro | Mezzala creativa ("Xavi") | Passaggio, Creatività, Visione | Playmaker |
| MC destro | Mezzala incursore ("Iniesta") | Dribbling, Creatività, Tiro | Shadow Striker |
| AML | Inverted Winger / Dribbler | Dribbling, Velocità, Tiro | One-on-One Scoring, Dual Position |
| AMR | Inverted Winger / Dribbler | Dribbling, Velocità, Tiro | One-on-One Scoring, Dual Position |
| ST | False Nine ("Messi") | Finalizzazione, Creatività, Visione | Goal Poacher, Free Kick Specialist |

**Regola d'oro [FISSO]**: il giocatore più forte della rosa è il **DMC playmaker**, non l'attaccante.

**Da evitare in rosa [CONFERMARE]**:
- Attaccanti "tank" lenti (non servono al sistema).
- Terzini Wing-Back (sovrapposizioni rischiano la perdita palla).
- AMC puro nel 4-3-3 (gli MC fanno già quel lavoro).

---

## 3. Repertorio moduli

Tengo **3 moduli + 1 di emergenza**, mai di più.

| # | Modulo | Quando lo uso | Story di riferimento |
|---|---|---|---|
| 1 | **4-3-3 puro** | Default, vs avversari pari o deboli | `tiki-taka-barca` |
| 2 | **3-1-5-1 AMC** | Vs avversari forti / pressing alto | `tiki-taka-fanatic` |
| 3 | **4-1-2-1-2 ND** | Plan B quando subisco transizioni veloci | meta tactic tier S |
| 4 | **3-4-1-2** *(emergenza)* | Solo da 0-2 in poi per rimonta | `comeback-with-arrows` |

**Non uso mai**: 5-4-1 Flat (non è il mio DNA), 4-4-2 Classic (poca creatività centrale).

---

## 4. Setup tattico base

Setup del **4-3-3 default**. Le varianti sui moduli #2 e #3 stanno in appendice **[INTEGRARE]**.

| Voce | Valore | Note |
|---|---|---|
| Mentalità | **Normale** | Tutta la partita. Cambio solo per emergenze (vedi §7). |
| Passaggi | **Al Centro** | Asse DMC → MC → ST/AMC. |
| Stile | **Corto** | Mai lungo, perdo identità. |
| Pressing | **Basso** | Il possesso *è* il pressing. |
| Marcatura | **A Zona** | Tengo blocco compatto. |
| Fuorigioco | **OFF** | Salvo difesa con 90%+ velocità. **[CONFERMARE]** |
| Tackling | **Misto** | I duri perdono palla → contropiede subito. |
| Force counter-attack | **OFF** | Antitetico al sistema. |
| Play wide | **OFF** | Il centro è la mia autostrada. |

---

## 5. Frecce & movimenti

**Setup frecce del 4-3-3 (FISSO)**:
- **Freccia BLU sul DMC**: non negoziabile. Busquets non sale mai. Senza questa freccia il sistema crolla.
- **Nessuna freccia sulle ali**: nel 4-3-3 sono già AML/AMR, vivono alte.
- **Nessuna freccia sui terzini**: non devono sovrapporre.
- **Neutre su tutto il resto**.

**Variante 3-1-5-1 [CONFERMARE]**:
- Blu sul DMC (sempre).
- Rosso sull'AMC (è il finalizzatore reale del sistema).
- Neutre sugli ML/MR larghi.

**Variante quando l'avversario chiude (5-4-1 Flat) [CONFERMARE]**:
- Rosso sui due terzini (allargano forzando il blocco basso).
- Cambio passaggi a "Sulle Fasce" temporaneamente.

---

## 6. Le 4 fasi di gioco

Cosa **deve** succedere in ognuna delle 4 fasi.

### A) Costruzione (1/3 difensivo)
- Superiorità numerica 3 vs 2 in uscita: GK + 2 DC contro le punte avversarie.
- Se l'avversario pressa con 3 attaccanti → il DMC si abbassa tra i 2 DC (build-up a 3+1 "alla Busquets").
- **Mai** lanci lunghi dal GK.

### B) Sviluppo (centrocampo)
- Triangoli MC ↔ DMC ↔ MC: 3-4 passaggi rapidi per portare avanti la linea.
- Terzini larghi e **bassi** (no sovrapposizioni: aprono la linea).
- AML/AMR aspettano alti, non vengono incontro.

### C) Finalizzazione (1/3 offensivo)
- Il Falso 9 **si abbassa**: libera lo spazio centrale.
- Inserimento di un'ala (AML o AMR) nello spazio liberato.
- Mezzala lato debole arriva in area (movimento "Iniesta").
- KPI di sistema sano: **25+ passaggi per azione** che finisce nel terzo offensivo.

### D) Non-possesso (riconquista)
- **6 secondi**: regola Guardiola. Pressing aggressivo solo nei primi 6" dopo la perdita.
- Se la palla non torna in 6" → ritorno in posizione, blocco basso e ricomincio.
- **Mai** inseguire individualmente (perdi forma).

---

## 7. Playbook scenari di partita

### Per livello stelle avversario

| Avversario | Modulo | Mentalità | Note |
|---|---|---|---|
| Forte (+1/+2 stelle) | 3-1-5-1 AMC | Difensiva → Normale al 60' | Possesso assoluto, accetto 1-0 |
| Pari | 4-3-3 puro | Normale | Default |
| Debole (-1 stella) | 4-3-3 puro | Normale → Offensiva al 60' | Eviti il fattore-condizione |

### Per situazione di punteggio

| Stato | Minuto | Azione |
|---|---|---|
| 0-0 | 1-60 | Default, nessun cambio |
| In vantaggio 1-0 | 70'+ | Scendo a Difensiva, MANTENGO possesso (no chiusura "all'italiana") |
| In svantaggio 0-1 | 60'+ | Salgo a Offensiva, **NON** cambio modulo |
| In svantaggio 0-2 | 60'+ | **Cambio al 3-4-1-2** (vedere story `comeback-with-arrows`) |
| Pareggio cercato vs forte | 80'+ | Difensiva, sostituzione DC freschi |

---

## 8. Counter ai moduli ostici

I 5 moduli che mi danno fastidio e come reagire **[CONFERMARE/INTEGRARE]**:

| Avversario | Problema | Soluzione |
|---|---|---|
| **5-4-1 Flat** (bus parcheggiato) | Nessuno spazio centrale | Salgo a Offensiva dal 65', passaggi "Sulle Fasce" temporanei, freccia rossa su 1 terzino |
| **4-2-3-1 con DMC** | Sigla la mediana | Passo al 3-1-5-1, sovraccarico centrale 5v3 |
| **3-5-2 V** | Pressa la mia difesa a 4 | Sweeper Keeper alto, DMC si abbassa nella linea (build-up a 3+1) |
| **4-1-2-1-2 ND** | Centrale denso, palla mia non passa | Apro con ala inversa, passaggi al centro **non bastano** — accetto un setup ibrido |
| **4-3-3 Falso 9 (specchio)** | Lui fa il mio gioco | Vince chi ha DMC + AMC migliori. Bisogna superare lui sul DMC. |

> Cross-link: vedere `MATCHUP_MATRIX` (`matchupMatrix.json`) per i counter generici già nel dataset. Questi sono i miei counter **personalizzati** sopra a quelli base.

---

## 9. Sostituzioni & cambi a partita in corso

Le mie 3 sostituzioni standard nel 4-3-3 default **[CONFERMARE]**:

| Minuto | Trigger | Sostituzione | Perché |
|---|---|---|---|
| 60' | MC stanco (<70% condizione) | MC fresco con Playmaker | Mantenere precisione passaggio |
| 75' | Vincere 1-0 / 2-0 | DMC fresco entra per 1 mezzala | Chiudere lo spazio centrale |
| 85' | Vantaggio risicato vs forte | DC fresco per terzino offensivo | Difesa a 5 occulta |

**Regola [FISSO]**: mai sostituire un difensore mentre rimonto.

---

## 10. Ritmo stagionale & token

**Settimana tipo [CONFERMARE]**:
- **Lun-Mer**: rotazione (2 undici), allenamenti Passaggio+Creatività.
- **Gio**: partita campionato — undici titolare.
- **Ven-Sab**: cura condizione/morale, NO Allenamenti Rapidi.
- **Dom**: knockout / Coppa — uso eventuali Allenamenti Rapidi.

**Asta — chi cercare in ordine di priorità**:
1. **DMC Playmaker** giovane (16-19 anni) con Passaggio 80%+.
2. **MC creativa** under 21 con Creatività 85%+.
3. **AML/AMR dribbler** con piede inverso (sinistro a destra, destro a sinistra).
4. **DC Ball-Playing** giovane.
5. ST Falso 9 solo se libero a costo basso (il sistema funziona anche con un buon ST normale).

**Token — regole [CONFERMARE]**:
- **80% riservati ai knockout di Champions**: niente sprechi prima.
- **0 token su attaccanti puri**: il sistema crea occasioni senza bombardieri.
- **Salute > velocità**: prima rosa sana, poi inseguo l'asta.

---

## 11. Errori da NON fare

Autoregole, ognuna nasce da una "lezione" presa **[INTEGRARE: aggiungi le tue]**:

1. **Mai Offensiva dal 1° minuto** → brucio la condizione, finale in apnea.
2. **Mai cambiare modulo a partita in corso**, eccezione 0-2 + rimonta.
3. **Mai Allenamento Rapido** se la partita non è un knockout.
4. **Mai vendere il DMC playmaker**, neanche se mi offrono il triplo del valore.
5. **Mai sostituire un giocatore al 80%+ di possesso "perché stanco"** prima del 75'.
6. **Mai fuorigioco ON** se la mia difesa non ha 90%+ velocità.
7. **Mai inseguire palla individualmente** in fase difensiva.

---

## 12. KPI

Indicatori per capire **dal foglio statistiche** se sto giocando il mio stile (target a regime, non a partita).

| Metrica | Target | Sotto target = |
|---|---|---|
| Possesso medio | **≥ 65%** | non sto controllando il tempo |
| Passaggi completati | **≥ 88%** | sto rischiando troppo |
| Tiri totali | **≥ 2x avversario** | non sto finalizzando il possesso |
| Goal subiti / partita | **< 1.0** | la struttura difensiva ha buchi |
| Gol fatti / partita | **≥ 1.5** | il sistema è sterile (rivedere ali) |
| Passaggi per azione | **≥ 15** | troppo verticale, non è tiki-taka |

> Cross-link: tip pertinenti in `scoutTips.json` categoria "tactics" e "meta".

---

## 13. Checklist pre-partita

60 secondi prima del calcio d'inizio:

- [ ] Morale **80/80** sui titolari?
- [ ] Condizione **80/80** sui titolari?
- [ ] Modulo salvato e caricato?
- [ ] **Freccia BLU sul DMC** verificata?
- [ ] AML/AMR sono dribbler veri (non lenti)?
- [ ] Avversario ha DMC? → decide se 4-3-3 o 3-1-5-1
- [ ] Penalty Specialist e Free Kick Specialist sono in campo?

---

## Spunti & migliorie strutturali

Cose che ho notato strutturando il documento (per discutere insieme):

### Cosa funziona della struttura attuale

- Le 13 categorie sono distinte e non si sovrappongono.
- C'è un'ancora narrativa (Barça 2010/11) che dà identità.
- Cross-link verso dataset esistenti (`playerRoles.json`, `specialAbilities.json`, `matchupMatrix.json`, `scoutTips.json`) evitano duplicazione.

### Categorie che mancano e potremmo aggiungere

1. **Set Piece (palle inattive)** — al momento nessuna sezione. Andrebbero: schema corner offensivo/difensivo, chi tira punizioni, chi tira rigori, marcatori designati sui calci d'angolo subiti.
2. **Trigger tattici** — eventi specifici durante la partita che fanno scattare una decisione automatica (es. "se avversario passa a 5 difensori al 70' → entra il mio 2° ST"). Una matrice "trigger → azione" sarebbe potente.
3. **Routine settimanale dettagliata** — per ora c'è solo un cenno in §10. Potrebbe diventare la mia "agenda" del manager.
4. **Diario "errori commessi nelle ultime 10 partite"** — sezione *vivente*, da aggiornare ogni settimana. Pattern che emergono → diventano nuove autoregole in §11.
5. **Profilo psicologico avversario** — "questo manager spinge sempre Offensiva nel primo tempo → io accetto 0-0 e lo rimonto al 60'". Conoscere i giocatori reali della lega.
6. **Glossario personale** — abbreviazioni mie (es. "TT puro", "Plan B"). Diverso da `abbreviations.json` (che è del gioco).

### Migliorie strutturali (su come è organizzato il documento)

1. **Numerazione gerarchica leggera**: oggi è solo H2/H3. Per riferimenti rapidi (es. "guarda §4.3") andrebbe estesa anche dentro le tabelle.
2. **Stato editoriale per voce** ([CONFERMARE]/[INTEGRARE]/[FISSO]) — l'ho introdotto come marker. Quando arriviamo a v1.0 dovrebbe sparire. Utile in bozza.
3. **Tabella "fonti"** in cima — qual è la story/meta tactic di riferimento per ogni decisione. Renderebbe il documento *audibile* (tracciamento del perché).
4. **Versione frontend?** — questo .md è il single source of truth, ma potremmo derivarne una sezione **"Il mio playstyle"** in Academy (nuova sezione #13), generata da `_gen_bundle.py` come gli altri dataset.

### Integrazione con i dataset dell'app

Se vogliamo portare questo in app:

- **Nuovo dataset `MY_PLAYBOOK`** in `server.py` con schema simile a `SEASON_STORIES` ma più strutturato (1 record per categoria).
- **Endpoint `/api/myplaybook`** + bundle JSON.
- **Nuova sezione Academy "My Style"** (sezione #13 della tab ACADEMY).
- **Filtro intelligente**: quando in COUNTER o FORMATIONS scelgo un avversario, l'app potrebbe mostrarmi *prima* il mio counter personalizzato (da `MY_PLAYBOOK`) e *poi* quello generico.

### Domande aperte (per la sessione di review)

1. **L'identità tiki-taka è davvero la tua?** O hai un secondo stile (es. "gioco difensivo" sotto pressione)? Se sì → documento "multi-stile" con sezione 0 dedicata alla scelta.
2. Sull'asta — quanti token spendi realmente per stagione? Mi serve per calibrare §10.
3. Sui counter — quali avversari ti hanno davvero **rovinato** le ultime stagioni? Li metto in cima a §8.
4. Vuoi che integri questo .md come **sezione Academy** nell'app, o resta documento personale?

---

*Fine bozza v0.1 — quando hai letto, dimmi cosa correggere / integrare / togliere.*

# Top Eleven Tactics — istruzioni per gli agenti

App di consultazione tattica per Top Eleven 2027. Backend FastAPI, frontend Expo /
React Native, tema NothingTheme. Branch di lavoro: `android-build`.

Leggi questo file prima di toccare qualsiasi cosa. Vale per Codex, Claude e
qualunque altro agente lavori nel repository.

## Dati della squadra: sono in `dossier/`

**Se ti viene chiesto un consiglio tattico, o ti viene mandato lo screenshot di un
avversario, leggi prima `dossier/ANALISI.md`.** Senza, rispondi alla cieca.

Contiene la rosa reale, 8 referti partita completi, 18 formazioni, 6 schede
mentore e gli aggregati ricalcolati. `ANALISI.md` elenca anche i buchi noti nei
dati: rispettali, non riempirli inventando.

Due cose da lì che vengono sbagliate di continuo:

- **I diagrammi a zone sono distribuzioni**, non percentuali di successo: le tre
  corsie sommano a 100.
- **La riga alta del diagramma cambia significato**: squadra di casa → riga alta =
  fascia sinistra; in trasferta → riga alta = fascia destra.

## Le tattiche 2027 hanno 11 parametri su tre fasi

Lo schema pre-2027 ("Attacco: sulle fasce", "Contropiede: attivo") **non esiste
più**. Consigli scritti con quei nomi non sono inseribili nel gioco. I campi veri,
come stanno in `opponent_settings` dentro `frontend/src/data/formations.json`:

| fase | campi |
|---|---|
| **In possesso** | `shooting_tendency` (Tendenza tiro), `passing_style` (Stile passaggi), `passing_type` (Tipo di passaggi), `crossing_tendency` (Tendenza cross) |
| **In transizione** | `lost_possession` (Possesso perso), `won_possession` (Possesso ottenuto), `mentality` (Mentalità) |
| **Non in possesso** | `marking` (Stile marcatura), `pressing` (Pressing), `defensive_line` (Linea difensiva), `tackling` (Stile contrasti) |

Ogni campo ha la variante `_it` con l'etichetta italiana esatta del gioco. Usa
quelle, non traduzioni tue.

## Chi tocca cosa

Due sessioni lavorano spesso in parallelo. Rispetta la divisione o vi
sovrascrivete a vicenda:

| area | file | proprietario |
|---|---|---|
| layer dati | `backend/server.py`, `tools/`, `frontend/src/data/*` | sessione Claude |
| schermate | `frontend/app/`, `frontend/src/components/` | Codex |
| dossier | `dossier/*` | sessione Claude |

## Regole non negoziabili

1. **`backend/server.py` è l'unica fonte di verità** per i 23 dataset. I file in
   `frontend/src/data/*.json` e `index.ts` sono **generati**: non modificarli a
   mano, le tue modifiche verranno sovrascritte al prossimo sync.
2. **Non committare mai dati senza validatore verde.** Il percorso è
   `python tools/sync_data.py` poi `python tools/validate_data.py`, che deve
   stampare `0 errori`.
3. **Gli script `_gen_*.py` alla radice sono temporanei e gitignorati.** Non
   committarli, non considerarli parte del progetto.
4. **Niente dati personali o identificativi** nei file del repository.
5. Errori sempre gestiti; niente ID o segreti in chiaro nel codice.

## Punto di comando: `tp.ps1`

```
.\tp.ps1 stato              stato dataset, git, commit di altre sessioni
.\tp.ps1 check              sync + validatore + typecheck
.\tp.ps1 commit "messaggio" check, poi commit
.\tp.ps1 ota "messaggio"    pubblica l'OTA sul canale preview
.\tp.ps1 codex "istruzioni" lancia Codex con i vincoli di proprietà già inclusi
```

`tp.ps1` deve restare **UTF-8 con BOM**: senza BOM, PowerShell 5.1 lo decodifica
come ANSI e i trattini lunghi rompono il parsing con errori fuorvianti.

## Se ti mandano lo screenshot di un avversario

Ordine di lavoro:

1. Leggi `dossier/ANALISI.md` e `dossier/rosa.json` — devi sapere con chi giochi.
2. Estrai dallo screenshot: modulo, GEN squadra, gol fatti/subiti a partita,
   giocatori più forti con ruolo e valore.
3. Proponi la contromossa **usando i nomi dei parametri 2027** della tabella qui
   sopra, non lo schema vecchio.
4. Dichiara cosa stai deducendo e cosa invece leggi davvero. Il mentore
   dell'avversario, per esempio, è visibile solo dopo il calcio d'inizio.

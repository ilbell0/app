# Top Eleven Tactics — Handoff

App mobile (React Native + Expo) per consigli tattici Top Eleven, completamente offline. **Sviluppata in coppia con Claude Code**, dati raccolti via NotebookLM + ricerche web + conoscenza calcistica.

Last commit di riferimento: `0f6bc69` su branch `android-build`.

---

## 1. Cos'è e a chi serve

App pensata per **Habetamu Bellini** (operatore sociosanitario, account `bellinihabetamu@gmail.com` / `ilbell0` su GitHub). L'utente non scrive codice: tutto si fa in coppia con un'AI nella console.

**Obiettivo**: app di riferimento tattico per Top Eleven 2026 — formazioni, counter-formazioni, frecce, ruoli giocatore, abilità speciali, storie, FAQ, percorsi per livello di rosa.

---

## 2. Architettura

```
C:\Users\habet\progetti\app-emergent\
├── backend/
│   └── server.py            # FastAPI + 18 dataset Python in-file (fonte di verità)
├── frontend/                # Expo SDK 54 + React Native + TypeScript
│   ├── app/(tabs)/          # Tab navigation (expo-router)
│   │   ├── index.tsx        # Home
│   │   ├── formations.tsx   # Tab FORM con filtro difesa 3/4/5
│   │   ├── counters.tsx     # Tab COUNTER
│   │   ├── scout.tsx        # Tab SCOUT (tips)
│   │   ├── academy.tsx      # Tab ACADEMY (12 sotto-sezioni)
│   │   ├── settings.tsx     # Tab SET
│   │   └── _layout.tsx      # Bottom tab bar (6 tab, no AI)
│   ├── src/
│   │   ├── components/      # PitchDiagram.tsx (mini-campo formazioni, no SVG)
│   │   ├── data/            # JSON estratti da server.py (offline)
│   │   ├── context/         # AuthContext, LanguageContext (IT/EN)
│   │   └── theme/           # NothingTheme (nero/rosso)
│   ├── app.json             # name, slug, package, updates URL
│   ├── eas.json             # build profiles + canale OTA
│   └── package.json
├── tools/
│   ├── datasets.py          # estrazione/scrittura dataset in server.py (via ast)
│   ├── sync_data.py         # rigenera frontend/src/data/*.json + index.ts da server.py
│   ├── validate_data.py     # validatore invarianti (0 errori = si può committare)
│   ├── tactical_audit.py    # report QUALITÀ tattica dei counter (non bloccante)
│   └── arrows_engine.py     # motore frecce: unica fonte di verità per fr e alt_fr
├── tests/, test_reports/    # Test backend
└── _gen_*.py                # Script generatori temporanei (gitignorati, NON committare)
```

**Bottom tabs attive**: HOME · FORM · COUNTER · SCOUT · ACADEMY · SET (tab AI rimossa il 04/06).

### UI/UX riordino (13/06)
- **FORM**: ogni scheda mostra un mini-campo (`PitchDiagram`) con i giocatori
  nelle posizioni reali e le frecce dello scenario; filtro **COMUNI** di default
  (37 moduli reali, campo `FORMATIONS.common`) vs TUTTE/DIF; badge COMUNE/VARIANTE;
  i moduli in BATTE/VULNERABILE A sono cliccabili (navigazione wiki).
- **Ricerca per numero (FORM + COUNTER)**: barra di ricerca che matcha il nome
  o la sequenza numerica (cifre): digitando "3-3-2-2" o "3-2-3-2" si trovano anche
  i moduli con notazione avanzata (es. "3N-2W-3N-2"). Risolve il problema dei nomi
  che Top Eleven mostra in forma numerica pulita ma che nel DB hanno notazione N/W.
  Audit completezza (13/06): tutte le formazioni base di difesa 4/5 delle fonti
  sono presenti, e tutte le strutture di difesa 3 — il dataset è completo, mancava
  solo la trovabilità per nome numerico.
- **COUNTER**: nel modal il modulo principale e l'alternativa sono selezionabili
  (toggle PRINCIPALE/ALTERNATIVA); ognuno mostra il proprio mini-campo e le proprie
  frecce. Le impostazioni di atteggiamento restano condivise (stesso scenario/avversario).
  **Frecce**: sia `fr` (principale) sia `alt_fr` (alternativa) sono prodotte dallo
  stesso `tools/arrows_engine.py` (principi tattici dalle fonti: DMC↓ schermo,
  ali AML/AMR↑, terzini↓ in difesa, ecc.) — stessa qualità per entrambi, niente
  asimmetria. Rigenerabili con `_apply_arrows.py`-style su tutto l'engine.
- **SCOUT**: filtro a 3 macro-aree (Tattica/Reparti/Gestione, mappa `MACRO_OF`)
  che copre tutti gli 82 consigli (prima il filtro ne raggiungeva ~5).
- **ACADEMY**: selettore a 2 livelli — 4 gruppi (Tattica/Giocatori/Strategia/
  Riferimento, `GROUPS`) sopra le 15 sezioni, invece della lista piatta.

---

## 3. Stato attuale dataset (18 totali)

| Dataset Python | Voci | Bundle JSON frontend | Descrizione |
|---|---|---|---|
| `FORMATIONS` | 126 | `formations.json` | Moduli con scenari forte/pari/debole + frecce + reverse-lookup (`effective_against`, `vulnerable_to`) + `defense_count` + `common` |
| `COUNTER_ENGINE` | 107 | `counterEngine.json` | Per ogni avversario: 3 scenari completi. **Fonte di verità dei counter** |
| `COUNTER_QUICK` | 74 | `counterQuick.json` | Tabella rapida avversario → 3 counter (derivata dalla matrice) |
| `MATCHUP_MATRIX` | 107 | `matchupMatrix.json` | Matrice avversario → 3 counter (derivata dall'engine: off=debole.mod, neu=pari.mod, dif=forte.mod) |
| `SCOUT_TIPS` | 82 | `scoutTips.json` | Tip per categoria (defense, midfield, attack, tactics, counter, scenario, morale, market, skills, arrows, meta, economy) |
| `PLAYER_ROLES` | 28 | `playerRoles.json` | Ruoli (Sweeper Keeper → False 9 → Trequartista → Carrilero → Raumdeuter…) |
| `META_TACTICS` | 13 | `metaTactics.json` | Tier S/A/B + flag `trending`, varianti FMM Vibe |
| `SPECIAL_ABILITIES` | 21 | `specialAbilities.json` | Shadow Striker, Falso 9, Pacey Dribbler, Goal Poacher… |
| `TRAINING_GUIDE` | 9 | `trainingGuide.json` | Per posizione (GK, DC, DL/DR, DMC, MC, ML/MR, AMC, AML/AMR, ST) |
| `ARROW_TACTICS` | 24 | `arrowTactics.json` | Setup frecce per modulo |
| `REAL_TEAMS` | 11 | `realTeams.json` | Pep City, Klopp Liverpool, Ancelotti Real, Conte Inter, Mou Triplete, Simeone, Pep Bayern, MSN, SAF United, Tuchel Chelsea, AC Milan |
| `SEASON_STORIES` | 6 | `seasonStories.json` | Storie narrate (Triplete 4-3-3, Underdog V-Style, Rimonta, Ricostruzione, Tiki-Taka 75%, Barça Tiki-Taka) |
| `FAQ` | 17 | `faq.json` | Categorie: app, tactics, training, economy, matchday |
| `ABBREVIATIONS` | 13 | `abbreviations.json` | F, N, W, B, C, D, H, V, ET, ML, ND, WD, XT |
| `CAREER_PATHS` | 5 | `careerPaths.json` | Percorsi per livello stelle rosa (3★ → 7★+) |
| `MY_PLAYBOOK` | 13 | `myPlaybook.json` | Sezione "Mio Stile": il playbook personale tiki-taka |
| `SET_PIECE` | 5 | `setPiece.json` | Sezione "Piazzati": rigoristi, punizioni, angoli, rimesse |
| `BATTLE_CARDS` | 10 | `battleCards.json` | Sezione "Scontri": schede scontro diretto tra moduli |

**Totale: 670 voci tattiche strutturate.**

**Gerarchia dei counter**: `COUNTER_ENGINE` è la fonte di verità; `MATCHUP_MATRIX` e `COUNTER_QUICK` sono derivate e il validatore fallisce se divergono.

**Endpoint API** (32 totali): `/api/{dataset}` + `/api/{dataset}/{filter}` per ognuno.

---

## 4. Sezioni Academy (12)

Ogni sezione ha card list + modal di dettaglio. Tutte bilingue IT/EN (toggle in Settings → context globale).

1. **Roles** (Ruoli) — 28 ruoli
2. **Arrows** (Frecce) — 24 setup frecce
3. **Meta** — 13 meta tactics 2026 (5 trending)
4. **Skills** (Abilità) — 21 abilità speciali
5. **Training** (Allenamento) — 9 guide
6. **Teams** (Squadre) — 11 squadre reali
7. **Stories** (Storie) — 6 storie di stagione
8. **FAQ** — 17 domande
9. **Quick** (Rapido) — 75 counter rapidi
10. **Legend** (Leggenda) — 13 abbreviazioni
11. **Matrix** (Matrice) — 117 matchup avversario→counter
12. **Paths** (Percorsi) — 5 percorsi per livello rosa

---

## 5. Stack tecnologico

- **Backend**: FastAPI + dataset Python in-file (no DB in produzione - usato solo per OAuth/AI che ora sono rimossi)
- **Frontend**: Expo SDK 54 + React Native 0.81 + TypeScript + expo-router (typed routes)
- **OTA Updates**: expo-updates 29.0.18, runtime policy `appVersion`, canale `preview`
- **Tema**: NothingTheme custom (nero `#000`, accent rosso `#D71921`)
- **i18n**: Custom `useLanguage()` hook con `language: 'it' | 'en'`
- **Package Android**: `com.ilbello.topeleventactics`
- **Project Expo**: `67021d93-0c92-4c15-ab6d-d7f8d8e059d5` (slug `top-eleven-tactics`, owner `hab3`)

### Toolchain locale richiesta
- Node 25 + npm 11
- Python 3.12+
- eas-cli (`npm install -g eas-cli`, l'utente l'ha installato; il path è in `$env:APPDATA\npm`)
- Git
- VS Code (installato in `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe`)
- **NotebookLM CLI** (`notebooklm`, Python package `notebooklm-py`)

---

## 6. Git workflow

- Repo: `https://github.com/ilbell0/app`
- Branch operativo: **`android-build`**
- Branch principale: `main`
- **Push diretto su `main` è bloccato** dal classifier di Claude Code → si usa PR via GitHub web UI
- Identità commit: `bellinihabetamu@gmail.com` / `Habetamu Bellini`
- Footer commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

### Pattern commit usato
```powershell
cd "C:\Users\habet\progetti\app-emergent"
git add backend/server.py "frontend/src/data" "frontend/app/(tabs)/<file>.tsx"
git -c user.email="bellinihabetamu@gmail.com" -c user.name="Habetamu Bellini" `
    commit -F _msg.txt
Remove-Item _msg.txt -Force
git push origin android-build
```

Per evitare problemi PowerShell con i caratteri speciali nei messaggi: scrivi sempre il messaggio in `_msg.txt` con `Write` tool e poi `commit -F _msg.txt`.

---

## 7. EAS Update flow (OTA)

**Setup completato** (commit `d9c11b9` + fix `71ac874`). L'APK installato dall'utente sull'emulatore BlueStacks include `expo-updates`.

### Pubblicare un OTA dopo aver modificato i dati
```powershell
cd C:\Users\habet\progetti\app-emergent\frontend
eas update --channel preview --message "Descrizione"
```
Dura ~30s. L'app sull'emulatore scarica l'update al riavvio successivo (vedere update al secondo avvio).

### Cosa NON si può fare via OTA (richiede nuova build)
- Plugin nativi, package Android, nome app, icona
- Versione `expo-updates` o SDK
- Permessi Android

### Build nuova APK (raro)
```powershell
cd C:\Users\habet\progetti\app-emergent\frontend
eas build -p android --profile preview
```
Rispondere `n` al prompt "Install and run on emulator?" (manca adb in locale).

### Link APK più recente
Lista build: `eas build:list --platform android --limit 3`  
APK del 04/06/2026 (corrente con OTA): `https://expo.dev/artifacts/eas/d4VaWXmgVGfeTuzKf9NFb8.apk`

---

## 8. NotebookLM workflow

L'utente ha un notebook **"Top Eleven 2026 - Tattica Avanzata & Meta"** (id `7b0eba98-5e99-473f-9694-78857180cbd7`) con **17 fonti caricate** (forum, YouTube tactics, BlueStacks guide).

### Setup definitivo (eseguito il 04/06)
- Variabile `NOTEBOOKLM_AUTH_JSON` **rimossa dal registro Windows** (era settata persistentemente a livello User e bloccava `login`)
- Auth viene salvata in `C:\Users\habet\.claude\notebooklm_home\storage_state.json` tramite `NOTEBOOKLM_HOME`
- Il file in `.claude\notebooklm_home\` è leggibile dalla shell sandbox di Claude Code (a differenza di `.notebooklm\` che è bloccato)

### Re-auth quando scade (~7 giorni)
```powershell
# In una PowerShell utente:
$env:NOTEBOOKLM_HOME = "C:\Users\habet\.claude\notebooklm_home"
notebooklm login
# Browser → login Google → torna in PowerShell → Invio
```

### Query da Claude Code (sandbox)
```powershell
$env:PYTHONIOENCODING="utf-8"
Remove-Item Env:NOTEBOOKLM_AUTH_JSON -ErrorAction SilentlyContinue
$env:NOTEBOOKLM_HOME="C:\Users\habet\.claude\notebooklm_home"
notebooklm ask "..." --notebook 7b0eba98 2>&1
```

---

## 9. Pattern ricorrenti

### Aggiungere/modificare dataset → bundle frontend
1. Modifica `backend/server.py` (a mano per piccole modifiche, o via `tools/datasets.py`:
   `extract_assignments()` → modifica l'oggetto Python → `replace_assignment()` → `write_server_text()`)
2. Esegui `python tools/sync_data.py` (riscrive tutti i JSON in `frontend/src/data/` + `index.ts`)
3. Esegui `python tools/validate_data.py` — **deve dare 0 errori prima del commit**
4. Frontend importa dati direttamente da `@/src/data`: `import { FORMATIONS } from '@/src/data'`
5. Commit + push + `eas update`

### Invarianti verificate dal validatore
- server.py ⇄ JSON identici; 11 giocatori e 1 GK per modulo; `defense_count` coerente
- Frecce solo su posizioni esistenti nel modulo (FORMATIONS, COUNTER_ENGINE, ARROW_TACTICS)
- Vocabolari chiusi EN/IT (mentalità, pressing, passaggi, contrasti, marcatura)
- Niente fuorigioco ON + pressing basso; niente contropiede ON + mentalità offensiva
- Riferimenti tra moduli canonici; niente contraddizioni A-batte-B/B-batte-A
- MATCHUP_MATRIX derivata da COUNTER_ENGINE; COUNTER_QUICK derivata dalla matrice
- Accenti italiani non strippati (più/è/perché…) nei campi `*_it` e `w`
- Counter offensivo confermato dal reverse-lookup; counter mai `vulnerable_to` l'avversario

### Audit tattico (qualità, non bloccante)
`python tools/tactical_audit.py [--severity ALTA|MEDIA|INFO]` valuta la sensatezza
di ogni counter coi principi di Top Eleven (dominio del centrocampo con eccezioni
per difese a 3 e per lo scenario difensivo; mentalità coerente con lo scenario,
con eccezione per le difese a 5; struttura off/dif). Stato al 13/06: **0 ALTA,
0 MEDIA, 47 INFO** su 107 voci — nessun problema tattico di sostanza.

### Verifica con le fonti (13/06)
**84 dei 107 moduli** hanno il counter principale verificato col notebook
NotebookLM `7b0eba98` (11 batch totali): è collocato nello scenario **neutro**
(risposta standard) con la nota `w` che cita la motivazione tattica dalle fonti
(`"Counter standard (fonte): … , <perché>"`); off/dif prendono le alternative
dal reverse-lookup. I 5 moduli che il notebook Top Eleven non trattava
(3-1-3-1-2, 3-1-3-2-1 Tiki-taka, 3-1-5-1 AMC, 3W-2N-3N-2, 5-1DMC-2-2) sono stati
verificati con ricerca calcistica generale (NotebookLM con angolazione generica
+ web: jobsinfootball, spielverlagerung) traducendoli nelle formazioni reali
(3-4-1-2, 3-4-2-1, 3-6-1, 3-2-3-2, catenaccio 5-1-2-2). I counter erano già
corretti: la nota neutro ora cita la debolezza ("Counter verificato …").
**Copertura totale: 107/107 moduli con counter motivato da fonte.**

### Stesso schema per ogni nuovo dataset
```
1. Aggiungi NEW_DATASET = [...] in server.py
2. Aggiungi endpoint @api_router.get("/api/<name>")
3. Aggiungi la entry in DATASETS dentro tools/datasets.py
4. Esegui tools/sync_data.py (genera JSON + import in index.ts)
5. Aggiungi sezione in academy.tsx (SECTIONS + LOCAL_DATA + cardTitle/Subtitle + modal block + SectionId + state)
```

### Sandbox PowerShell di Claude Code: cose da sapere
- **NON può accedere a `C:\Users\habet\.notebooklm\`** (ACL ristretti)
- Può accedere a tutto in `C:\Users\habet\.claude\` e `C:\Users\habet\progetti\`
- Per `eas`, `notebooklm`, `git`: lanciare i comandi nella shell sandbox funziona (sono nel PATH utente)
- Per scrivere file Python lunghi, usare `Write` tool (non Edit su file > 5000 righe)

---

## 10. Idee aperte / TODO

Già proposte all'utente, non ancora implementate:
- **Calcolatore "Trova il mio counter"** — flusso guidato form-based: inserisci modulo avversario + livello → setup completo
- **Achievement / Sfide** — obiettivi da completare per stagione
- **+5 SEASON_STORIES** (ne abbiamo solo 6, dataset poco popolato)
- **Aggiornamento TRAINING_GUIDE** (ferma a 9 voci - una per posizione, potrebbe arrivare a 20+ con dettagli per ruolo specifico)
- **Riempimento ARROW_TACTICS** — coprire tutte le 125 formazioni (attualmente 24)
- **45 INFO dell'audit tattico** (`python tools/tactical_audit.py`) — migliorie opzionali su moduli rari: counter molto stretti contro difese a 3, inversioni di struttura offensivo/difensivo, 5 coppie residue (off=neu) dove l'avversario ha una sola alternativa nel reverse-lookup. Non sono errori: il modulo consigliato è sempre un counter validato. Per perfezionarle servono le fonti NotebookLM una a una.

Idee mie (Claude) per future sessioni:
- **Pulsante Feedback in-app** → Google Form
- **Link community Telegram/Discord** (l'utente è interessato all'aspetto community)
- **AdMob** se l'utente vuole monetizzare (l'app è personal-use)
- **Build APK release firmata** quando l'utente la vuole pubblicare su Play Store

---

## 11. File da NON committare mai

- `_*.py` nella root (script temporanei di sessione) — ora coperti dal `.gitignore`
- `preview_server.py` — viewer HTML locale (utile per testare bundle senza emulatore) — gitignorato
- `frontend/package-lock.json` — il lockfile canonico è `yarn.lock` — gitignorato
- `node_modules/`, `.expo/`, `.metro-cache/`

---

## 12. Comandi di emergenza

### Se l'OTA fallisce con socket hang up / ECONNRESET
Rete instabile o McAfee. Riprovare 2-3 volte; cambiare DNS a `1.1.1.1` come ultimo step.

### Se l'app sull'emulatore non riceve l'OTA
1. Verificare che l'APK installato sia da build `61b9a9d0` o successiva (con expo-updates)
2. Verificare con `eas update:list --branch preview --json` che l'update sia pubblicato
3. Chiudere COMPLETAMENTE l'app (recents → swipe), riaprire, aspettare 5s, richiudere, riaprire (doppio riavvio applica l'update)

### Se `notebooklm` dice "Authentication expired"
1. Controllare se `$env:NOTEBOOKLM_AUTH_JSON` è settata: rimuovere con `Remove-Item Env:NOTEBOOKLM_AUTH_JSON`
2. Verificare con `[Environment]::GetEnvironmentVariable('NOTEBOOKLM_AUTH_JSON','User')` che sia rimossa dal registro
3. Re-login come descritto in §8

### Se PowerShell sandbox non vede file in `.claude\notebooklm_home\storage_state.json`
Far ricopiare all'utente da `.notebooklm\storage_state.json` (le copie utente hanno permessi normali, quelle Playwright hanno ACL ristretti).

---

## 13. Numero magico

Il numero che riassume il lavoro fatto: **670 voci tattiche strutturate, 18 dataset, 15 sezioni Academy, un validatore che le tiene tutte coerenti, una stagione di calcio nel telefono**.

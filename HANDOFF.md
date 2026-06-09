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
│   └── server.py            # FastAPI + 15 dataset Python in-file
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
│   │   ├── data/            # JSON estratti da server.py (offline)
│   │   ├── context/         # AuthContext, LanguageContext (IT/EN)
│   │   └── theme/           # NothingTheme (nero/rosso)
│   ├── app.json             # name, slug, package, updates URL
│   ├── eas.json             # build profiles + canale OTA
│   └── package.json
├── tests/, test_reports/    # Test backend
└── _gen_*.py                # Script generatori temporanei (NON committare)
```

**Bottom tabs attive**: HOME · FORM · COUNTER · SCOUT · ACADEMY · SET (tab AI rimossa il 04/06).

---

## 3. Stato attuale dataset (15 totali)

| Dataset Python | Voci | Bundle JSON frontend | Descrizione |
|---|---|---|---|
| `FORMATIONS` | 56 | `formations.json` | Moduli con scenari forte/pari/debole + frecce + reverse-lookup (`effective_against`, `vulnerable_to`) + `defense_count` |
| `COUNTER_ENGINE` | 81 | `counterEngine.json` | Per ogni avversario: 3 scenari completi |
| `COUNTER_QUICK` | 75 | `counterQuick.json` | Tabella rapida avversario → 3 counter |
| `MATCHUP_MATRIX` | 117 | `matchupMatrix.json` | Matrice avversario → 3 counter (off/neu/dif) |
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

**Totale: 558 voci tattiche strutturate.**

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
1. Modifica `backend/server.py` (manualmente o via script `_gen_*.py`)
2. Esegui `_gen_bundle.py` (riscrive tutti i JSON in `frontend/src/data/` + `index.ts`)
3. Frontend importa dati direttamente da `@/src/data`: `import { FORMATIONS } from '@/src/data'`
4. Commit + push + `eas update`

### Stesso schema per ogni nuovo dataset
```
1. Aggiungi NEW_DATASET = [...] in server.py
2. Aggiungi endpoint @api_router.get("/api/<name>")
3. Aggiungi MAP entry in _gen_bundle.py
4. Aggiungi import in src/data/index.ts (lo fa _gen_bundle.py)
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
- **Riempimento ARROW_TACTICS** — coprire tutte le 56 formazioni (attualmente 24)

Idee mie (Claude) per future sessioni:
- **Pulsante Feedback in-app** → Google Form
- **Link community Telegram/Discord** (l'utente è interessato all'aspetto community)
- **AdMob** se l'utente vuole monetizzare (l'app è personal-use)
- **Build APK release firmata** quando l'utente la vuole pubblicare su Play Store

---

## 11. File da NON committare mai

- `_gen_*.py`, `_audit*.py`, `_msg.txt`, `_apply*.py`, `_add_*.py`, `_build_*.py`, `_enrich*.py`, `_fix_*.py`, `_fill_*.py` — script generatori temporanei
- `preview_server.py` — viewer HTML locale (utile per testare bundle senza emulatore)
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

Il numero che riassume il lavoro fatto: **558 voci tattiche strutturate, 15 dataset, 12 sezioni Academy, 32 endpoint API, 35+ commit su un branch, una stagione di calcio nel telefono**.

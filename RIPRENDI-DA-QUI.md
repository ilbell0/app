# Riprendi da qui — sessione interrotta il 10/08/2026

Sessione Antigravity ("Top Eleven Tactics Development") interrotta alle 12:26 per
**esaurimento della quota modelli**, non per un errore. Il piano Antigravity si
rinnova il **16/08/2026 alle 22:23**.

Questo file serve a riprendere da Claude Code, che ha una quota separata.

## Stato verificato al momento dell'interruzione

- Branch: `android-build`
- HEAD: `e91a6c6` "feat(dati): enrichment gestione live + lettura avversario da NotebookLM"
- **`python tools/validate_data.py` → 0 errori, 0 avvisi su 716 voci in 22 dataset**

Il lavoro è in uno stato **coerente e validato**. Non è rimasto niente a metà.

## Cosa era in corso

Migrazione della struttura di `COUNTER_ENGINE`, eseguita con lo script temporaneo
`_migrate_tactics.py` alla radice del progetto, seguita da `tools/sync_data.py` e
da `tools/validate_data.py`. Gli ultimi due comandi della sessione sono stati
proprio validazioni, entrambe concluse.

## Modifiche non committate

```
M backend/server.py
M frontend/app/(tabs)/counters.tsx
M frontend/src/data/counterEngine.json
M frontend/src/data/formations.json
M tools/validate_data.py
?? .claude/
```

Sono il risultato della migrazione, già validato. **Primo passo consigliato: leggere
il diff e committare**, prima di iniziare qualsiasi cosa nuova — così il lavoro è al
sicuro e si riparte da una base pulita.

```
git diff --stat
git add -A ':!.claude'
git commit -m "refactor(dati): migrazione struttura COUNTER_ENGINE"
```

## Da fare dopo

- `_migrate_tactics.py` è uno script usa-e-getta di migrazione, ancora presente
  nella radice. Una volta committata la migrazione, va rimosso.
- Valutare se `.claude/` va tracciata o aggiunta a `.gitignore`.

## Regole della toolchain — non aggirarle

1. La fonte di verità dei dati è `backend/server.py`. I JSON in
   `frontend/src/data/` sono **generati**: non si modificano a mano.
2. Dopo ogni modifica ai dati: `python tools/sync_data.py`, poi
   `python tools/validate_data.py`. La validazione deve chiudere a 0 errori.
3. Non tenere il progetto aperto in due editor che scrivono insieme: in passato
   ha prodotto mojibake nei file di dati.

Il contesto completo dell'architettura è in [HANDOFF.md](HANDOFF.md) — nota però
che quel file cita come riferimento il commit `0f6bc69`, superato: da allora sono
arrivati `a2570b7`, `541712e` e `e91a6c6`.

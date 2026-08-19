<#
  tp.ps1 — punto di comando del progetto Top Eleven Tactics.

  Uso:
    .\tp.ps1 stato              stato dataset, typecheck, git, sessioni parallele
    .\tp.ps1 check              sync + validatore + typecheck (non scrive su git)
    .\tp.ps1 commit "messaggio" check, poi commit di tutto l'albero
    .\tp.ps1 ota "messaggio"    pubblica l'OTA sul canale preview
    .\tp.ps1 codex "istruzioni" lancia Codex sul frontend con i vincoli di proprieta'
    .\tp.ps1 aiuto

  Regola di proprieta' dei file, per evitare che due sessioni si sovrascrivano:
    layer dati  -> backend/server.py, tools/, frontend/src/data/*  (sessione Claude)
    schermate   -> frontend/app/, frontend/src/components/         (Codex)
  Il sotto-comando 'codex' inietta questi vincoli automaticamente.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Comando = 'stato',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Resto
)

$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot
$FRONTEND = Join-Path $ROOT 'frontend'
$STATOFILE = Join-Path $ROOT '.tp-ultimo-head'

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m) { Write-Host "  OK  $m" -ForegroundColor Green }
function Ko($m) { Write-Host "  KO  $m" -ForegroundColor Red }
function Warn($m) { Write-Host "  !   $m" -ForegroundColor Yellow }

# --- controlli singoli -----------------------------------------------------

function Invoke-Sync {
    Info 'sync_data.py'
    $out = & python (Join-Path $ROOT 'tools\sync_data.py') 2>&1
    if ($LASTEXITCODE -ne 0) { $out | Write-Host; Ko 'sync fallito'; return $false }
    Ok (($out | Select-String 'index.ts') -join '')
    return $true
}

function Invoke-Validate {
    Info 'validate_data.py'
    $out = & python (Join-Path $ROOT 'tools\validate_data.py') 2>&1
    $riga = ($out | Select-String 'errori').ToString().Trim()
    if ($LASTEXITCODE -ne 0 -or $riga -notmatch '^0 errori') {
        $out | Write-Host
        Ko "validatore: $riga"
        return $false
    }
    Ok $riga
    return $true
}

function Invoke-Typecheck {
    Info 'tsc --noEmit'
    Push-Location $FRONTEND
    try {
        $out = & npx tsc --noEmit -p tsconfig.json 2>&1
        if ($LASTEXITCODE -ne 0) { $out | Select-Object -First 15 | Write-Host; Ko 'typecheck fallito'; return $false }
        Ok 'nessun errore di tipo'
        return $true
    } finally { Pop-Location }
}

# Rileva commit fatti da un'altra sessione dall'ultimo giro.
function Test-SessioniParallele {
    $head = (& git -C $ROOT rev-parse HEAD).Trim()
    $precedente = if (Test-Path $STATOFILE) { (Get-Content $STATOFILE -Raw).Trim() } else { $null }
    if ($precedente -and $precedente -ne $head) {
        Warn "HEAD e' cambiato dall'ultimo controllo: $($precedente.Substring(0,7)) -> $($head.Substring(0,7))"
        & git -C $ROOT log --oneline "$precedente..$head" | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        Warn "Un'altra sessione ha committato. Verifica che il tuo lavoro sia intatto prima di procedere."
    }
    elseif ($precedente) { Ok 'nessun commit esterno dall''ultimo controllo' }
    else { Warn 'primo avvio: registro HEAD come riferimento' }
    Set-Content -Path $STATOFILE -Value $head -Encoding utf8
}

# --- sotto-comandi ---------------------------------------------------------

function Cmd-Stato {
    Info "=== STATO — $(Split-Path $ROOT -Leaf) ==="
    $ramo = (& git -C $ROOT rev-parse --abbrev-ref HEAD).Trim()
    Write-Host "  branch  : $ramo"

    $dataDir = Join-Path $FRONTEND 'src\data'
    $json = Get-ChildItem $dataDir -Filter *.json
    $voci = 0
    foreach ($f in $json) {
        $c = Get-Content $f.FullName -Raw | ConvertFrom-Json
        $voci += @($c).Count
    }
    Write-Host "  dataset : $voci voci in $($json.Count) file"

    $mod = & git -C $ROOT status --short
    if ($mod) {
        Write-Host "  git     : $(@($mod).Count) file modificati"
        $mod | ForEach-Object { Write-Host "            $_" }
    }
    else { Write-Host '  git     : albero pulito' }

    Test-SessioniParallele
}

function Cmd-Check {
    if (-not (Invoke-Sync)) { exit 1 }
    if (-not (Invoke-Validate)) { exit 1 }
    if (-not (Invoke-Typecheck)) { exit 1 }
    Info 'tutto verde.'
}

function Cmd-Commit($messaggio) {
    if (-not $messaggio) { Ko 'serve un messaggio: .\tp.ps1 commit "descrizione"'; exit 1 }
    Test-SessioniParallele
    Cmd-Check
    $mod = & git -C $ROOT status --short
    if (-not $mod) { Warn 'niente da committare'; return }
    & git -C $ROOT add -A
    & git -C $ROOT commit -m $messaggio
    if ($LASTEXITCODE -ne 0) { Ko 'commit fallito'; exit 1 }
    Set-Content -Path $STATOFILE -Value (& git -C $ROOT rev-parse HEAD).Trim() -Encoding utf8
    Ok 'commit creato'
}

function Cmd-Ota($messaggio) {
    if (-not $messaggio) { Ko 'serve un messaggio: .\tp.ps1 ota "descrizione"'; exit 1 }
    Cmd-Check
    $mod = & git -C $ROOT status --short
    if ($mod) { Ko 'ci sono modifiche non committate: fai prima .\tp.ps1 commit'; exit 1 }
    Push-Location $FRONTEND
    try { & eas update --channel preview --message $messaggio }
    finally { Pop-Location }
}

function Cmd-Codex($istruzioni) {
    if (-not $istruzioni) { Ko 'serve un prompt: .\tp.ps1 codex "cosa deve fare"'; exit 1 }
    $vincoli = @'
VINCOLI (un'altra sessione lavora sul layer dati in parallelo):
- Modifica SOLO file dentro frontend/app/ e frontend/src/components/.
- NON toccare backend/server.py, NON toccare tools/, NON modificare a mano
  i file in frontend/src/data/ (sono generati automaticamente).
- NON eseguire tools/sync_data.py ne' tools/validate_data.py.
- NON fare commit e non usare git.
- Alla fine esegui, dalla cartella frontend: npx tsc --noEmit
  e correggi solo gli errori che hai introdotto tu.

COMPITO:
'@
    $prompt = $vincoli + "`n" + $istruzioni
    $tmp = Join-Path $env:TEMP "tp-codex-$(Get-Date -Format yyyyMMdd-HHmmss).txt"
    Set-Content -Path $tmp -Value $prompt -Encoding utf8
    Info "prompt scritto in $tmp"
    & codex exec -C $ROOT -s workspace-write $prompt
}

# --- dispatch --------------------------------------------------------------

$arg = if ($Resto) { $Resto -join ' ' } else { $null }

switch ($Comando.ToLower()) {
    'stato' { Cmd-Stato }
    'check' { Cmd-Check }
    'commit' { Cmd-Commit $arg }
    'ota' { Cmd-Ota $arg }
    'codex' { Cmd-Codex $arg }
    default {
        Write-Host @'
tp.ps1 — punto di comando Top Eleven Tactics

  .\tp.ps1 stato               stato dataset, git, commit esterni
  .\tp.ps1 check               sync + validatore + typecheck
  .\tp.ps1 commit "messaggio"  check, poi commit
  .\tp.ps1 ota "messaggio"     OTA sul canale preview (richiede albero pulito)
  .\tp.ps1 codex "istruzioni"  lancia Codex sul frontend con i vincoli gia' inclusi
'@
    }
}

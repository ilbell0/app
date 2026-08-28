#!/bin/bash
# Cattura schermate da BlueStacks per il protocollo del dossier.
#
#   bash tools/cattura.sh <nome>       una schermata, salvata come <nome>.png
#   bash tools/cattura.sh <nome> 5 3   5 schermate a 3 secondi di distanza
#
# Le schermate finiscono in dossier/catture/ (gitignorata: sono grandi).
#
# Perche' exec-out e non "screencap + pull": su BlueStacks la shell adb si
# chiude dopo pochi comandi ("error: closed"), mentre exec-out screencap passa
# sempre. Stessa ragione per cui l'input non e' automatizzabile: naviga l'utente.
#
# MSYS_NO_PATHCONV serve perche' Git Bash convertirebbe i path Android
# (/sdcard/...) in path Windows.
set -u
export MSYS_NO_PATHCONV=1

ADB="/c/Program Files/BlueStacks_nxt/HD-Adb.exe"
DEV="127.0.0.1:5555"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/dossier/catture"

nome="${1:-schermata}"
quante="${2:-1}"
pausa="${3:-3}"

[ -x "$ADB" ] || { echo "HD-Adb.exe non trovato in $ADB"; exit 1; }
mkdir -p "$DEST"
"$ADB" connect "$DEV" >/dev/null 2>&1

for i in $(seq 1 "$quante"); do
    if [ "$quante" -gt 1 ]; then
        f="$DEST/${nome}_$(printf '%02d' "$i").png"
    else
        f="$DEST/${nome}.png"
    fi
    "$ADB" -s "$DEV" exec-out screencap -p > "$f"
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)
    # un PNG valido comincia con \x89PNG; sotto i 50 KB e' quasi certo un errore
    if [ "$size" -lt 50000 ]; then
        echo "ERRORE: $f e' $size byte, cattura fallita"
        rm -f "$f"
        exit 1
    fi
    echo "$(basename "$f")  ${size} byte"
    if [ "$i" -lt "$quante" ]; then sleep "$pausa"; fi
done

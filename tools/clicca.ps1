# Clicca dentro BlueStacks usando coordinate dello screenshot ADB (2560x1440).
#
#   powershell -File tools/clicca.ps1 -X 1715 -Y 161
#
# Serve perche' l'input via ADB non passa su BlueStacks (la shell si chiude con
# "error: closed"), mentre HD-Player e' una normale finestra Windows: il click
# si inietta col mouse di sistema. Vedi tools/cattura.sh per il lato lettura.
#
# La geometria viene misurata a ogni chiamata: se sposti o ridimensioni la
# finestra, le coordinate restano valide senza ritoccare nulla.
param(
    [Parameter(Mandatory=$true)][int]$X,
    [Parameter(Mandatory=$true)][int]$Y,
    [int]$AttesaMs = 1000
)

Add-Type @"
using System; using System.Runtime.InteropServices;
public class BsClick {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, int e);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out PT p);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RC r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref PT p);
  [StructLayout(LayoutKind.Sequential)] public struct RC { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct PT { public int X, Y; }
  public const uint DOWN = 0x0002, UP = 0x0004;
}
"@

$proc = Get-Process HD-Player -ErrorAction SilentlyContinue
if (-not $proc) { Write-Error "BlueStacks (HD-Player) non e' in esecuzione"; exit 1 }
$hwnd = $proc.MainWindowHandle

# area client della finestra e sua origine sullo schermo
$cr = New-Object BsClick+RC
[void][BsClick]::GetClientRect($hwnd, [ref]$cr)
$org = New-Object BsClick+PT; $org.X = 0; $org.Y = 0
[void][BsClick]::ClientToScreen($hwnd, [ref]$org)

# BlueStacks disegna una barra propria in alto; il display Android e' il resto,
# in 16:9. Ricavo l'altezza della barra dalla larghezza, invece di fissarla.
$dispW = $cr.R
$dispH = $dispW * 9.0 / 16.0
$barra = $cr.B - $dispH
if ($barra -lt 0) { $barra = 0 }

$sx = [int]($org.X + $X * ($dispW / 2560.0))
$sy = [int]($org.Y + $barra + $Y * ($dispH / 1440.0))

$vecchio = New-Object BsClick+PT
[void][BsClick]::GetCursorPos([ref]$vecchio)

[void][BsClick]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 300
[void][BsClick]::SetCursorPos($sx, $sy)
Start-Sleep -Milliseconds 150
[BsClick]::mouse_event([BsClick]::DOWN, 0, 0, 0, 0)
Start-Sleep -Milliseconds 60
[BsClick]::mouse_event([BsClick]::UP, 0, 0, 0, 0)
Start-Sleep -Milliseconds $AttesaMs

# rimette il puntatore dov'era: se stai usando il PC, non te lo sposto
[void][BsClick]::SetCursorPos($vecchio.X, $vecchio.Y)
Write-Output "click android($X,$Y) -> schermo($sx,$sy)  barra=$([int]$barra)px"

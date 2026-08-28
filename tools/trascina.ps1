# Trascina dentro BlueStacks usando coordinate dello screenshot ADB (2560x1440).
#
#   powershell -File tools/trascina.ps1 -X1 2200 -Y1 800 -X2 1200 -Y2 800
#
# Serve per le liste Android, che non rispondono alla rotella del mouse: vanno
# scorse con uno swipe. Stessa geometria di tools/clicca.ps1.
param(
    [Parameter(Mandatory=$true)][int]$X1,
    [Parameter(Mandatory=$true)][int]$Y1,
    [Parameter(Mandatory=$true)][int]$X2,
    [Parameter(Mandatory=$true)][int]$Y2,
    [int]$Passi = 25,
    [int]$AttesaMs = 900
)

Add-Type @"
using System; using System.Runtime.InteropServices;
public class BsDrag {
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
if (-not $proc) { Write-Error "BlueStacks non e' in esecuzione"; exit 1 }
$hwnd = $proc.MainWindowHandle
$cr = New-Object BsDrag+RC; [void][BsDrag]::GetClientRect($hwnd, [ref]$cr)
$org = New-Object BsDrag+PT; $org.X = 0; $org.Y = 0
[void][BsDrag]::ClientToScreen($hwnd, [ref]$org)
$dispW = $cr.R; $dispH = $dispW * 9.0 / 16.0
$barra = [math]::Max(0, $cr.B - $dispH)
function Map($ax, $ay) {
    return @([int]($org.X + $ax * ($dispW / 2560.0)),
             [int]($org.Y + $barra + $ay * ($dispH / 1440.0)))
}
$a = Map $X1 $Y1
$b = Map $X2 $Y2
$vecchio = New-Object BsDrag+PT; [void][BsDrag]::GetCursorPos([ref]$vecchio)

[void][BsDrag]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 300
[void][BsDrag]::SetCursorPos($a[0], $a[1])
Start-Sleep -Milliseconds 200
[BsDrag]::mouse_event([BsDrag]::DOWN, 0, 0, 0, 0)
Start-Sleep -Milliseconds 150
# movimento a passi: uno scatto secco viene ignorato dal riconoscimento gesti
for ($i = 1; $i -le $Passi; $i++) {
    $x = [int]($a[0] + ($b[0] - $a[0]) * $i / $Passi)
    $y = [int]($a[1] + ($b[1] - $a[1]) * $i / $Passi)
    [void][BsDrag]::SetCursorPos($x, $y)
    Start-Sleep -Milliseconds 12
}
Start-Sleep -Milliseconds 150
[BsDrag]::mouse_event([BsDrag]::UP, 0, 0, 0, 0)
Start-Sleep -Milliseconds $AttesaMs
[void][BsDrag]::SetCursorPos($vecchio.X, $vecchio.Y)
Write-Output "swipe ($X1,$Y1) -> ($X2,$Y2)"

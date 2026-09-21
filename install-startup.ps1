# Adds Usage Deck to Windows startup (uses UsageDeck.exe if built, else pythonw widget.py).
$dir = $PSScriptRoot
$exe = Join-Path $dir "UsageDeck.exe"
$lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\UsageDeck.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
if (Test-Path $exe) { $s.TargetPath = $exe }
else { $s.TargetPath = (Get-Command pythonw).Source; $s.Arguments = "`"$dir\widget.py`"" }
$s.WorkingDirectory = $dir
$ico = Join-Path $dir "logos\app.ico"
if (Test-Path $ico) { $s.IconLocation = $ico }
$s.Save()
Write-Host "Startup shortcut created: $lnk"

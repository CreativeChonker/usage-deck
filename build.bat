@echo off
rem Builds UsageDeck.exe (needs Python 3.9+). Run from this folder.
cd /d "%~dp0"
py -m pip install -q pyinstaller || exit /b 1
py -c "import widget; widget.ensure_icon()" || exit /b 1
py -m PyInstaller --noconfirm --onefile --noconsole --icon "%~dp0logos\app.ico" --name UsageDeck --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" widget.py

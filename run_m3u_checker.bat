@echo off
cd /d "%~dp0"
py -3.10 -m pip install -r requirements.txt
if errorlevel 1 py -m pip install -r requirements.txt
py -3.10 m3u_stream_checker.py
if errorlevel 1 py m3u_stream_checker.py
pause

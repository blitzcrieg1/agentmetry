@echo off
rem BLACKBOX ops CLI — start | stop | status | logs | backup | restore | install | uninstall
"%~dp0..\apps\orchestrator\.venv\Scripts\python.exe" -m cli %*

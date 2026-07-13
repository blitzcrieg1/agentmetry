@echo off
rem Agentmetry ops CLI — start | stop | status | replay | export | doctor
"%~dp0..\apps\orchestrator\.venv\Scripts\python.exe" -m cli %*

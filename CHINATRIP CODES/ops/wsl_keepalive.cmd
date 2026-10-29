@echo off
rem Keep WSL VM resident (it hosts PostgreSQL 18; systemd auto-starts it).
rem Install: copy a caller of this into shell:startup. Repo copy is the source of truth.
start "wsl-keepalive" /min wsl.exe -d Ubuntu -- sleep infinity

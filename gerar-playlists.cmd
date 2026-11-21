@echo off
setlocal
chcp 65001 >nul

set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_BIN%" (
    echo [ERRO] Ambiente virtual nao encontrado em "%~dp0.venv".
    echo        Execute na pasta do projeto:
    echo          py -m venv .venv
    echo          .\.venv\Scripts\pip.exe install -r requirements.txt
    exit /b 1
)

"%PYTHON_BIN%" "%~dp0playlist_gen.py" %*

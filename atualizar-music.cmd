@echo off
setlocal
chcp 65001 >nul

pushd "%~dp0"

echo === Atualizando Music Fetcher ===
git pull --ff-only
if errorlevel 1 (
    echo.
    echo [ERRO] Nao foi possivel atualizar via git pull.
    echo        Verifique se ha alteracoes locais pendentes em "%~dp0".
    popd
    exit /b 1
)

set "PIP_BIN=%~dp0.venv\Scripts\pip.exe"
if exist "%PIP_BIN%" (
    echo.
    echo Atualizando dependencias Python...
    "%PIP_BIN%" install -r "%~dp0requirements.txt" -q
) else (
    echo.
    echo Ambiente virtual nao encontrado. Executando install.ps1...
    powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
)

echo.
echo [SUCESSO] Music Fetcher atualizado!
popd

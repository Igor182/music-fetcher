$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host "=== Instalador Music Fetcher (Windows) ===" -ForegroundColor Cyan

# 1. Localiza Python
$PythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = @("python")
} else {
    Write-Host "[ERRO] Python 3 não encontrado no PATH." -ForegroundColor Red
    Write-Host "       Instale via: winget install Python.Python.3.12"
    exit 1
}

# 2. Verifica ffmpeg e rclone
$Missing = @()
foreach ($dep in @("ffmpeg", "rclone")) {
    if (-not (Get-Command $dep -ErrorAction SilentlyContinue)) {
        $Missing += $dep
    }
}

if ($Missing.Count -gt 0) {
    Write-Host "[AVISO] Dependência(s) ausente(s) no PATH: $($Missing -join ', ')" -ForegroundColor Yellow
    Write-Host "        Instale via: winget install Gyan.FFmpeg Rclone.Rclone"
    Write-Host "        Depois reinicie o PowerShell e rode .\install.ps1 novamente."
    exit 1
}

# 3. Cria .venv e instala dependências Python
if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/3] Criando ambiente virtual em $VenvDir..."
    if ($PythonCmd.Count -eq 2) {
        & $PythonCmd[0] $PythonCmd[1] -m venv $VenvDir
    } else {
        & $PythonCmd[0] -m venv $VenvDir
    }
} else {
    Write-Host "[1/3] Ambiente virtual já existe em $VenvDir."
}

Write-Host "[2/3] Instalando dependências Python (requirements.txt)..."
& $VenvPython -m pip install --upgrade pip -q
& $VenvPip install -r (Join-Path $ProjectDir "requirements.txt")

# 4. Adiciona a pasta do projeto ao PATH do usuário (para baixar-musica e criar-playlist)
Write-Host "[3/3] Registrando comandos globais 'baixar-musica' e 'criar-playlist' no PATH do usuário..."
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @()
if ($UserPath) {
    $PathEntries = $UserPath -split ';' | Where-Object { $_ -ne '' }
}

if ($PathEntries -notcontains $ProjectDir) {
    $NewPath = if ($UserPath) { "$UserPath;$ProjectDir" } else { $ProjectDir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Host "  -> Adicionado ao PATH: $ProjectDir"
} else {
    Write-Host "  -> Já está no PATH: $ProjectDir"
}

# 5. Avisa se o remote do rclone ainda não está configurado
$ConfigPath = Join-Path $ProjectDir "config.json"
$RemoteName = "gdrive"
if (Test-Path $ConfigPath) {
    $Config = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.rclone_remote) {
        $RemoteName = ($Config.rclone_remote -split ':')[0]
    }
}

$Remotes = & rclone listremotes 2>$null
if (-not ($Remotes -contains "${RemoteName}:")) {
    Write-Host ""
    Write-Host "[AVISO] O remote '${RemoteName}:' ainda não está configurado no rclone." -ForegroundColor Yellow
    Write-Host "        Rode 'rclone config' para conectar seu Google Drive."
}

Write-Host ""
Write-Host "[SUCESSO] Instalação concluída!" -ForegroundColor Green
Write-Host "Reabra o terminal (PowerShell ou CMD) e use de qualquer pasta:"
Write-Host "  baixar-musica   -> baixar músicas/álbuns/playlists e enviar ao Drive"
Write-Host "  criar-playlist  -> gerar playlists .m3u interativas direto do Drive"
Write-Host "  numerar-album   -> numerar faixas de um álbum no Drive"

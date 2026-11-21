#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "=== Instalador Music Fetcher (Linux) ==="

# 1. Verifica dependências de sistema
MISSING=()
for dep in python3 ffmpeg rclone; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        MISSING+=("$dep")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "[ERRO] Dependências ausentes no sistema: ${MISSING[*]}"
    echo "       No Arch Linux, instale com:"
    echo "         sudo pacman -S --needed python ffmpeg rclone"
    exit 1
fi

# 2. Cria ambiente virtual e instala dependências Python
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Criando ambiente virtual em $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "[1/3] Ambiente virtual já existe em $VENV_DIR."
fi

echo "[2/3] Instalando dependências Python (requirements.txt)..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Configura aliases no ~/.bashrc e/ou ~/.zshrc (sem duplicar)
echo "[3/3] Configurando atalhos 'baixar-musica' e 'criar-playlist'..."

MARKER_START="# >>> music-fetcher >>>"
MARKER_END="# <<< music-fetcher <<<"
ALIAS_BLOCK="$MARKER_START
alias baixar-musica='$VENV_DIR/bin/python $PROJECT_DIR/main.py'
alias criar-playlist='$VENV_DIR/bin/python $PROJECT_DIR/playlist_gen.py'
$MARKER_END"

update_shell_rc() {
    local rc_file="$1"
    if [ -f "$rc_file" ]; then
        if grep -qF "$MARKER_START" "$rc_file"; then
            # Atualiza bloco existente
            "$VENV_DIR/bin/python" -c "
from pathlib import Path
import re
p = Path('$rc_file')
text = p.read_text(encoding='utf-8')
pattern = re.compile(r'# >>> music-fetcher >>>.*?# <<< music-fetcher <<<', re.DOTALL)
p.write_text(pattern.sub('''$ALIAS_BLOCK''', text), encoding='utf-8')
"
        else
            printf "\n%s\n" "$ALIAS_BLOCK" >> "$rc_file"
        fi
        echo "  -> Atualizado: $rc_file"
    fi
}

UPDATED=0
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ]; then
        update_shell_rc "$rc"
        UPDATED=1
    fi
done

if [ "$UPDATED" -eq 0 ]; then
    printf "%s\n" "$ALIAS_BLOCK" >> "$HOME/.bashrc"
    echo "  -> Criado: $HOME/.bashrc"
fi

# 4. Avisa se o remote do rclone ainda não foi configurado
REMOTE_NAME="$("$VENV_DIR/bin/python" -c "import json; print(json.load(open('$PROJECT_DIR/config.json', encoding='utf-8')).get('rclone_remote', 'gdrive:Músicas').split(':')[0])")"
if ! rclone listremotes 2>/dev/null | grep -qx "${REMOTE_NAME}:"; then
    echo ""
    echo "[AVISO] O remote '${REMOTE_NAME}:' ainda não está configurado no rclone."
    echo "        Rode 'rclone config' para conectar seu Google Drive."
fi

echo ""
echo "[SUCESSO] Instalação concluída!"
echo "Recarregue seu terminal (ex: 'source ~/.bashrc' ou 'source ~/.zshrc') e use:"
echo "  baixar-musica   -> baixar músicas/álbuns/playlists e enviar ao Drive"
echo "  criar-playlist  -> gerar playlists .m3u interativas direto do Drive"

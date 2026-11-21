import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"
DEFAULT_REMOTE = "gdrive:Músicas"
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".flac", ".ogg", ".opus")


def configure_console_encoding():
    """Garante saída UTF-8 no terminal (especialmente importante no Windows)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def load_remote() -> str:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                remote = config.get("rclone_remote")
                if remote:
                    return str(remote).rstrip("/")
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_REMOTE


def check_rclone():
    if shutil.which("rclone") is None:
        print("[ERRO] Dependência 'rclone' não encontrada no PATH.")
        if os.name == "nt":
            print("  Windows: instale via 'winget install Rclone.Rclone'")
        else:
            print("  Arch Linux: instale via 'sudo pacman -S rclone'")
        sys.exit(1)


def salvar_e_enviar(output_dir: Path, remote: str, nome_arquivo: str, lista_faixas: list[str]):
    if not lista_faixas:
        print(f"Nenhuma faixa encontrada para: {nome_arquivo}")
        return

    caminho_local = output_dir / nome_arquivo
    # Usa newline="\n" (LF) para garantir compatibilidade com Android/Musicolet mesmo gerando no Windows
    with open(caminho_local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(lista_faixas) + "\n")

    subprocess.run(["rclone", "copy", str(caminho_local), f"{remote}/Playlists"], check=True)
    print(f"Enviada: {nome_arquivo} ({len(lista_faixas)} faixas)")


def main():
    configure_console_encoding()
    check_rclone()

    remote = load_remote()
    output_dir = Path(tempfile.gettempdir()) / "playlists_m3u"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Listando biblioteca no Google Drive ({remote})...")
    cmd = ["rclone", "lsf", remote, "-R", "--files-only"]
    arquivos = subprocess.check_output(
        cmd, text=True, encoding="utf-8", errors="replace"
    ).splitlines()

    classicos_50_69: list[str] = []
    flac_only: list[str] = []

    for caminho in sorted(arquivos):
        if not caminho.lower().endswith(AUDIO_EXTENSIONS):
            continue

        partes = caminho.split("/")
        if len(partes) >= 3:
            pasta_album = partes[1]
            ano_str = pasta_album[:4]
            if ano_str.isdigit():
                ano = int(ano_str)
                if 1950 <= ano <= 1969:
                    classicos_50_69.append(f"../{caminho}")

        if caminho.lower().endswith(".flac"):
            flac_only.append(f"../{caminho}")

    salvar_e_enviar(output_dir, remote, "Classicos (1950-1969).m3u", classicos_50_69)
    salvar_e_enviar(output_dir, remote, "Alta Fidelidade (FLAC).m3u", flac_only)


if __name__ == "__main__":
    main()

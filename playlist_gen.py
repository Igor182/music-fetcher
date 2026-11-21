import json
import os
import re
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


def parse_year_range(anos_input: str) -> tuple[int | None, int | None]:
    if not anos_input:
        return None, None

    if "-" in anos_input:
        partes_ano = [p.strip() for p in anos_input.split("-")]
        if len(partes_ano) == 2 and partes_ano[0].isdigit() and partes_ano[1].isdigit():
            inicio, fim = int(partes_ano[0]), int(partes_ano[1])
            return min(inicio, fim), max(inicio, fim)
        print("[AVISO] Intervalo de anos inválido; filtro de ano será ignorado.")
        return None, None

    if anos_input.isdigit():
        ano = int(anos_input)
        return ano, ano

    print("[AVISO] Ano inválido; filtro de ano será ignorado.")
    return None, None


def main():
    configure_console_encoding()
    check_rclone()

    remote = load_remote()
    output_dir = Path(tempfile.gettempdir()) / "playlists_m3u"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        nome_playlist = input("Nome da playlist (ex: Rock Anos 90): ").strip()
        if not nome_playlist:
            print("Nome inválido. Operação cancelada.")
            sys.exit(1)

        nome_arquivo = nome_playlist if nome_playlist.lower().endswith(".m3u") else f"{nome_playlist}.m3u"

        print("\nFiltros opcionais (deixe em branco e aperte Enter para ignorar):")
        anos_input = input("Intervalo de anos (ex: 1990-1999 ou 2005): ").strip()
        artista_input = input("Artistas separados por vírgula (ex: Nirvana, Pearl Jam): ").strip()
        formato_input = input("Formato específico (ex: flac, m4a, mp3): ").strip().lower().lstrip(".")
    except (KeyboardInterrupt, EOFError):
        print("\nOperação cancelada.")
        sys.exit(0)

    artistas_lista = [a.strip().lower() for a in artista_input.split(",") if a.strip()]
    ano_inicio, ano_fim = parse_year_range(anos_input)

    print(f"\nListando biblioteca no Google Drive ({remote})...")
    cmd = ["rclone", "lsf", remote, "-R", "--files-only"]
    arquivos = subprocess.check_output(
        cmd, text=True, encoding="utf-8", errors="replace"
    ).splitlines()

    faixas_filtradas: list[str] = []

    for caminho in sorted(arquivos):
        caminho_lower = caminho.lower()
        if not caminho_lower.endswith(AUDIO_EXTENSIONS):
            continue

        if formato_input and not caminho_lower.endswith(f".{formato_input}"):
            continue

        partes = caminho.split("/")
        artista = partes[0].lower() if len(partes) >= 1 else ""
        pasta_album = partes[1] if len(partes) >= 3 else ""

        if artistas_lista and not any(a in artista for a in artistas_lista):
            continue

        if ano_inicio is not None and ano_fim is not None:
            match_ano = re.search(r"\b(19\d{2}|20\d{2})\b", pasta_album)
            if not match_ano:
                continue
            ano = int(match_ano.group(1))
            if not (ano_inicio <= ano <= ano_fim):
                continue

        faixas_filtradas.append(f"../{caminho}")

    if not faixas_filtradas:
        print("Nenhuma música encontrada com esses critérios.")
        sys.exit(0)

    caminho_local = output_dir / nome_arquivo
    # Usa newline="\n" (LF) para compatibilidade com Android/Musicolet mesmo gerando no Windows
    with open(caminho_local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        f.write("\n".join(faixas_filtradas) + "\n")

    subprocess.run(["rclone", "copy", str(caminho_local), f"{remote}/Playlists"], check=True)
    print(f"\nPlaylist '{nome_arquivo}' enviada para {remote}/Playlists com {len(faixas_filtradas)} faixas!")


if __name__ == "__main__":
    main()

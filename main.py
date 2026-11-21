import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"


def configure_console_encoding():
    """Garante saída UTF-8 no terminal (especialmente importante no Windows)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print(f"[ERRO] Arquivo de configuração não encontrado: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_temp_dir(config: dict) -> Path:
    """Resolve o diretório temporário de forma compatível com Linux e Windows."""
    raw_temp = config.get("temp_dir")
    if not raw_temp:
        return Path(tempfile.gettempdir()) / "music-fetcher-downloads"

    expanded = os.path.expandvars(str(raw_temp))
    return Path(expanded).expanduser()


def resolve_spotdl_command() -> list[str] | None:
    """Localiza o executável spotdl no PATH, no ambiente virtual atual ou via módulo Python."""
    spotdl_path = shutil.which("spotdl")
    if spotdl_path:
        return [spotdl_path]

    exe_name = "spotdl.exe" if os.name == "nt" else "spotdl"
    venv_spotdl = Path(sys.executable).parent / exe_name
    if venv_spotdl.is_file():
        return [str(venv_spotdl)]

    if importlib.util.find_spec("spotdl") is not None:
        return [sys.executable, "-m", "spotdl"]

    return None


def check_dependencies() -> list[str]:
    missing = []

    spotdl_cmd = resolve_spotdl_command()
    if spotdl_cmd is None:
        missing.append("spotdl")

    for cmd in ("ffmpeg", "rclone"):
        if shutil.which(cmd) is None:
            missing.append(cmd)

    if missing:
        print(f"[ERRO] Dependência(s) não encontrada(s): {', '.join(missing)}")
        if os.name == "nt":
            print("  Windows: instale ffmpeg/rclone via 'winget install Gyan.FFmpeg Rclone.Rclone'")
            print("           e ative a venv com '.venv\\Scripts\\Activate.ps1' (ou instale 'pip install -r requirements.txt').")
        else:
            print("  Arch Linux: instale via 'sudo pacman -S ffmpeg rclone'")
            print("              e ative a venv com 'source .venv/bin/activate' (ou instale 'pip install -r requirements.txt').")
        sys.exit(1)

    return spotdl_cmd


def _handle_remove_readonly(func, path, exc_info):
    """Permite remover arquivos somente leitura ao limpar diretórios no Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def safe_rmtree(path: Path):
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_handle_remove_readonly)
    else:
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def format_query(raw_query: str) -> str:
    if raw_query.startswith(("http://", "https://", "album:", "playlist:", "artist:")):
        return raw_query

    print("\nO que você está buscando?")
    print("  [1] Música avulsa (padrão)")
    print("  [2] Álbum completo")
    print("  [3] Playlist / Coletânea (ex: 'This Is Bee Gees' ou 'maiores sucessos 2pac')")
    choice = input("Escolha (1/2/3) [Enter = 1]: ").strip()

    if choice == "2":
        return f"album:{raw_query}"
    if choice == "3":
        return f"playlist:{raw_query}"
    return raw_query


def download_music(query: str, config: dict, spotdl_cmd: list[str]):
    temp_dir = resolve_temp_dir(config)
    safe_rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = str(temp_dir / config["output_template"])
    audio_format = config.get("audio_format", "m4a")
    audio_bitrate = config.get("audio_bitrate", "256k")
    download_threads = str(config.get("download_threads", 4))

    print(f"\n[1/3] Buscando e baixando: '{query}'...")
    cmd = [
        *spotdl_cmd,
        "download",
        query,
        "--output",
        output_pattern,
        "--format",
        audio_format,
        "--bitrate",
        audio_bitrate,
        "--threads",
        download_threads,
    ]

    subprocess_env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    result = subprocess.run(cmd, env=subprocess_env)
    if result.returncode != 0:
        print("\n[AVISO] O download terminou com algum aviso ou erro.")

    downloaded_files = list(temp_dir.rglob(f"*.{audio_format}"))
    if not downloaded_files:
        print("[ERRO] Nenhuma música foi baixada. Verifique o termo pesquisado.")
        return

    print(f"\n[2/3] {len(downloaded_files)} faixa(s) pronta(s):")
    for f in sorted(downloaded_files):
        print(f"  -> {f.relative_to(temp_dir)}")

    rclone_remote = config["rclone_remote"]
    rclone_transfers = str(config.get("rclone_transfers", 3))
    rclone_checkers = str(config.get("rclone_checkers", 4))
    rclone_tpslimit = str(config.get("rclone_tpslimit", 2))
    rclone_retries = str(config.get("rclone_retries", 5))

    print(f"\n[3/3] Enviando para o Google Drive ({rclone_remote})...")
    rclone_cmd = [
        "rclone",
        "move",
        str(temp_dir),
        rclone_remote,
        "--delete-empty-src-dirs",
        "--transfers",
        rclone_transfers,
        "--checkers",
        rclone_checkers,
        "--tpslimit",
        rclone_tpslimit,
        "--retries",
        rclone_retries,
        "--log-level",
        "ERROR",
        "--stats-one-line",
        "--stats",
        "2s",
    ]

    upload = subprocess.run(rclone_cmd)
    if upload.returncode == 0:
        safe_rmtree(temp_dir)
        print("\n[SUCESSO] Músicas enviadas para o Drive! O FolderSync baixará no seu celular na próxima sincronização.")
    else:
        print("\n[ERRO] Falha ao enviar para o Google Drive via rclone.")
        print(f"       Os arquivos foram mantidos em: {temp_dir}")


def main():
    configure_console_encoding()
    spotdl_cmd = check_dependencies()
    config = load_config()

    print("=== Music Fetcher -> Google Drive ===")
    print("Digite o nome da música, álbum, playlist ou cole um link do Spotify/YouTube.")
    print("Digite 'sair' para encerrar.\n")

    while True:
        try:
            raw_query = input("O que você quer baixar? > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando...")
            break

        if not raw_query:
            continue
        if raw_query.lower() in {"sair", "exit", "q"}:
            break

        query = format_query(raw_query)
        download_music(query, config, spotdl_cmd)
        print("\n" + "-" * 50 + "\n")


if __name__ == "__main__":
    main()

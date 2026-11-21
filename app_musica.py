import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def exibir_menu():
    print("\n========================================")
    print("             APP-MUSICA CLI")
    print("========================================")
    print("  [1] Baixar musicas / albuns / playlists (Spotify)")
    print("  [2] Criar / gerar playlist")
    print("  [3] Arrumar pasta de artista (agrupar faixas soltas)")
    print("  [4] Numerar faixas de album (tracklist online / tag interna)")
    print("  [5] Aplicar capa do album nos arquivos (cover.jpg/png)")
    print("  [6] Atualizar repositorio (git pull)")
    print("  [0] Sair")
    print("========================================")


def executar_script(nome_script: str, args_extras: list[str] | None = None):
    cmd = [sys.executable, str(BASE_DIR / nome_script)]
    if args_extras:
        cmd.extend(args_extras)
    subprocess.run(cmd)


def opcao_arrumar_artista():
    artista = input("Nome do artista em gdrive:Músicas (ex: Frank Sinatra): ").strip()
    if not artista:
        print("Artista nao informado. Operacao cancelada.")
        return

    args = [artista]
    simular = input("Simular sem alterar o Drive (--dry-run)? [s/N]: ").strip().lower()
    if simular in {"s", "sim", "y", "yes"}:
        args.append("--dry-run")
    else:
        apagar = input("Apagar duplicatas ja existentes em albuns (--apagar-duplicatas)? [s/N]: ").strip().lower()
        if apagar in {"s", "sim", "y", "yes"}:
            args.append("--apagar-duplicatas")

    executar_script("arrumar_artista.py", args)


def opcao_atualizar_repositorio():
    print(f"\nAtualizando repositorio em {BASE_DIR}...")
    res = subprocess.run(["git", "-C", str(BASE_DIR), "pull"])
    if res.returncode == 0:
        req = BASE_DIR / "requirements.txt"
        if req.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req), "-q"])


def main():
    configure_console_encoding()

    while True:
        exibir_menu()
        try:
            escolha = input("Escolha uma opcao: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando...")
            break

        if escolha in {"0", "sair", "exit", "q"}:
            print("Encerrando...")
            break
        elif escolha == "1":
            executar_script("main.py")
        elif escolha == "2":
            executar_script("playlist_gen.py")
        elif escolha == "3":
            opcao_arrumar_artista()
        elif escolha == "4":
            executar_script("numerar_album.py")
        elif escolha == "5":
            executar_script("aplicar_capa.py")
        elif escolha == "6":
            opcao_atualizar_repositorio()
        else:
            print("Opcao invalida. Escolha um numero de 0 a 6.")


if __name__ == "__main__":
    main()

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

BASE_DIR = Path(__file__).resolve().parent
REMOTE_BASE = "gdrive:M\u00fasicas"
EXTENSOES = {".mp3", ".m4a", ".flac", ".ogg", ".opus"}


def norm(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"^\d+\s*[-._]\s*", "", t)
    t = re.sub(r"\b(ao vivo|live|remastered|remaster|part|feat|citacao|trecho|incluindo|official|audio|video|deluxe|expanded|edition|extra|turne|bonus|faixa bonus|radio edit)\b.*", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def rclone_lsf(caminho, extra_flags):
    res = subprocess.run(
        ["rclone", "lsf", caminho] + extra_flags,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        print("Erro rclone:", res.stderr)
        sys.exit(1)
    return [l.strip().rstrip("/") for l in res.stdout.splitlines() if l.strip()]


def localizar_pasta_album(termo_busca):
    if "/" in termo_busca:
        caminho_direto = f"{REMOTE_BASE}/{termo_busca.strip('/')}"
        check = subprocess.run(["rclone", "lsd", caminho_direto], capture_output=True)
        if check.returncode == 0:
            return termo_busca.strip("/")

    print(f"Procurando pasta correspondente a '{termo_busca}' em {REMOTE_BASE}...")
    pastas = rclone_lsf(REMOTE_BASE, ["-R", "--dirs-only"])
    alvo_norm = norm(termo_busca)

    candidatas = []
    for p in pastas:
        partes = p.split("/")
        if len(partes) < 2:
            continue
        nome_album_pasta = re.sub(r"^(19|20)\d{2}\s*-\s*", "", partes[-1])
        pasta_norm = norm(nome_album_pasta)
        completo_norm = norm(p)

        if alvo_norm in pasta_norm or pasta_norm in alvo_norm or alvo_norm in completo_norm:
            candidatas.append(p)

    if not candidatas:
        print(f"Nenhuma pasta encontrada para '{termo_busca}'.")
        sys.exit(1)

    if len(candidatas) == 1:
        print(f"Pasta selecionada: {candidatas[0]}")
        return candidatas[0]

    print("\nMais de uma pasta encontrada. Escolha o numero:")
    for i, c in enumerate(candidatas, 1):
        print(f"  [{i}] {c}")
    escolha = input("\nNumero da pasta: ").strip()
    if not escolha.isdigit() or not (1 <= int(escolha) <= len(candidatas)):
        print("Opcao invalida.")
        sys.exit(1)
    return candidatas[int(escolha) - 1]


def extrair_playlist(exe, url):
    cmd = [exe, "--flat-playlist", "--dump-single-json", url]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not res.stdout.strip():
        return []
    try:
        dados = json.loads(res.stdout)
        return [e.get("title") for e in (dados.get("entries") or []) if e.get("title")]
    except Exception:
        return []


def buscar_tracklist_yt(consulta, url_direta=None):
    ytdlp_win = BASE_DIR / ".venv" / "Scripts" / "yt-dlp.exe"
    ytdlp_unix = BASE_DIR / ".venv" / "bin" / "yt-dlp"
    exe = str(ytdlp_win) if ytdlp_win.exists() else (str(ytdlp_unix) if ytdlp_unix.exists() else "yt-dlp")

    if url_direta:
        print(f"Extraindo tracklist da URL: {url_direta}...")
        return extrair_playlist(exe, url_direta)

    print(f"Buscando tracklist online para: '{consulta}'...")
    url_busca = f"https://www.youtube.com/results?search_query={consulta.replace(' ', '+')}&sp=EgIQAw%253D%253D"
    cmd_search = [exe, "--flat-playlist", "--dump-single-json", "--playlist-items", "1:5", url_busca]
    res = subprocess.run(cmd_search, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if res.returncode == 0 and res.stdout.strip():
        try:
            dados = json.loads(res.stdout)
            for ent in (dados.get("entries") or []):
                u = ent.get("url") or ent.get("webpage_url") or ""
                if "list=" in u:
                    faixas = extrair_playlist(exe, u)
                    if len(faixas) >= 4:
                        return faixas
        except Exception:
            pass
    return []


def carregar_tracklist_arquivo(caminho_txt):
    p = Path(caminho_txt)
    if not p.exists():
        print(f"Arquivo nao encontrado: {caminho_txt}")
        sys.exit(1)
    linhas = []
    for l in p.read_text(encoding="utf-8").splitlines():
        l = re.sub(r"^\d+\s*[-._)]\s*", "", l.strip())
        if l:
            linhas.append(l)
    return linhas


def encontrar_indice_faixa(nome_arquivo_norm, tracklist_norm):
    for idx, titulo in enumerate(tracklist_norm, start=1):
        if titulo and (titulo == nome_arquivo_norm or titulo in nome_arquivo_norm or nome_arquivo_norm in titulo):
            return idx

    palavras_arq = set(nome_arquivo_norm.split())
    melhor_idx = None
    melhor_score = 0.0

    for idx, titulo in enumerate(tracklist_norm, start=1):
        if not titulo:
            continue
        palavras_tit = set(titulo.split())
        menor_len = min(len(palavras_arq), len(palavras_tit))

        # Proporcao de palavras do titulo menor presentes no maior
        overlap = (len(palavras_arq & palavras_tit) / menor_len) if menor_len > 0 else 0.0
        seq_ratio = SequenceMatcher(None, nome_arquivo_norm, titulo).ratio()

        # Usa o maior sinal entre semelhança textual e contenção de palavras
        score = max(seq_ratio, overlap * 0.95) if menor_len >= 2 else seq_ratio

        if score > melhor_score:
            melhor_score = score
            melhor_idx = idx

    return melhor_idx if melhor_score >= 0.62 else None


def main():
    p = argparse.ArgumentParser(description="Busca um album no Drive, identifica a tracklist e grava tags internas de faixa.")
    p.add_argument("album", nargs="?", help='Nome do album ou caminho "Artista/Album" (se omitido, pergunta no terminal)')
    p.add_argument("--url", help="URL direta da playlist/album no YouTube ou YouTube Music")
    p.add_argument("--lista", help="Arquivo .txt local com as faixas na ordem (uma por linha)")
    p.add_argument("--dry-run", action="store_true", help="Apenas simula sem alterar arquivos no Drive")
    p.add_argument("-y", "--yes", action="store_true", help="Aplica direto sem pedir confirmacao")
    args = p.parse_args()

    termo = args.album or input("Digite o nome do album que deseja numerar: ").strip()
    if not termo:
        print("Nenhum album informado.")
        sys.exit(1)

    caminho_relativo = localizar_pasta_album(termo)
    remoto = f"{REMOTE_BASE}/{caminho_relativo}"

    if args.lista:
        faixas = carregar_tracklist_arquivo(args.lista)
    else:
        partes = caminho_relativo.split("/")
        limpas = [re.sub(r"^(19|20)\d{2}\s*-\s*", "", x) for x in partes]
        limpas = [re.sub(r"\(.*?\)", "", x).strip() for x in limpas]
        consulta = " ".join(limpas)
        faixas = buscar_tracklist_yt(consulta, args.url)

    if not faixas:
        print("\nNao foi possivel obter a tracklist automaticamente.")
        url_manual = input("Cole a URL de uma playlist do YouTube (ou Enter para sair): ").strip()
        if url_manual:
            faixas = buscar_tracklist_yt("", url_manual)
        if not faixas:
            sys.exit(1)

    total = len(faixas)
    tracklist_norm = [norm(f) for f in faixas]
    arquivos = sorted(rclone_lsf(remoto, ["--files-only"]))

    plano = []
    sem_match = []
    for arq in arquivos:
        path = Path(arq)
        if path.suffix.lower() not in EXTENSOES:
            continue
        nome_limpo_arquivo = re.sub(r"^\d{2}\s*-\s*", "", path.name)
        nome_busca = norm(Path(nome_limpo_arquivo).stem)
        num = encontrar_indice_faixa(nome_busca, tracklist_norm)
        if num:
            plano.append((arq, nome_limpo_arquivo, num))
        else:
            sem_match.append(arq)

    print(f"\nPrevia para '{caminho_relativo}' ({len(plano)}/{len(plano)+len(sem_match)} faixas identificadas):")
    for _, nome_limpo, num in sorted(plano, key=lambda x: x[2]):
        print(f"  [{num:02d}/{total:02d}] {nome_limpo}")
    for arq in sem_match:
        print(f"  [SEM MATCH] {arq}")

    if args.dry_run or not plano:
        return

    if not args.yes:
        resp = input("\nAplicar essas tags de faixa no Google Drive? [S/n] (ou cole uma URL do YouTube): ").strip()
        if resp.startswith("http"):
            subprocess.run([sys.executable, __file__, caminho_relativo, "--url", resp, "-y"], check=True)
            return
        if resp.lower() in {"n", "nao", "não"}:
            print("Operacao cancelada.")
            return

    tmp = BASE_DIR / ".tmp_numerar"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    for arq, nome_limpo, num in plano:
        path = Path(arq)
        local = tmp / nome_limpo
        subprocess.run(["rclone", "copyto", f"{remoto}/{arq}", str(local)], check=True, capture_output=True)

        if path.suffix.lower() == ".m4a":
            m4a = MP4(local)
            m4a["trkn"] = [(num, total)]
            m4a.save()
        elif path.suffix.lower() == ".mp3":
            mp3 = MP3(local, ID3=EasyID3)
            mp3["tracknumber"] = f"{num}/{total}"
            mp3.save()

        subprocess.run(["rclone", "copyto", str(local), f"{remoto}/{nome_limpo}"], check=True, capture_output=True)
        if arq != nome_limpo:
            subprocess.run(["rclone", "deletefile", f"{remoto}/{arq}"], check=True, capture_output=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nConcluido! {len(plano)} faixas atualizadas com sucesso.")


if __name__ == "__main__":
    main()

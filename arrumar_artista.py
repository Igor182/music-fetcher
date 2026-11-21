import argparse
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from mutagen import File as MutagenFile

BASE_DIR = Path(__file__).resolve().parent
REMOTE_BASE = "gdrive:M\u00fasicas"
EXTENSOES_AUDIO = {".mp3", ".m4a", ".flac", ".ogg", ".opus"}


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"^\d+\s*[-._]\s*", "", texto)
    texto = re.sub(r"\(\d+\)$", "", texto)
    texto = re.sub(r"\b(remastered|remaster|live at|live in|live|mono|stereo|version|edit|deluxe|expanded|edition)\b.*", "", texto)
    texto = re.sub(r"\b(19|20)\d{2}\b.*", "", texto)
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def normalizar_pasta_album(nome_pasta):
    sem_ano = re.sub(r"^(\d{4}|0000)\s*-\s*", "", nome_pasta.strip())
    return normalizar(sem_ano)


def sanitizar(nome):
    return re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*]', "", str(nome))).strip()


def rclone_lsf(caminho, extra):
    res = subprocess.run(["rclone", "lsf", caminho] + extra, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print("Erro rclone:", res.stderr)
        sys.exit(1)
    return [l.strip() for l in res.stdout.splitlines() if l.strip()]


def ler_tags_locais(caminho):
    audio = MutagenFile(caminho, easy=True)
    if not audio:
        return None
    album = (audio.get("album") or [""])[0].strip()
    if not album:
        return None
    data = (audio.get("date") or audio.get("originaldate") or [""])[0]
    m_ano = re.search(r"(19|20)\d{2}", str(data))
    ano = m_ano.group(0) if m_ano else ""
    faixa_raw = (audio.get("tracknumber") or ["1"])[0]
    m_tr = re.search(r"\d+", str(faixa_raw))
    faixa = int(m_tr.group(0)) if m_tr else 1
    titulo = (audio.get("title") or [caminho.stem])[0].strip()
    return {"album": album, "year": ano, "track": faixa, "title": titulo}


def encontrar_pasta_destino(meta, pastas_existentes):
    album_norm = normalizar(meta["album"])

    for chave_norm, nome_real in pastas_existentes.items():
        if chave_norm == album_norm or (album_norm and (album_norm in chave_norm or chave_norm in album_norm)):
            return nome_real

    if meta["year"]:
        nova_pasta = sanitizar(f"{meta['year']} - {meta['album']}")
    else:
        nova_pasta = sanitizar(meta["album"])

    pastas_existentes[album_norm] = nova_pasta
    return nova_pasta


def main():
    p = argparse.ArgumentParser(description="Organiza musicas soltas de um artista em pastas de albuns no Google Drive.")
    p.add_argument("artista", help='Nome da pasta do artista em gdrive:Músicas (ex: "Frank Sinatra")')
    p.add_argument("--dry-run", action="store_true", help="Simula as alteracoes sem modificar o Drive")
    p.add_argument("--apagar-duplicatas", action="store_true", help="Remove arquivos soltos que ja existem dentro de albuns")
    args = p.parse_args()

    artista = args.artista.strip()
    remoto = f"{REMOTE_BASE}/{artista}"
    print(f"Analisando {remoto}...")
    todos = rclone_lsf(remoto, ["-R", "--files-only"])

    soltos = []
    existentes = set()
    pastas_existentes = {}

    for rel in todos:
        partes = [x for x in rel.replace("\\", "/").split("/") if x]
        path = Path(rel)
        if path.suffix.lower() not in EXTENSOES_AUDIO:
            continue
        if len(partes) == 1:
            soltos.append(rel)
        else:
            existentes.add(normalizar(path.stem))
            pasta_topo = partes[0]
            chave = normalizar_pasta_album(pasta_topo)
            if chave not in pastas_existentes or re.match(r"^(19|20)\d{2}\s*-", pasta_topo):
                pastas_existentes[chave] = pasta_topo

    print(f"Encontrados {len(soltos)} soltos, {len(existentes)} faixas em albuns e {len(pastas_existentes)} pastas de albuns.\n")
    tmp = BASE_DIR / ".tmp_tags" / sanitizar(artista)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    movidos = dup = sem_tag = 0
    for arq in sorted(soltos):
        norm = normalizar(Path(arq).stem)
        if norm in existentes:
            dup += 1
            print(f"[DUPLICATA] {arq}")
            if not args.dry_run and args.apagar_duplicatas:
                subprocess.run(["rclone", "deletefile", f"{remoto}/{arq}"], check=True)
            continue

        local = tmp / arq
        subprocess.run(["rclone", "copyto", f"{remoto}/{arq}", str(local)], check=True, capture_output=True)
        meta = ler_tags_locais(local)
        if not meta:
            sem_tag += 1
            print(f"[SEM TAG INTERNA] {arq}")
            continue

        pasta = encontrar_pasta_destino(meta, pastas_existentes)
        nome_final = sanitizar(f"{meta['track']:02d} - {meta['title']}{Path(arq).suffix.lower()}")
        print(f"[MOVER] {arq}  -->  {pasta}/{nome_final}")
        existentes.add(norm)
        movidos += 1

        if not args.dry_run:
            subprocess.run(["rclone", "moveto", f"{remoto}/{arq}", f"{remoto}/{pasta}/{nome_final}"], check=True, capture_output=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nResumo: {movidos} movidos | {dup} duplicatas | {sem_tag} sem tag interna")


if __name__ == "__main__":
    main()

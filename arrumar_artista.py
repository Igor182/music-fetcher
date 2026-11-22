import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

BASE_DIR = Path(__file__).resolve().parent
REMOTE_BASE = "gdrive:M\u00fasicas"
EXTENSOES_AUDIO = {".mp3", ".m4a", ".flac", ".ogg", ".opus"}
USER_AGENT = "music-fetcher/1.0 (https://github.com/Igor182/music-fetcher)"


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


def limpar_titulo_arquivo(stem, artista=""):
    t = str(stem).strip()
    t = re.sub(r"^\d+\s*[-._)]\s*", "", t)
    if artista:
        padrao_art = re.compile(r"^" + re.escape(artista.strip()) + r"\s*[-_]\s*", re.IGNORECASE)
        t = padrao_art.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or str(stem).strip()


def pontuar_title_case(nome_pasta):
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", nome_pasta)
    if not palavras:
        return (0, 0)
    iniciais_maiusculas = sum(1 for p in palavras if p[0].isupper() and (len(p) == 1 or not p.isupper()))
    todas_maiusculas = sum(1 for p in palavras if p[0].isupper())
    return (iniciais_maiusculas, todas_maiusculas)


def escolher_pasta_title_case(nomes_pastas):
    melhor = max(nomes_pastas, key=lambda n: (pontuar_title_case(n), -len(n)))
    if pontuar_title_case(melhor)[1] == 0:
        return sanitizar(melhor).title()
    return sanitizar(melhor)


def mesclar_pastas_duplicadas(remoto, todos_arquivos, dry_run=False, apagar_duplicatas=False):
    pastas_top = {}
    arquivos_por_pasta = {}

    for rel in todos_arquivos:
        partes = [x for x in rel.replace("\\", "/").split("/") if x]
        if len(partes) < 2:
            continue
        topo = partes[0]
        resto = "/".join(partes[1:])
        chave_ci = re.sub(r"\s+", " ", topo).strip().lower()
        pastas_top.setdefault(chave_ci, set()).add(topo)
        arquivos_por_pasta.setdefault(topo, []).append(resto)

    mescladas = 0
    for chave_ci, grupo in pastas_top.items():
        if len(grupo) <= 1:
            continue

        lista_grupo = sorted(grupo)
        destino = escolher_pasta_title_case(lista_grupo)
        origens = [p for p in lista_grupo if p != destino]

        print(f"[PASTA DUPLICADA] Mesclando {origens} --> '{destino}'")
        existentes_destino = {
            normalizar(Path(arq).stem)
            for arq in arquivos_por_pasta.get(destino, [])
        }
        nomes_destino_ci = {
            arq.lower()
            for arq in arquivos_por_pasta.get(destino, [])
        }

        for origem in origens:
            for arq_rel in sorted(arquivos_por_pasta.get(origem, [])):
                stem_norm = normalizar(Path(arq_rel).stem)
                if arq_rel.lower() in nomes_destino_ci or (stem_norm and stem_norm in existentes_destino):
                    print(f"  [MESCLAR - DUPLICATA] {origem}/{arq_rel} (ja existe em {destino})")
                    if not dry_run and apagar_duplicatas:
                        subprocess.run(
                            ["rclone", "deletefile", f"{remoto}/{origem}/{arq_rel}"],
                            check=True,
                            capture_output=True,
                        )
                    continue

                print(f"  [MESCLAR] {origem}/{arq_rel}  -->  {destino}/{arq_rel}")
                existentes_destino.add(stem_norm)
                nomes_destino_ci.add(arq_rel.lower())
                mescladas += 1

                if not dry_run:
                    subprocess.run(
                        ["rclone", "moveto", f"{remoto}/{origem}/{arq_rel}", f"{remoto}/{destino}/{arq_rel}"],
                        check=True,
                        capture_output=True,
                    )

            if not dry_run:
                subprocess.run(["rclone", "rmdir", f"{remoto}/{origem}"], capture_output=True)

    if mescladas > 0:
        print(f"Pastas mescladas ({mescladas} arquivo(s) realocado(s)).\n")
    return mescladas


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


def gravar_tags_locais(caminho, artista, meta):
    try:
        if caminho.suffix.lower() == ".mp3":
            try:
                audio = EasyID3(caminho)
            except ID3NoHeaderError:
                audio = MutagenFile(caminho, easy=True)
                if audio is None:
                    return False
                audio.add_tags()
        else:
            audio = MutagenFile(caminho, easy=True)
            if audio is None:
                return False

        if meta.get("album"):
            audio["album"] = [str(meta["album"])]
        if meta.get("title"):
            audio["title"] = [str(meta["title"])]
        if artista:
            audio["artist"] = [str(artista)]
        if meta.get("track"):
            audio["tracknumber"] = [str(meta["track"])]
        if meta.get("year"):
            audio["date"] = [str(meta["year"])]
        audio.save()
        return True
    except Exception:
        return False


def _carregar_credenciais_spotify():
    cid = os.environ.get("SPOTIPY_CLIENT_ID")
    secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    if cid and secret:
        return cid, secret

    possiveis = [
        Path.home() / ".spotdl" / "config.json",
        Path.home() / ".config" / "spotdl" / "config.json",
    ]
    appdata = os.environ.get("APPDATA") or os.environ.get("USERPROFILE")
    if appdata:
        possiveis.append(Path(appdata) / ".spotdl" / "config.json")

    for cfg_path in possiveis:
        if cfg_path.is_file():
            try:
                dados = json.loads(cfg_path.read_text(encoding="utf-8"))
                if dados.get("client_id") and dados.get("client_secret"):
                    return dados["client_id"], dados["client_secret"]
            except Exception:
                pass
    return None, None


def _buscar_spotify(artista, titulo_limpo):
    cid, secret = _carregar_credenciais_spotify()
    if not (cid and secret):
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        sp = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(client_id=cid, client_secret=secret),
            requests_timeout=8,
        )
        q = f'artist:"{artista}" track:"{titulo_limpo}"'
        res = sp.search(q=q, type="track", limit=5)
        items = (res.get("tracks") or {}).get("items") or []
        if not items:
            res = sp.search(q=f"{artista} {titulo_limpo}", type="track", limit=5)
            items = (res.get("tracks") or {}).get("items") or []

        art_norm = normalizar(artista)
        for item in items:
            artistas_item = [normalizar(a.get("name", "")) for a in (item.get("artists") or [])]
            if art_norm and not any(art_norm in a or a in art_norm for a in artistas_item if a):
                continue
            album_obj = item.get("album") or {}
            album_nome = (album_obj.get("name") or "").strip()
            if not album_nome:
                continue
            release_date = album_obj.get("release_date") or ""
            m_ano = re.search(r"(19|20)\d{2}", release_date)
            ano = m_ano.group(0) if m_ano else ""
            faixa = int(item.get("track_number") or 1)
            titulo = (item.get("name") or titulo_limpo).strip()
            return {"album": album_nome, "year": ano, "track": faixa, "title": titulo}
    except Exception:
        return None
    return None


def _buscar_musicbrainz(artista, titulo_limpo):
    query = f'artist:"{artista}" AND recording:"{titulo_limpo}"'
    url = f"https://musicbrainz.org/ws/2/recording/?query={urllib.parse.quote(query)}&fmt=json&limit=5"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            dados = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    finally:
        time.sleep(1.0)

    art_norm = normalizar(artista)
    for rec in dados.get("recordings") or []:
        creditos = rec.get("artist-credit") or []
        nomes_art = [normalizar(c.get("name") or (c.get("artist") or {}).get("name", "")) for c in creditos if isinstance(c, dict)]
        if art_norm and nomes_art and not any(art_norm in a or a in art_norm for a in nomes_art if a):
            continue

        releases = rec.get("releases") or []
        if not releases:
            continue

        escolhido = releases[0]
        for rel in releases:
            rg = rel.get("release-group") or {}
            prim = (rg.get("primary-type") or "").lower()
            sec = [s.lower() for s in (rg.get("secondary-types") or [])]
            if prim == "album" and "compilation" not in sec and "live" not in sec:
                escolhido = rel
                break

        album_nome = (escolhido.get("title") or "").strip()
        if not album_nome:
            continue

        data = escolhido.get("date") or rec.get("first-release-date") or ""
        m_ano = re.search(r"(19|20)\d{2}", str(data))
        ano = m_ano.group(0) if m_ano else ""

        faixa = None
        for media in escolhido.get("media") or []:
            tracks = media.get("track") or []
            if tracks:
                num_str = str(tracks[0].get("number") or "")
                m_tr = re.search(r"\d+", num_str)
                if m_tr:
                    faixa = int(m_tr.group(0))
                    break

        titulo = (rec.get("title") or titulo_limpo).strip()
        return {"album": album_nome, "year": ano, "track": faixa, "title": titulo}

    return None


def buscar_metadados_online(artista, stem_arquivo):
    titulo_limpo = limpar_titulo_arquivo(stem_arquivo, artista)
    meta = _buscar_spotify(artista, titulo_limpo)
    if meta:
        return meta
    return _buscar_musicbrainz(artista, titulo_limpo)


def encontrar_pasta_destino(meta, pastas_existentes):
    album_norm = normalizar(meta["album"])

    for chave_norm, nome_real in pastas_existentes.items():
        if chave_norm == album_norm or (album_norm and (album_norm in chave_norm or chave_norm in album_norm)):
            return nome_real

    if meta.get("year"):
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

    mescladas = mesclar_pastas_duplicadas(
        remoto,
        todos,
        dry_run=args.dry_run,
        apagar_duplicatas=args.apagar_duplicatas,
    )
    if mescladas > 0 and not args.dry_run:
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

    movidos = tag_online = dup = sem_tag = 0
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
            meta_online = buscar_metadados_online(artista, Path(arq).stem)
            if not meta_online:
                sem_tag += 1
                print(f"[SEM TAG INTERNA] {arq}")
                continue

            gravou = gravar_tags_locais(local, artista, meta_online)
            pasta = encontrar_pasta_destino(meta_online, pastas_existentes)
            nome_final = sanitizar(Path(arq).name)
            print(f"[TAG ONLINE] {arq}  -->  {pasta}/{nome_final}")
            existentes.add(norm)
            movidos += 1
            tag_online += 1

            if not args.dry_run:
                if gravou:
                    subprocess.run(["rclone", "copyto", str(local), f"{remoto}/{pasta}/{nome_final}"], check=True, capture_output=True)
                    subprocess.run(["rclone", "deletefile", f"{remoto}/{arq}"], check=True, capture_output=True)
                else:
                    subprocess.run(["rclone", "moveto", f"{remoto}/{arq}", f"{remoto}/{pasta}/{nome_final}"], check=True, capture_output=True)
            continue

        pasta = encontrar_pasta_destino(meta, pastas_existentes)
        nome_final = sanitizar(f"{meta['track']:02d} - {meta['title']}{Path(arq).suffix.lower()}")
        print(f"[MOVER] {arq}  -->  {pasta}/{nome_final}")
        existentes.add(norm)
        movidos += 1

        if not args.dry_run:
            subprocess.run(["rclone", "moveto", f"{remoto}/{arq}", f"{remoto}/{pasta}/{nome_final}"], check=True, capture_output=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nResumo: {movidos} movidos ({tag_online} via tag online) | {dup} duplicatas | {sem_tag} sem tag interna")


if __name__ == "__main__":
    main()

import argparse
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

BASE_DIR = Path(__file__).resolve().parent
REMOTE_BASE = "gdrive:M\u00fasicas"
EXTENSOES_AUDIO = {".mp3", ".m4a"}
EXTENSOES_IMG = {".jpg", ".jpeg", ".png"}


def norm(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
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


def localizar_pasta(termo):
    if "/" in termo:
        check = subprocess.run(["rclone", "lsd", f"{REMOTE_BASE}/{termo.strip('/')}"], capture_output=True)
        if check.returncode == 0:
            return termo.strip("/")

    pastas = rclone_lsf(REMOTE_BASE, ["-R", "--dirs-only"])
    alvo = norm(termo)
    candidatas = [p for p in pastas if "/" in p and (alvo in norm(p.split("/")[-1]) or alvo in norm(p))]

    if not candidatas:
        print(f"Nenhuma pasta encontrada para '{termo}'.")
        sys.exit(1)
    if len(candidatas) == 1:
        return candidatas[0]

    for i, c in enumerate(candidatas, 1):
        print(f"  [{i}] {c}")
    idx = int(input("Escolha o numero da pasta: ").strip()) - 1
    return candidatas[idx]


def escolher_imagem(arquivos, nome_forcado=None):
    imagens = [a for a in arquivos if Path(a).suffix.lower() in EXTENSOES_IMG]
    if not imagens:
        print("Nenhuma imagem encontrada dentro da pasta do album.")
        sys.exit(1)

    if nome_forcado and nome_forcado in imagens:
        return nome_forcado

    for padrao in ["cover.jpg", "cover.png", "folder.jpg", "folder.png"]:
        for img in imagens:
            if img.lower() == padrao:
                return img

    if len(imagens) == 1:
        return imagens[0]

    print("\nImagens encontradas na pasta:")
    for i, img in enumerate(imagens, 1):
        print(f"  [{i}] {img}")
    idx = int(input("Qual imagem usar como capa? ").strip()) - 1
    return imagens[idx]


def embutir_capa(caminho_audio, bytes_img, is_png):
    ext = caminho_audio.suffix.lower()
    if ext == ".mp3":
        try:
            tags = ID3(caminho_audio)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime="image/png" if is_png else "image/jpeg",
                type=3,
                desc="Cover",
                data=bytes_img,
            )
        )
        tags.save(caminho_audio, v2_version=3)
    elif ext == ".m4a":
        m4a = MP4(caminho_audio)
        fmt = MP4Cover.FORMAT_PNG if is_png else MP4Cover.FORMAT_JPEG
        m4a["covr"] = [MP4Cover(bytes_img, imageformat=fmt)]
        m4a.save()


def main():
    p = argparse.ArgumentParser(description="Embute a capa ja existente na pasta do album dentro dos arquivos MP3/M4A.")
    p.add_argument("album", nargs="?", help='Nome do album (ex: "Return Of The Dream Canteen")')
    p.add_argument("--imagem", help='Nome especifico da imagem na pasta (ex: "cover.jpg")')
    args = p.parse_args()

    termo = args.album or input("Nome do album: ").strip()
    caminho_rel = localizar_pasta(termo)
    remoto = f"{REMOTE_BASE}/{caminho_rel}"
    print(f"Pasta: {caminho_rel}")

    arquivos = sorted(rclone_lsf(remoto, ["--files-only"]))
    img_nome = escolher_imagem(arquivos, args.imagem)
    audios = [a for a in arquivos if Path(a).suffix.lower() in EXTENSOES_AUDIO]
    print(f"Capa: {img_nome} | Baixando {len(audios)} faixas em paralelo...")

    tmp = BASE_DIR / ".tmp_capa"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["rclone", "copy", remoto, str(tmp), "--max-depth", "1", "--transfers", "8"],
        check=True,
        capture_output=True,
    )

    local_img = tmp / img_nome
    bytes_img = local_img.read_bytes()
    is_png = local_img.suffix.lower() == ".png"
    local_img.unlink()

    for f in list(tmp.iterdir()):
        if f.suffix.lower() not in EXTENSOES_AUDIO:
            f.unlink()
        else:
            embutir_capa(f, bytes_img, is_png)
            print(f"  [OK] {f.name}")

    print("\nEnviando faixas atualizadas em lote para o Drive...")
    subprocess.run(
        ["rclone", "copy", str(tmp), remoto, "--transfers", "8"],
        check=True,
        capture_output=True,
    )

    shutil.rmtree(tmp, ignore_errors=True)
    print("Concluido!")


if __name__ == "__main__":
    main()

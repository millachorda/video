"""
Vídeo completo de cada caso: cuando se publica la última parte de una serie, junta todas las
partes (que bot.py guarda en la release 'partes' y apunta en partes.json) en un vídeo largo
horizontal para YouTube, con intro narrada, portadilla antes de cada parte, cierre, capítulos
en la descripción y miniatura. Los vídeos largos convierten mucho mejor en suscriptores.

Para probarlo sin publicar:  PRUEBA=true python recopilacion.py "<título del caso>"
"""
import asyncio
import json
import os
import subprocess
import sys
import textwrap

import edge_tts
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import youtube
from canales import ACTUAL as CANAL, ruta

TEXTOS = CANAL["completo"]
PARTES = ruta("partes.json")
RELEASE = CANAL["release"]  # Una por canal: los archivos Episodio_N.mp4 se llaman igual en todos
CARPETA = "completo"
ANCHO, ALTO = 1920, 1080
FUENTE = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
VOZ = os.environ.get("VOZ") or "es-ES-AlvaroNeural"
AMARILLO = (255, 222, 0)
# Mismos parámetros en todos los trozos para poder unirlos sin recodificar
CODIFICACION = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", "30", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k"]


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duracion(archivo):
    salida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", archivo], capture_output=True, text=True, check=True)
    return float(salida.stdout.strip())


def leer_partes():
    return json.load(open(PARTES, encoding="utf-8")) if os.path.exists(PARTES) else []


def guardar_parte(archivo, n_episodio, caso, parte, total):
    """Sube el vídeo de una parte a la release 'partes' y lo apunta en partes.json."""
    if subprocess.run(["gh", "release", "view", RELEASE], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", RELEASE, "--title", "Partes pendientes",
                        "--notes", "Partes de las series en curso; se borran al publicar el vídeo completo."],
                       check=True)
    subprocess.run(["gh", "release", "upload", RELEASE, archivo, "--clobber"], check=True)
    partes = leer_partes()
    partes.append({"episodio": int(n_episodio), "caso": caso, "parte": parte, "total": total,
                   "archivo": os.path.basename(archivo)})
    json.dump(partes, open(PARTES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def fondo_oscuro():
    img = Image.new("RGB", (ANCHO, ALTO))
    d = ImageDraw.Draw(img)
    for y in range(ALTO):
        t = y / ALTO
        d.line([(0, y), (ANCHO, y)], fill=(int(14 + 30 * t), int(8 + 10 * t), int(28 + 50 * t)))
    return img


def tarjeta(arriba, texto, archivo):
    """Portadilla: una etiqueta en amarillo y el texto en blanco, centrados."""
    img = fondo_oscuro()
    d = ImageDraw.Draw(img)
    f_arriba, f_texto = ImageFont.truetype(FUENTE, 90), ImageFont.truetype(FUENTE, 72)
    lineas = textwrap.wrap(texto.upper(), width=30)[:4]
    y = (ALTO - (120 + 90 * len(lineas))) // 2
    for linea, fuente, color in [(arriba, f_arriba, AMARILLO)] + [(l, f_texto, (255, 255, 255)) for l in lineas]:
        d.text(((ANCHO - d.textlength(linea, font=fuente)) / 2, y), linea, font=fuente, fill=color,
               stroke_width=5, stroke_fill=(0, 0, 0))
        y += 120 if fuente is f_arriba else 90
    img.save(archivo)


def tarjeta_a_video(imagen, segundos, salida, audio=None):
    entrada_audio = ["-i", audio] if audio else ["-f", "lavfi", "-t", str(segundos), "-i",
                                                 "anullsrc=r=44100:cl=stereo"]
    ffmpeg("-loop", "1", "-t", str(segundos), "-i", imagen, *entrada_audio,
           "-map", "0:v", "-map", "1:a", "-af", "apad", "-t", str(segundos), *CODIFICACION, salida)


def vertical_a_horizontal(entrada, salida):
    """El vídeo vertical en el centro y, detrás, él mismo ampliado, desenfocado y oscurecido."""
    ffmpeg("-i", entrada, "-filter_complex",
           f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,crop={ANCHO}:{ALTO},"
           f"boxblur=30:3,eq=brightness=-0.25[fondo];[0:v]scale=-2:{ALTO}[frente];"
           "[fondo][frente]overlay=(W-w)/2:0,fps=30[v]",
           "-map", "[v]", "-map", "0:a", *CODIFICACION, salida)


def miniatura(video, caso, salida):
    """Fotograma de la primera parte, ampliado y oscurecido, con el título del caso en grande."""
    ffmpeg("-ss", "3", "-i", video, "-frames:v", "1", f"{CARPETA}/fotograma.png")
    foto = Image.open(f"{CARPETA}/fotograma.png").convert("RGB")
    fondo = foto.resize((1280, int(1280 * foto.height / foto.width))).crop((0, 0, 1280, 720))
    fondo = fondo.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.55))
    fondo.paste(foto.resize((int(720 * foto.width / foto.height), 720)), (860, 0))
    d = ImageDraw.Draw(fondo)
    d.text((50, 50), TEXTOS["etiqueta"], font=ImageFont.truetype(FUENTE, 70), fill=AMARILLO,
           stroke_width=6, stroke_fill=(0, 0, 0))
    y = 160
    for linea in textwrap.wrap(caso.upper(), width=16)[:4]:
        d.text((50, y), linea, font=ImageFont.truetype(FUENTE, 92), fill=(255, 255, 255),
               stroke_width=7, stroke_fill=(0, 0, 0))
        y += 110
    fondo.save(salida)


def tiempo(segundos):
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def publicar_caso(caso, publicar=True):
    """Monta y (si publicar) sube el vídeo completo del caso; devuelve el enlace o None."""
    partes = sorted([p for p in leer_partes() if p["caso"] == caso], key=lambda p: p["parte"])
    if not partes:
        print("No hay partes guardadas de este caso.")
        return None
    os.makedirs(CARPETA, exist_ok=True)
    for p in partes:
        subprocess.run(["gh", "release", "download", RELEASE, "-p", p["archivo"], "-D", CARPETA, "--clobber"],
                       check=True)
    print(f"Montando el caso completo con {len(partes)} partes...")

    trozos, capitulos, t = [], [], 0.0

    def añadir(archivo, capitulo=None):
        nonlocal t
        if capitulo:
            capitulos.append(f"{tiempo(t)} {capitulo}")
        trozos.append(archivo)
        t += duracion(archivo)

    # Si la voz no devuelve audio (le pasa a veces a la multilingüe), se prueba con otras
    for voz in [VOZ, "en-US-BrianMultilingualNeural", "es-ES-AlvaroNeural"]:
        try:
            asyncio.run(edge_tts.Communicate(TEXTOS["intro"].format(caso=caso), voz).save(f"{CARPETA}/intro.mp3"))
            break
        except edge_tts.exceptions.NoAudioReceived as e:
            print(f"Aviso: la voz {voz} no respondió ({e}); pruebo con otra...")
    else:
        raise RuntimeError("ninguna voz respondió para la introducción")
    tarjeta(TEXTOS["etiqueta"], caso, f"{CARPETA}/intro.png")
    tarjeta_a_video(f"{CARPETA}/intro.png", duracion(f"{CARPETA}/intro.mp3") + 0.6,
                    f"{CARPETA}/00_intro.mp4", audio=f"{CARPETA}/intro.mp3")
    añadir(f"{CARPETA}/00_intro.mp4", "Introducción")

    for p in partes:
        k = p["parte"]
        tarjeta(f"PARTE {k}", caso, f"{CARPETA}/t{k}.png")
        tarjeta_a_video(f"{CARPETA}/t{k}.png", 2, f"{CARPETA}/{k:02d}a.mp4")
        añadir(f"{CARPETA}/{k:02d}a.mp4", f"Parte {k}")
        vertical_a_horizontal(f"{CARPETA}/{p['archivo']}", f"{CARPETA}/{k:02d}b.mp4")
        añadir(f"{CARPETA}/{k:02d}b.mp4")

    tarjeta(*TEXTOS["fin"], f"{CARPETA}/fin.png")
    tarjeta_a_video(f"{CARPETA}/fin.png", 5, f"{CARPETA}/99_fin.mp4")
    añadir(f"{CARPETA}/99_fin.mp4", "Final")

    with open(f"{CARPETA}/lista.txt", "w") as f:
        f.writelines(f"file '{os.path.basename(x)}'\n" for x in trozos)
    salida = f"{CARPETA}/caso_completo.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", f"{CARPETA}/lista.txt", "-c", "copy", "-movflags", "+faststart",
           salida)
    print(f"Caso completo listo: {tiempo(t)}, {os.path.getsize(salida) / 1e6:.0f} MB.")
    if not publicar or not youtube.configurado():
        return None

    descripcion = (TEXTOS["descripcion"].format(caso=caso) + "\n\n" + "\n".join(capitulos)
                   + "\n\n" + TEXTOS["hashtags"])
    video_id, enlace = youtube.subir(salida, TEXTOS["titulo"].format(caso=caso)[:100], descripcion,
                                     TEXTOS["etiquetas"], short=False, categoria=CANAL["categoria"])
    print(f"Caso completo publicado: {enlace}")
    try:
        miniatura(f"{CARPETA}/{partes[0]['archivo']}", caso, f"{CARPETA}/miniatura.png")
        youtube.poner_miniatura(video_id, f"{CARPETA}/miniatura.png")
    except Exception as e:
        print(f"AVISO: no se pudo poner la miniatura (hace falta verificar el canal por teléfono): {e}")

    # Las partes ya no hacen falta: fuera de la lista y de la release
    json.dump([p for p in leer_partes() if p["caso"] != caso], open(PARTES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for p in partes:
        subprocess.run(["gh", "release", "delete-asset", RELEASE, p["archivo"], "--yes"], check=False)
    return enlace


if __name__ == "__main__":
    publicar_caso(sys.argv[1], publicar=os.environ.get("PRUEBA") != "true")

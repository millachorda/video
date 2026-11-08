"""
Recopilación semanal: junta los vídeos de la semana (los que bot.py guarda en la release
'semana' y apunta en semana.json) en un vídeo largo horizontal para YouTube, con intro
narrada, portadilla antes de cada vídeo, cierre, capítulos en la descripción y miniatura.
Los vídeos largos convierten mucho mejor en suscriptores que los Shorts.
"""
import asyncio
import json
import os
import subprocess
import textwrap

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import youtube

SEMANA = "semana.json"
CARPETA = "recopilacion"
MINIMO = 3                      # Con menos vídeos no merece la pena
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


def fondo_oscuro():
    img = Image.new("RGB", (ANCHO, ALTO))
    d = ImageDraw.Draw(img)
    for y in range(ALTO):
        t = y / ALTO
        d.line([(0, y), (ANCHO, y)], fill=(int(14 + 30 * t), int(8 + 10 * t), int(28 + 50 * t)))
    return img


def tarjeta(arriba, texto, archivo):
    """Portadilla: una etiqueta en amarillo y el título en blanco, centrados."""
    img = fondo_oscuro()
    d = ImageDraw.Draw(img)
    f_arriba, f_texto = ImageFont.truetype(FUENTE, 90), ImageFont.truetype(FUENTE, 72)
    lineas = textwrap.wrap(texto.upper(), width=30)[:4]
    alto_total = 120 + 90 * len(lineas)
    y = (ALTO - alto_total) // 2
    for linea, fuente, color in [(arriba, f_arriba, AMARILLO)] + [(l, f_texto, (255, 255, 255)) for l in lineas]:
        ancho = d.textlength(linea, font=fuente)
        d.text(((ANCHO - ancho) / 2, y), linea, font=fuente, fill=color, stroke_width=5, stroke_fill=(0, 0, 0))
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


async def voz(texto, archivo):
    await edge_tts.Communicate(texto, VOZ).save(archivo)


def miniatura(video, n, salida):
    """Fotograma del primer vídeo, ampliado y oscurecido, con el número de casos en grande."""
    ffmpeg("-ss", "3", "-i", video, "-frames:v", "1", f"{CARPETA}/fotograma.png")
    foto = Image.open(f"{CARPETA}/fotograma.png").convert("RGB")
    fondo = foto.resize((1280, int(1280 * foto.height / foto.width))).crop((0, 0, 1280, 720))
    fondo = fondo.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.55))
    fondo.paste(foto.resize((int(720 * foto.width / foto.height), 720)), (820, 0))
    d = ImageDraw.Draw(fondo)
    for texto, tam, color, y in [(f"{n}", 260, AMARILLO, 70), ("CASOS SIN", 110, (255, 255, 255), 340),
                                 ("RESOLVER", 110, AMARILLO, 470)]:
        d.text((60, y), texto, font=ImageFont.truetype(FUENTE, tam), fill=color, stroke_width=8,
               stroke_fill=(0, 0, 0))
    fondo.save(salida)


def telegram(texto):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      data={"chat_id": chat, "text": texto})


def tiempo(segundos):
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def main():
    videos = json.load(open(SEMANA, encoding="utf-8")) if os.path.exists(SEMANA) else []
    if len(videos) < MINIMO:
        print(f"Solo hay {len(videos)} vídeos esta semana; no se hace recopilación.")
        return
    os.makedirs(CARPETA, exist_ok=True)
    subprocess.run(["gh", "release", "download", "semana", "-D", CARPETA, "-p", "*.mp4", "--clobber"], check=True)
    videos = [v for v in videos if os.path.exists(f"{CARPETA}/{v['archivo']}")]
    n = len(videos)
    print(f"Montando la recopilación con {n} vídeos...")

    trozos, capitulos, t = [], [], 0.0

    def añadir(archivo, capitulo=None):
        nonlocal t
        if capitulo:
            capitulos.append(f"{tiempo(t)} {capitulo}")
        trozos.append(archivo)
        t += duracion(archivo)

    asyncio.run(voz(f"Estos son los {n} misterios sin resolver de esta semana. Quédate hasta el final, "
                    "porque el último es el más inquietante.", f"{CARPETA}/intro.mp3"))
    tarjeta("RECOPILACIÓN SEMANAL", f"{n} misterios sin resolver", f"{CARPETA}/intro.png")
    tarjeta_a_video(f"{CARPETA}/intro.png", duracion(f"{CARPETA}/intro.mp3") + 0.6,
                    f"{CARPETA}/00_intro.mp4", audio=f"{CARPETA}/intro.mp3")
    añadir(f"{CARPETA}/00_intro.mp4", "Introducción")

    for i, v in enumerate(videos, start=1):
        print(f"  {i}/{n}: {v['titulo']}")
        tarjeta(f"CASO {i}", v["titulo"], f"{CARPETA}/t{i}.png")
        tarjeta_a_video(f"{CARPETA}/t{i}.png", 2.5, f"{CARPETA}/{i:02d}a.mp4")
        añadir(f"{CARPETA}/{i:02d}a.mp4", f"{i}. {v['titulo']}")
        vertical_a_horizontal(f"{CARPETA}/{v['archivo']}", f"{CARPETA}/{i:02d}b.mp4")
        añadir(f"{CARPETA}/{i:02d}b.mp4")

    tarjeta("¿CUÁL TE HA DADO MÁS MIEDO?", "Cuéntamelo en los comentarios y suscríbete para no perderte "
            "los casos de la próxima semana", f"{CARPETA}/fin.png")
    tarjeta_a_video(f"{CARPETA}/fin.png", 5, f"{CARPETA}/99_fin.mp4")
    añadir(f"{CARPETA}/99_fin.mp4", "Final")

    with open(f"{CARPETA}/lista.txt", "w") as f:
        f.writelines(f"file '{os.path.basename(x)}'\n" for x in trozos)
    salida = f"{CARPETA}/recopilacion.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", f"{CARPETA}/lista.txt", "-c", "copy", "-movflags", "+faststart", salida)
    print(f"Recopilación lista: {tiempo(t)} de duración.")

    if os.environ.get("PRUEBA") == "true" or not youtube.configurado():
        print("Modo prueba o sin YouTube: no se publica.")
        return

    titulo = f"{n} misterios reales que siguen sin resolver | Recopilación semanal"
    descripcion = ("Los misterios sin resolver de esta semana, uno detrás de otro. "
                   "¿Cuál te ha dado más miedo? Cuéntamelo en los comentarios.\n\n"
                   + "\n".join(capitulos)
                   + "\n\n#misterio #casosreales #sinresolver #enigma #recopilacion")
    video_id, enlace = youtube.subir(salida, titulo, descripcion,
                                     ["Misterio", "CasosReales", "SinResolver", "Enigma", "Recopilación"],
                                     short=False)
    print(f"Publicada: {enlace}")
    try:
        miniatura(f"{CARPETA}/{videos[0]['archivo']}", n, f"{CARPETA}/miniatura.png")
        youtube.poner_miniatura(video_id, f"{CARPETA}/miniatura.png")
    except Exception as e:
        print(f"AVISO: no se pudo poner la miniatura (hace falta verificar el canal por teléfono): {e}")

    # Semana nueva: se vacía la lista y se borran los vídeos guardados
    json.dump([], open(SEMANA, "w", encoding="utf-8"))
    subprocess.run(["gh", "release", "delete", "semana", "--yes", "--cleanup-tag"], check=False)
    telegram(f"📺 Recopilación semanal publicada ({n} vídeos, {tiempo(t)}): {enlace}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        telegram(f"⚠️ La recopilación semanal ha fallado: {e}")
        raise

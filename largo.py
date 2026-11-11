"""
Vídeo largo semanal de cada canal (unos 10 minutos, horizontal 1080p), hecho desde cero:

- Gemini escribe un guion tipo documental: introducción con gancho, 6 capítulos que acaban dejando
  intriga y un cierre. El tema profundiza en una historia que ya salió en Shorts (los Shorts llevan
  público al vídeo largo y enlazan a él).
- Voz por bloques (con voces de reserva), música del canal por debajo.
- Planos de Pexels de pocos segundos con movimiento, en el orden de lo que se cuenta; título de
  cada capítulo en pantalla. Todo con ffmpeg (mucho más rápido que moviepy en 10 minutos de vídeo).
- Miniatura, capítulos en la descripción y aviso por Telegram.

    CANAL=ysi PRUEBA=true python largo.py   -> se sube como oculto para revisarlo
"""
import asyncio
import json
import math
import os
import random
import subprocess
import sys
import textwrap

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.io import wavfile
from telegram import Bot

import montaje
import sonido
import youtube
from canales import ACTUAL as CANAL, ruta
from historias_ia import _pedir

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PRUEBA = os.environ.get("PRUEBA") == "true"          # Se sube como oculto y no se apunta el tema
PROGRAMADO = os.environ.get("PROGRAMADO") == "true"

CARPETA = "largo"
ANCHO, ALTO, FPS = 1920, 1080, 30
MARGEN = 1.1                  # Los planos se amplían un 10 % para poder moverse (paneo lento)
PLANO = (3.0, 4.5)            # Segundos por plano: cortes frecuentes para que no se haga lento
GOLPE = 9                     # Fotogramas (~0,3 s) del golpe de zoom con que entra cada plano
PAUSA = 0.7                   # Silencio entre bloques
TITULO_CAPITULO = 4.0         # Segundos que se ve el título de cada capítulo
FUENTE = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
AMARILLO = (255, 222, 0)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duracion(archivo):
    salida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                             archivo], capture_output=True, text=True, check=True)
    return float(salida.stdout.strip())


def tiempo(segundos):
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------ Guion
def leer_lineas(archivo):
    return [l.strip() for l in open(archivo, encoding="utf-8")] if os.path.exists(archivo) else []


def guion():
    hechos = [l for l in leer_lineas(ruta("largos.txt")) if l]
    publicados = [l for l in leer_lineas(ruta("casos_publicados.txt")) if l][-15:]
    que, _, _, reglas = CANAL["serie"]
    if publicados:
        eleccion = ("Elige UNO de estos temas que ya salieron en Shorts y cuéntalo a fondo (el público ya lo "
                    "conoce y querrá saber más):\n" + "\n".join(f"- {p}" for p in publicados))
    else:
        eleccion = "Elige un tema muy atractivo para este canal."
    evitar = "\n".join(f"- {h}" for h in hechos) or "- (ninguno)"
    instrucciones = f"""Escribe el guion de un vídeo largo de YouTube de unos 10 minutos narrado para el canal
"{CANAL['nombre']}", cuyo tema es: {CANAL['tema']}.

{eleccion}
No repitas ninguno de estos temas, que ya tienen vídeo largo:
{evitar}

Reglas de contenido: {reglas}

Estilo (es lo que hace que la gente vea hasta el final):
- Narrado en español de España, como se habla: frases cortas, ritmo de documental de YouTube.
- Datos concretos (nombres, lugares, fechas, cifras) en vez de adjetivos vagos.
- Cada capítulo cuenta cosas nuevas y termina con una frase que deja intriga para el siguiente.
- Sin saludos, sin emojis, sin acotaciones como [música], sin "en el capítulo anterior".

Devuelve solo un objeto JSON con:
- "tema": nombre corto del tema (para no repetirlo en el futuro).
- "titulo": título de YouTube de máximo 70 caracteres que despierte curiosidad sin mentir.
- "miniatura": texto para la miniatura, de 2 a 4 palabras impactantes.
- "descripcion": 2 o 3 frases para la descripción de YouTube.
- "intro": de 90 a 120 palabras. Empieza con lo más impactante de todo el vídeo, plantea la gran pregunta y
  promete lo que se va a descubrir.
- "busquedas_intro": 4 búsquedas para la intro.
- "capitulos": lista de 6 capítulos, cada uno con "titulo" (2 a 5 palabras), "texto" (de 200 a 260 palabras)
  "busquedas" (6 búsquedas) y "destacado" (el dato clave del capítulo en 2 a 6 palabras, con una cifra o
  una frase fuerte, para mostrarlo en pantalla; por ejemplo "6 MUERTOS, 0 CULPABLES").
- "cierre": de 80 a 110 palabras: conclusión, una pregunta para que comenten y una invitación a suscribirse.
- "busquedas_cierre": 3 búsquedas para el cierre.
Las búsquedas son para vídeos de stock {CANAL['estilo_busquedas']}: en inglés, de 2 a 3 palabras, en el mismo
orden que el texto, de cosas concretas que se puedan ver (objetos, lugares, acciones), sin personas reconocibles."""
    datos = json.loads(_pedir(GEMINI_API_KEY, instrucciones, 12 * 60, 0.8, espera_maxima=300, intentos=2))
    capitulos = [c for c in datos.get("capitulos", []) if isinstance(c, dict) and len(c.get("texto", "")) > 600]
    if len(capitulos) < 4 or len(datos.get("intro", "")) < 300 or len(datos.get("cierre", "")) < 200:
        raise ValueError(f"el guion no salió bien: {len(capitulos)} capítulos válidos")
    datos["capitulos"] = capitulos
    return datos


# ------------------------------------------------------------------ Voz y música
async def locucion(bloques):
    """Voz de cada bloque, unida en un WAV con pausas. Devuelve (inicio de cada bloque, duración total, palabras)."""
    piezas, inicios, palabras, t = [], [], [], 0.0
    silencio = np.zeros((int(PAUSA * sonido.FS), 2), dtype=np.int16)
    for i, (titulo, texto, _) in enumerate(bloques):
        mp3, wav = f"{CARPETA}/voz_{i}.mp3", f"{CARPETA}/voz_{i}.wav"
        sueltas = await asyncio.wait_for(montaje.generar_voz(texto, mp3), timeout=600)
        ffmpeg("-i", mp3, "-ar", str(sonido.FS), "-ac", "2", "-sample_fmt", "s16", wav)
        _, audio = wavfile.read(wav)
        inicios.append(t)
        palabras += [(a + t, b + t, w) for a, b, w in sueltas]
        piezas += [audio, silencio]
        t += (len(audio) + len(silencio)) / sonido.FS
        print(f"  voz {i + 1}/{len(bloques)} ({titulo}): {len(audio) / sonido.FS:.0f} s")
    voz = np.concatenate(piezas)
    return voz, inicios, len(voz) / sonido.FS, palabras


def mezclar(voz, total, palabras, cortes, inicios):
    musica = sonido.banda_sonora(total, palabras, cortes, inicios[1] if len(inicios) > 1 else 3.0,
                                 inicios[-1], CANAL["musica"])
    n = min(len(voz), len(musica))
    # Algo más baja que en los Shorts: 10 minutos de música alta cansan
    mezcla = voz[:n].astype(np.float32) / 32768 + 0.7 * musica[:n]
    salida = f"{CARPETA}/audio.wav"
    wavfile.write(salida, sonido.FS, (np.clip(mezcla, -1, 1) * 32767).astype(np.int16))
    return salida


# ------------------------------------------------------------------ Imagen
_cache = {}


def buscar(termino):
    """Vídeos horizontales de Pexels para una búsqueda (con caché; si falla, lista vacía)."""
    if termino not in _cache:
        try:
            r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                             headers={"Authorization": PEXELS_API_KEY},
                             params={"query": termino, "orientation": "landscape", "per_page": 5})
            r.raise_for_status()
            _cache[termino] = r.json().get("videos", [])
        except Exception as e:
            print(f"  Aviso: Pexels falló con '{termino}': {e}")
            _cache[termino] = []
    return _cache[termino]


def archivo_de(video):
    archivos = [f for f in video.get("video_files", []) if f.get("link") and f.get("width") and f.get("height")]
    buenos = [f for f in archivos if f["width"] > f["height"] and 1280 <= f["width"] <= 1920]
    return max(buenos or archivos, key=lambda f: f["width"])["link"] if (buenos or archivos) else None


def descargar(video):
    destino = f"{CARPETA}/clips/{video['id']}.mp4"
    if not os.path.exists(destino):
        with requests.get(archivo_de(video), stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
    return destino


def texto_a_archivo(texto, nombre):
    """drawtext lee el texto de un archivo: así no hay que escapar comillas ni dos puntos."""
    ruta_txt = os.path.abspath(f"{CARPETA}/{nombre}.txt")
    with open(ruta_txt, "w", encoding="utf-8") as f:
        f.write(texto)
    return ruta_txt


def tramo(clip, d, salida, n, capitulo=None, destacado=None):
    """Un plano: entra con un golpe de zoom y se mueve en paneo lento, con el etalonaje del canal; si
    empieza capítulo, su título; si toca, un dato clave que sube desde abajo."""
    w2, h2 = int(ANCHO * MARGEN), int(ALTO * MARGEN)
    fotogramas = max(1, round(d * FPS))
    avance = f"in/{fotogramas}" if n % 2 else f"(1-in/{fotogramas})"
    zoom = f"{MARGEN}+0.12*max(0,1-in/{GOLPE})"
    filtros = [f"scale={w2}:{h2}:force_original_aspect_ratio=increase", f"crop={w2}:{h2}", f"fps={FPS}",
               f"zoompan=z='{zoom}':x='(iw-iw/zoom)*{avance}':y='(ih-ih/zoom)/2':d=1:"
               f"s={ANCHO}x{ALTO}:fps={FPS}", "setsar=1"]
    filtros.append("eq=brightness=-0.05:saturation=0.85,vignette=angle=PI/5" if CANAL["oscuro"]
                   else "eq=saturation=1.1:contrast=1.04")
    if capitulo:
        etiqueta, titulo = capitulo
        color = "0x%02X%02X%02X" % tuple(CANAL["color_etiqueta"])
        aparece = (f"alpha='if(lt(t,0.4),t/0.4,if(lt(t,{TITULO_CAPITULO - 0.5}),1,"
                   f"max(0,({TITULO_CAPITULO}-t)/0.5)))'")
        filtros.append(f"drawtext=fontfile={FUENTE}:textfile={texto_a_archivo(etiqueta, f'e{n}')}:fontsize=44:"
                       f"fontcolor=white:box=1:boxcolor={color}@0.9:boxborderw=18:x=(w-text_w)/2:y=h/2-130:"
                       f"enable='lt(t,{TITULO_CAPITULO})':{aparece}")
        filtros.append(f"drawtext=fontfile={FUENTE}:textfile={texto_a_archivo(titulo.upper(), f't{n}')}:"
                       f"fontsize=96:fontcolor=white:borderw=7:bordercolor=black:x=(w-text_w)/2:y=h/2-30:"
                       f"enable='lt(t,{TITULO_CAPITULO})':{aparece}")
    if destacado:
        # Dato clave abajo: sube y se desvanece, en amarillo sobre fondo oscuro
        sube = "h-260+max(0,0.35-t)*500"
        filtros.append(f"drawtext=fontfile={FUENTE}:textfile={texto_a_archivo(destacado.upper(), f'd{n}')}:"
                       f"fontsize=70:fontcolor=0xFFDE00:box=1:boxcolor=black@0.7:boxborderw=26:"
                       f"x=(w-text_w)/2:y='{sube}':alpha='min(1,t/0.3,max(0,({d:.3f}-t)/0.4))'")
    inicio = random.uniform(0, max(0.0, duracion(clip) - d - 0.2))
    ffmpeg("-stream_loop", "-1", "-ss", f"{inicio:.2f}", "-i", clip, "-t", f"{d:.3f}", "-vf", ",".join(filtros),
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", salida)


def montar_imagen(bloques, inicios, total, destacados=None):
    """Divide cada bloque en planos cortos, cada uno con la búsqueda que toca en ese momento."""
    os.makedirs(f"{CARPETA}/clips", exist_ok=True)
    usados, sobrantes, tramos, cortes = set(), [], [], []
    limites = inicios[1:] + [total]
    n = 0
    for b, (titulo, _, busquedas) in enumerate(bloques):
        largo = limites[b] - inicios[b]
        planos = max(1, round(largo / random.uniform(*PLANO)))
        busquedas = [s for s in busquedas if isinstance(s, str) and s.strip()] or CANAL["busquedas_genericas"]
        for j in range(planos):
            d = largo / planos
            termino = busquedas[min(len(busquedas) - 1, j * len(busquedas) // planos)]
            candidatos = [v for v in buscar(termino) if v["id"] not in usados]
            sobrantes += candidatos[1:]
            opciones = candidatos[:1] + [v for v in sobrantes if v["id"] not in usados]
            if not opciones:
                opciones = [v for v in buscar(random.choice(CANAL["busquedas_genericas"])) if v["id"] not in usados]
            capitulo = None
            if j == 0 and 0 < b < len(bloques) - 1:
                capitulo = (f"CAPÍTULO {b}", titulo)
            salida = f"{CARPETA}/tramo_{n:03d}.mp4"
            for video in opciones[:4]:
                try:
                    dato = (destacados or {}).get(b) if planos >= 3 and j == planos // 2 else None
                    tramo(descargar(video), d, salida, n, capitulo, dato)
                    usados.add(video["id"])
                    break
                except Exception as e:
                    print(f"  Aviso: se descarta un clip: {e}")
            else:
                # Sin clip válido: un fondo del color del canal para no dejar un hueco
                ffmpeg("-f", "lavfi", "-i", f"color=c=black:s={ANCHO}x{ALTO}:r={FPS}:d={d:.3f}",
                       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", salida)
            tramos.append(salida)
            cortes.append(inicios[b] + j * d)
            n += 1
        print(f"  imagen {b + 1}/{len(bloques)} ({titulo}): {planos} planos")
    with open(f"{CARPETA}/tramos.txt", "w") as f:
        f.writelines(f"file '{os.path.basename(t)}'\n" for t in tramos)
    ffmpeg("-f", "concat", "-safe", "0", "-i", f"{CARPETA}/tramos.txt", "-c", "copy", f"{CARPETA}/imagen.mp4")
    return f"{CARPETA}/imagen.mp4", cortes[1:]


# ------------------------------------------------------------------ Miniatura
def miniatura(video, texto, salida):
    ffmpeg("-ss", "20", "-i", video, "-frames:v", "1", f"{CARPETA}/fotograma.png")
    img = Image.open(f"{CARPETA}/fotograma.png").convert("RGB").resize((1280, 720))
    img = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.35).convert("RGBA")
    # Degradado oscuro a la izquierda para que el texto se lea
    sombra = Image.new("L", img.size)
    ImageDraw.Draw(sombra).rectangle([0, 0, 760, 720], fill=170)
    img.paste((0, 0, 0), mask=sombra.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)
    etiqueta = ImageFont.truetype(FUENTE, 40)
    ancho = d.textlength(CANAL["etiqueta"], font=etiqueta)
    d.rectangle([40, 40, 80 + ancho, 104], fill=tuple(CANAL["color_etiqueta"]))
    d.text((60, 48), CANAL["etiqueta"], font=etiqueta, fill=(255, 255, 255))
    lineas = textwrap.wrap(texto.upper(), width=11)[:3]
    tam = 150 if len(lineas) <= 2 else 120
    y = 720 - 60 - len(lineas) * int(tam * 1.05)
    for k, linea in enumerate(lineas):
        d.text((50, y), linea, font=ImageFont.truetype(FUENTE, tam), fill=AMARILLO if k == 0 else (255, 255, 255),
               stroke_width=10, stroke_fill=(0, 0, 0))
        y += int(tam * 1.05)
    img.convert("RGB").save(salida)


# ------------------------------------------------------------------ Principal
async def main():
    if PROGRAMADO and not youtube.configurado():
        print(f"{CANAL['nombre']} aún no está conectado a YouTube: no se hace nada.")
        return
    os.makedirs(CARPETA, exist_ok=True)
    print(f"Canal: {CANAL['nombre']}. [1/6] Escribiendo el guion...")
    datos = guion()
    print(f"Tema: {datos.get('tema')} | Título: {datos.get('titulo')}")
    bloques = ([("Introducción", datos["intro"], datos.get("busquedas_intro"))]
               + [(c.get("titulo", f"Capítulo {k}"), c["texto"], c.get("busquedas"))
                  for k, c in enumerate(datos["capitulos"], start=1)]
               + [("Conclusión", datos["cierre"], datos.get("busquedas_cierre"))])

    print("[2/6] Voz...")
    voz, inicios, total, palabras = await locucion(bloques)
    print(f"Duración: {tiempo(total)}")
    print("[3/6] Imagen (Pexels + ffmpeg)...")
    destacados = {k: str(c["destacado"])[:40] for k, c in enumerate(datos["capitulos"], start=1)
                  if isinstance(c.get("destacado"), str) and c["destacado"].strip()}
    imagen, cortes = montar_imagen(bloques, inicios, total, destacados)
    print("[4/6] Música y mezcla...")
    audio = mezclar(voz, total, palabras, cortes, inicios)
    final = f"{CARPETA}/final.mp4"
    ffmpeg("-i", imagen, "-i", audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", final)
    print(f"Vídeo listo: {tiempo(duracion(final))}, {os.path.getsize(final) / 1e6:.0f} MB.")
    portada = f"{CARPETA}/miniatura.png"
    miniatura(final, datos.get("miniatura") or datos["titulo"], portada)

    print("[5/6] Subiendo a YouTube...")
    capitulos = "\n".join(f"{tiempo(t)} {titulo}" for t, (titulo, _, _) in zip(inicios, bloques))
    hashtags = " ".join(h for h in CANAL["hashtags_youtube"].split() if h != "#shorts")
    descripcion = ((f"{CANAL['aviso']}\n\n" if CANAL.get("aviso") else "") + f"{datos.get('descripcion', '')}\n\n"
                   f"Capítulos:\n{capitulos}\n\n{hashtags}")
    titulo = datos["titulo"][:100]
    enlace = None
    if youtube.configurado():
        video_id, enlace = youtube.subir(final, titulo, descripcion, [e for e in CANAL["etiquetas"] if e != "Shorts"],
                                         short=False, categoria=CANAL["categoria"],
                                         privacidad="unlisted" if PRUEBA else "public")
        print(f"Subido ({'oculto' if PRUEBA else 'público'}): {enlace}")
        try:
            youtube.poner_miniatura(video_id, portada)
        except Exception as e:
            print(f"AVISO: no se pudo poner la miniatura (hace falta verificar el canal por teléfono): {e}")
    else:
        print("El canal no está conectado a YouTube: el vídeo queda como artefacto de la ejecución.")

    print("[6/6] Avisando por Telegram y guardando...")
    if not PRUEBA:
        with open(ruta("largos.txt"), "a", encoding="utf-8") as f:
            f.write(str(datos.get("tema") or titulo)[:100] + "\n")
        if enlace:
            with open(ruta("ultimo_largo.txt"), "w", encoding="utf-8") as f:
                f.write(enlace + "\n")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        estado = (f"🧪 Prueba subida como OCULTA, revísala: {enlace}" if PRUEBA and enlace
                  else f"▶️ Publicado: {enlace}" if enlace
                  else "📦 No está conectado a YouTube: descárgalo de los artefactos de la ejecución en GitHub.")
        texto = f"📺 {CANAL['nombre']}: vídeo largo ({tiempo(total)})\n{titulo}\n{estado}"
        async with Bot(token=TELEGRAM_TOKEN) as bot:
            with open(portada, "rb") as f:
                await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=f, caption=texto[:1000])
    print("Listo.")


if __name__ == "__main__":
    asyncio.run(main())

"""
Montaje del vídeo vertical: voz con tiempos por palabra, planos cortos con movimiento,
etalonaje oscuro, subtítulos palabra a palabra, cabecera, barra de progreso y cierre.
"""
import json
import random
import textwrap
import time

import numpy as np
import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, VideoFileClip, AudioFileClip, ImageClip,
                            CompositeVideoClip, concatenate_videoclips)
from moviepy.video.fx.all import loop

ANCHO, ALTO = 1080, 1920
FPS = 30
VOZ = "es-ES-AlvaroNeural"
VELOCIDAD = "+6%"          # Un pelín más rápido: en Shorts el ritmo retiene
DURACION_PLANO = (2.8, 4.2)  # Cortes frecuentes para que no se haga monótono
CIERRE = 2.0                 # Segundos de "sígueme" al final, ya sin voz
AMARILLO = (255, 222, 0)
ROJO = (220, 30, 45)

# Si Gemini no está disponible, se combinan búsquedas genéricas de ambiente
BUSQUEDAS_GENERICAS = [
    "dark forest fog", "abandoned house", "night sky stars", "old documents",
    "foggy road night", "candle dark", "dark corridor", "storm clouds", "old photographs",
]


async def generar_voz(texto, archivo):
    """Genera la locución y devuelve [(inicio, fin, palabra)] en segundos."""
    try:
        comunicar = edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD, boundary="WordBoundary")
    except TypeError:  # Versiones antiguas de edge-tts ya dan WordBoundary por defecto
        comunicar = edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD)
    palabras = []
    with open(archivo, "wb") as f:
        async for trozo in comunicar.stream():
            if trozo["type"] == "audio":
                f.write(trozo["data"])
            elif trozo["type"] == "WordBoundary":
                inicio = trozo["offset"] / 1e7
                palabras.append((inicio, inicio + trozo["duration"] / 1e7, trozo["text"]))
    return palabras


def tiempos_aproximados(texto, duracion):
    """Plan B si la voz no trae tiempos: reparte las palabras según su longitud."""
    palabras = texto.split()
    total = sum(len(p) + 1 for p in palabras)
    t, salida = 0.0, []
    for p in palabras:
        d = duracion * (len(p) + 1) / total
        salida.append((t, t + d, p))
        t += d
    return salida


def busquedas_para(historia, api_key):
    """Pide a Gemini 5 búsquedas en inglés para Pexels que encajen con la historia."""
    if not api_key:
        return random.sample(BUSQUEDAS_GENERICAS, 5)
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": api_key}, timeout=60,
            json={
                "contents": [{"parts": [{"text": (
                    "Dame 5 búsquedas cortas en inglés (2-3 palabras) para encontrar vídeos de stock "
                    "atmosféricos, sin personas reconocibles, que ilustren esta historia de misterio. "
                    "Devuelve solo un array JSON de strings.\n\n" + historia)}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        terminos = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        terminos = [t for t in terminos if isinstance(t, str) and t.strip()][:5]
        if terminos:
            return terminos + random.sample(BUSQUEDAS_GENERICAS, 2)
    except Exception as e:
        print(f"Aviso: Gemini no dio búsquedas, uso las genéricas: {e}")
    return random.sample(BUSQUEDAS_GENERICAS, 5)


def _descargar(url, destino):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for trozo in r.iter_content(1024 * 1024):
                f.write(trozo)


def plano_con_movimiento(clip, duracion):
    """Recorta un trozo del clip y le da un paneo lento (efecto Ken Burns barato)."""
    if clip.duration > duracion:
        inicio = random.uniform(0, clip.duration - duracion)
        clip = clip.subclip(inicio, inicio + duracion)
    else:
        duracion = clip.duration
    escala = 1.12
    clip = clip.resize(height=int(ALTO * escala))
    if clip.w < ANCHO * escala:
        clip = clip.resize(width=int(ANCHO * escala))
    margen_x, margen_y = clip.w - ANCHO, clip.h - ALTO
    x0, x1 = random.choice([(0, margen_x), (margen_x, 0), (margen_x // 2, margen_x // 2)])
    y0, y1 = random.choice([(0, margen_y), (margen_y, 0)])

    def recortar(get_frame, t):
        p = min(t / duracion, 1)
        x, y = int(x0 + (x1 - x0) * p), int(y0 + (y1 - y0) * p)
        return get_frame(t)[y:y + ALTO, x:x + ANCHO]

    plano = clip.fl(recortar, apply_to=[]).set_duration(duracion)
    plano.size = (ANCHO, ALTO)
    return plano


def descargar_planos(pexels_key, busquedas, duracion_total):
    """Descarga clips verticales de varias búsquedas y los trocea en planos cortos."""
    candidatos, vistos = [], set()
    for termino in busquedas:
        try:
            r = requests.get("https://api.pexels.com/videos/search", timeout=30,
                             headers={"Authorization": pexels_key},
                             params={"query": termino, "orientation": "portrait", "per_page": 8})
            r.raise_for_status()
        except Exception as e:
            print(f"Aviso: Pexels falló con '{termino}': {e}")
            continue
        for v in r.json().get("videos", []):
            if v["id"] not in vistos:
                vistos.add(v["id"])
                candidatos.append(v)
    if not candidatos:
        raise RuntimeError("Pexels no devolvió vídeos.")
    random.shuffle(candidatos)

    planos, acumulado = [], 0.0
    for i, vid in enumerate(candidatos):
        if acumulado >= duracion_total:
            break
        archivos = [f for f in vid.get("video_files", []) if f.get("link") and f.get("height")]
        # Verticales de 1280 a 1920 px de alto: buena calidad sin el coste del 4K
        verticales = [f for f in archivos if f["height"] > (f.get("width") or 0) and 1280 <= f["height"] <= 1920]
        opciones = verticales or [f for f in archivos if f["height"] <= 1920] or archivos
        if not opciones:
            continue
        nombre = f"clip_{i}.mp4"
        try:
            _descargar(max(opciones, key=lambda f: f["height"])["link"], nombre)
            plano = plano_con_movimiento(VideoFileClip(nombre).without_audio(), random.uniform(*DURACION_PLANO))
        except Exception as e:
            print(f"Aviso: se descarta un clip por error: {e}")
            continue
        planos.append(plano)
        acumulado += plano.duration
        print(f"  plano {len(planos)}: {plano.duration:.1f} s ({acumulado:.0f}/{duracion_total:.0f} s)")
    if not planos:
        raise RuntimeError("no se pudo preparar ningún plano.")
    return planos


def _viñeta():
    """Máscara que oscurece los bordes y el conjunto para un tono de documental de misterio."""
    y, x = np.ogrid[-1:1:ALTO * 1j, -1:1:ANCHO * 1j]
    distancia = np.sqrt((x * 0.9) ** 2 + (y * 0.7) ** 2)
    mascara = np.clip(1.05 - 0.55 * distancia ** 2, 0.35, 1.0) * 0.82
    return mascara[..., None].astype(np.float32)


def etalonar(clip):
    mascara = _viñeta()
    tinte = np.array([0.92, 0.97, 1.10], dtype=np.float32)  # Frío, ligeramente azulado

    def aplicar(frame):
        return np.clip(frame.astype(np.float32) * mascara * tinte, 0, 255).astype(np.uint8)

    return clip.fl_image(aplicar)


def _imagen_texto(lineas, fuente, borde=8, interlineado=1.15):
    """Dibuja varias líneas centradas; cada línea es una lista de (texto, color)."""
    alto_linea = int(fuente.size * interlineado)
    img = Image.new("RGBA", (ANCHO, alto_linea * len(lineas) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 20
    for linea in lineas:
        ancho = sum(d.textlength(t + " ", font=fuente) for t, _ in linea) - d.textlength(" ", font=fuente)
        x = (ANCHO - ancho) / 2
        for t, color in linea:
            d.text((x, y), t, font=fuente, fill=color, stroke_width=borde, stroke_fill=(0, 0, 0))
            x += d.textlength(t + " ", font=fuente)
        y += alto_linea
    return np.array(img)


def subtitulos_palabra_a_palabra(palabras, ruta_fuente, palabras_por_grupo=3):
    """Grupos de hasta 3 palabras en mayúsculas; la que se está diciendo, en amarillo."""
    fuente = ImageFont.truetype(ruta_fuente, 96)
    grupos, actual = [], []
    for i, p in enumerate(palabras):
        # Corta el grupo si está lleno o si hay una pausa clara en la voz
        if actual and (len(actual) == palabras_por_grupo or p[0] - actual[-1][1] > 0.35):
            grupos.append(actual)
            actual = []
        actual.append(p)
    if actual:
        grupos.append(actual)

    clips = []
    for g, grupo in enumerate(grupos):
        fin_grupo = grupos[g + 1][0][0] if g + 1 < len(grupos) else grupo[-1][1] + 0.3
        textos = [p[2].upper() for p in grupo]
        for i, (inicio, _, _) in enumerate(grupo):
            fin = grupo[i + 1][0] if i + 1 < len(grupo) else fin_grupo
            coloreadas = [(t, AMARILLO if j == i else (255, 255, 255)) for j, t in enumerate(textos)]
            # Si no cabe en una línea, parte en dos
            lineas = [coloreadas]
            if len(" ".join(textos)) > 16 and len(textos) > 1:
                corte = (len(textos) + 1) // 2
                lineas = [coloreadas[:corte], coloreadas[corte:]]
            imagen = _imagen_texto(lineas, fuente)
            clips.append(ImageClip(imagen).set_start(inicio).set_duration(max(fin - inicio, 0.05))
                         .set_position(("center", int(ALTO * 0.60))))
    return clips


def cabecera(n_episodio, ruta_fuente, duracion):
    """Etiqueta fija arriba: 'CASO SIN RESOLVER · Nº X' en una franja roja."""
    fuente = ImageFont.truetype(ruta_fuente, 52)
    texto = f"CASO SIN RESOLVER · Nº {n_episodio}"
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    ancho = int(d.textlength(texto, font=fuente)) + 60
    img = Image.new("RGBA", (ancho, 90), ROJO + (235,))
    ImageDraw.Draw(img).text((30, 14), texto, font=fuente, fill=(255, 255, 255))
    return ImageClip(np.array(img)).set_duration(duracion).set_position(("center", 170))


def gancho(texto, ruta_fuente):
    """Primera frase en grande durante los primeros segundos: lo que engancha al deslizar."""
    primera = texto.split(". ")[0].strip().rstrip(".")
    if len(primera) > 90:
        primera = primera[:87].rsplit(" ", 1)[0] + "…"
    fuente = ImageFont.truetype(ruta_fuente, 64)
    lineas = [[(l, (255, 255, 255))] for l in textwrap.wrap(primera.upper(), width=24)]
    return (ImageClip(_imagen_texto(lineas, fuente, borde=6)).set_start(0).set_duration(2.6)
            .set_position(("center", 300)).crossfadeout(0.4))


def barra_progreso(duracion):
    """Barra fina amarilla abajo que avanza: anima a ver el vídeo hasta el final."""
    alto = 12

    def fotograma(t):
        f = np.zeros((alto, ANCHO, 3), dtype=np.uint8)
        f[:, :int(ANCHO * min(t / duracion, 1))] = AMARILLO
        return f

    return VideoClip(fotograma, duration=duracion).set_position((0, ALTO - alto))


def cierre(ruta_fuente, inicio):
    fuente = ImageFont.truetype(ruta_fuente, 86)
    lineas = [[("SÍGUEME", AMARILLO)], [("PARA EL PRÓXIMO", (255, 255, 255))], [("CASO", (255, 255, 255))]]
    return (ImageClip(_imagen_texto(lineas, fuente)).set_start(inicio).set_duration(CIERRE)
            .set_position(("center", "center")).crossfadein(0.3))


def montar(historia, n_episodio, archivo_voz, palabras, planos, ruta_fuente, salida):
    voz = AudioFileClip(archivo_voz)
    if not palabras:
        palabras = tiempos_aproximados(historia, voz.duration)
    duracion = voz.duration + CIERRE

    fondo = concatenate_videoclips(planos, method="compose")
    fondo = fondo.subclip(0, min(duracion, fondo.duration))
    if fondo.duration < duracion:
        fondo = loop(fondo, duration=duracion)
    fondo = etalonar(fondo).set_audio(voz)

    capas = ([fondo, cabecera(n_episodio, ruta_fuente, duracion), gancho(historia, ruta_fuente)]
             + subtitulos_palabra_a_palabra(palabras, ruta_fuente)
             + [cierre(ruta_fuente, voz.duration), barra_progreso(duracion)])
    video = CompositeVideoClip(capas, size=(ANCHO, ALTO)).set_duration(duracion)
    print(f"  {len(capas)} capas, {duracion:.1f} s; renderizando...")
    t0 = time.time()
    video.write_videofile(
        salida, fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="160k",
        preset="faster", threads=2, logger="bar",
        # Calidad constante alta, con tope para no pasar de los 50 MB de Telegram
        ffmpeg_params=["-crf", "20", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p"],
    )
    print(f"  render: {time.time() - t0:.0f} s")

"""
Montaje del vídeo vertical: voz con tiempos por palabra, planos cortos con movimiento,
etalonaje oscuro, subtítulos palabra a palabra, cabecera, barra de progreso y cierre.
"""
import json
import os
import random
import textwrap
import time

import numpy as np
import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoClip, VideoFileClip, AudioFileClip, ImageClip,
                            CompositeVideoClip, CompositeAudioClip, concatenate_videoclips)
from moviepy.audio.AudioClip import AudioArrayClip

import sonido
from moviepy.video.fx.all import loop

ANCHO, ALTO = 1080, 1920
FPS = 30
VOZ = os.environ.get("VOZ") or "es-ES-AlvaroNeural"
VELOCIDAD = "+6%"          # Un pelín más rápido: en Shorts el ritmo retiene
DURACION_PLANO = (2.8, 4.2)  # Cortes frecuentes para que no se haga monótono
CIERRE = 2.6                 # Segundos de cierre al final, ya sin voz
GOLPE = 0.25                 # Duración del golpe de zoom al empezar cada plano
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


GANCHOS_GENERICOS = [
    "Este caso sigue sin resolverse.",
    "Nadie ha conseguido explicar lo que pasó.",
    "Lo que ocurrió aquí sigue siendo un misterio.",
    "Este misterio aún no tiene respuesta.",
]


def planificar(historia, api_key):
    """Pide a Gemini un gancho hablado, búsquedas para Pexels y hashtags del caso.
    Si falla, devuelve un plan genérico para que el vídeo salga igual."""
    plan = {"gancho": random.choice(GANCHOS_GENERICOS),
            "busquedas": random.sample(BUSQUEDAS_GENERICAS, 5), "hashtags": []}
    if not api_key:
        return plan
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
            headers={"x-goog-api-key": api_key}, timeout=60,
            json={
                "contents": [{"parts": [{"text": (
                    "Para un vídeo corto sobre esta historia de misterio real, devuelve un objeto JSON con:\n"
                    '- "gancho": una frase en español de 6 a 10 palabras que se dirá ANTES de la historia para '
                    "que nadie deslice el vídeo (intrigante, sin destripar el final, sin clickbait falso).\n"
                    '- "busquedas": 5 búsquedas cortas en inglés (2-3 palabras) para vídeos de stock atmosféricos '
                    "sin personas reconocibles que ilustren la historia.\n"
                    '- "hashtags": 3 hashtags en español o con el nombre del caso, sin espacios, con #, '
                    "específicos de esta historia (lugar, nombre del caso, tema).\n\n" + historia)}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        datos = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(datos.get("gancho"), str) and 3 <= len(datos["gancho"].split()) <= 14:
            plan["gancho"] = datos["gancho"].strip()
        busquedas = [b for b in datos.get("busquedas", []) if isinstance(b, str) and b.strip()][:5]
        if busquedas:
            plan["busquedas"] = busquedas + random.sample(BUSQUEDAS_GENERICAS, 2)
        # Solo letras y números: un "_" rompería el formato del mensaje de Telegram
        limpios = ["".join(c for c in h if c.isalnum()) for h in datos.get("hashtags", []) if isinstance(h, str)]
        plan["hashtags"] = ["#" + h for h in limpios if h][:3]
    except Exception as e:
        print(f"Aviso: Gemini no dio el plan del vídeo, uso uno genérico: {e}")
    return plan


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
        cuadro = get_frame(t)[y:y + ALTO, x:x + ANCHO]
        if t < GOLPE:
            # Golpe de zoom al entrar el plano: empieza un 8 % más cerca y se abre rápido
            z = 1 + 0.08 * (1 - t / GOLPE) ** 2
            w, h = int(ANCHO / z), int(ALTO / z)
            ox, oy = (ANCHO - w) // 2, (ALTO - h) // 2
            cuadro = np.array(Image.fromarray(cuadro[oy:oy + h, ox:ox + w]).resize((ANCHO, ALTO), Image.BILINEAR))
        return cuadro

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


PALABRAS_CLAVE = {"NADIE", "NUNCA", "JAMÁS", "MUERTE", "MUERTOS", "MURIERON", "ASESINADOS", "ASESINATO",
                  "DESAPARECIÓ", "DESAPARECIERON", "DESAPARICIÓN", "SANGRE", "CADÁVER", "CUERPOS", "MISTERIO",
                  "INEXPLICABLE", "SECRETO", "EXTRAÑO", "TERROR", "SEÑAL", "NINGUNA", "NINGÚN"}
ROJO_TEXTO = (255, 70, 70)


def _color_palabra(texto, activa):
    if activa:
        return AMARILLO
    limpia = texto.strip("¿?¡!.,;:«»\"'")
    if any(c.isdigit() for c in limpia) or limpia in PALABRAS_CLAVE:
        return ROJO_TEXTO  # Fechas, cifras y palabras fuertes destacan aunque no se estén diciendo
    return (255, 255, 255)


def _rebote(t):
    """Escala del texto al aparecer: crece un poco de más y se asienta (0,15 s)."""
    if t >= 0.15:
        return 1.0
    return 0.75 + 0.35 * (t / 0.15) - 0.1 * (t / 0.15) ** 2


def subtitulos_palabra_a_palabra(palabras, ruta_fuente, palabras_por_grupo=3):
    """Grupos de hasta 3 palabras en mayúsculas; la que se está diciendo, en amarillo."""
    fuente = ImageFont.truetype(ruta_fuente, 100)
    y_base = int(ALTO * 0.60)
    grupos, actual = [], []
    for p in palabras:
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
            coloreadas = [(t, _color_palabra(t, j == i)) for j, t in enumerate(textos)]
            # Si no cabe en una línea, parte en dos
            lineas = [coloreadas]
            if len(" ".join(textos)) > 16 and len(textos) > 1:
                corte = (len(textos) + 1) // 2
                lineas = [coloreadas[:corte], coloreadas[corte:]]
            imagen = _imagen_texto(lineas, fuente)
            clip = ImageClip(imagen).set_start(inicio).set_duration(max(fin - inicio, 0.05))
            if i == 0:
                # El grupo entra con un rebote, centrado sobre su posición final
                alto = imagen.shape[0]
                clip = (clip.resize(_rebote)
                        .set_position(lambda t, a=alto: ("center", y_base + a * (1 - _rebote(t)) / 2)))
            else:
                clip = clip.set_position(("center", y_base))
            clips.append(clip)
    return clips


def destellos(cortes):
    """Destello blanco muy breve en cada cambio de plano."""
    blanco = np.full((ALTO, ANCHO, 3), 255, dtype=np.uint8)
    return [ImageClip(blanco).set_start(c).set_duration(0.07).set_opacity(0.28) for c in cortes]


def cabecera(n_episodio, ruta_fuente, duracion):
    """Etiqueta fija arriba: 'CASO SIN RESOLVER · Nº X' en una franja roja."""
    fuente = ImageFont.truetype(ruta_fuente, 52)
    texto = f"CASO SIN RESOLVER · Nº {n_episodio}"
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    ancho = int(d.textlength(texto, font=fuente)) + 60
    img = Image.new("RGBA", (ancho, 90), ROJO + (235,))
    ImageDraw.Draw(img).text((30, 14), texto, font=fuente, fill=(255, 255, 255))
    return ImageClip(np.array(img)).set_duration(duracion).set_position(("center", 170))


def gancho(texto, ruta_fuente, duracion):
    """Frase gancho en grande arriba mientras se dice: lo que engancha al deslizar."""
    fuente = ImageFont.truetype(ruta_fuente, 74)
    lineas = [[(l, AMARILLO if n == 0 else (255, 255, 255))]
              for n, l in enumerate(textwrap.wrap(texto.upper().rstrip("."), width=20))]
    imagen = _imagen_texto(lineas, fuente, borde=7)
    alto = imagen.shape[0]
    return (ImageClip(imagen).set_start(0).set_duration(duracion)
            .resize(_rebote).set_position(lambda t: ("center", 300 + alto * (1 - _rebote(t)) / 2))
            .crossfadeout(0.3))


def barra_progreso(duracion):
    """Barra fina amarilla abajo que avanza: anima a ver el vídeo hasta el final."""
    alto = 12

    def fotograma(t):
        f = np.zeros((alto, ANCHO, 3), dtype=np.uint8)
        f[:, :int(ANCHO * min(t / duracion, 1))] = AMARILLO
        return f

    return VideoClip(fotograma, duration=duracion).set_position((0, ALTO - alto))


def cierre(ruta_fuente, inicio):
    fuente = ImageFont.truetype(ruta_fuente, 80)
    lineas = [[("¿TÚ QUÉ CREES?", AMARILLO)], [("COMENTA TU TEORÍA", (255, 255, 255))],
              [("Y SÍGUEME PARA MÁS", (255, 255, 255))]]
    return (ImageClip(_imagen_texto(lineas, fuente)).set_start(inicio).set_duration(CIERRE)
            .set_position(("center", "center")).crossfadein(0.3))


def montar(historia, gancho_texto, n_episodio, archivo_voz, palabras, planos, ruta_fuente, salida):
    voz = AudioFileClip(archivo_voz)
    if not palabras:
        palabras = tiempos_aproximados(f"{gancho_texto} {historia}", voz.duration)
    duracion = voz.duration + CIERRE
    # El gancho son las primeras palabras de la locución: dura hasta que acaba la última de ellas
    n_gancho = len(gancho_texto.split())
    fin_gancho = palabras[min(n_gancho, len(palabras)) - 1][1] + 0.2 if palabras else 2.6

    fondo = concatenate_videoclips(planos, method="compose")
    fondo = fondo.subclip(0, min(duracion, fondo.duration))
    if fondo.duration < duracion:
        fondo = loop(fondo, duration=duracion)
    cortes, t = [], 0.0
    for plano in planos[:-1]:
        t += plano.duration
        if t < duracion - 0.3:
            cortes.append(t)

    musica = AudioArrayClip(sonido.banda_sonora(duracion, palabras, cortes, fin_gancho, voz.duration),
                            fps=sonido.FS)
    fondo = etalonar(fondo).set_audio(CompositeAudioClip([musica, voz]).set_duration(duracion))

    capas = ([fondo] + destellos(cortes)
             + [cabecera(n_episodio, ruta_fuente, duracion), gancho(gancho_texto, ruta_fuente, fin_gancho)]
             + subtitulos_palabra_a_palabra(palabras[n_gancho:], ruta_fuente)
             + [cierre(ruta_fuente, voz.duration), barra_progreso(duracion)])
    video = CompositeVideoClip(capas, size=(ANCHO, ALTO)).set_duration(duracion)
    print(f"  {len(capas)} capas, {duracion:.1f} s; renderizando...")
    t0 = time.time()
    video.write_videofile(
        salida, fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="160k",
        preset="faster", threads=2, logger=None,
        # Calidad constante alta, con tope para no pasar de los 50 MB de Telegram
        ffmpeg_params=["-crf", "20", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p"],
    )
    print(f"  render: {time.time() - t0:.0f} s")

import os
import sys
import random
import asyncio
import textwrap

import requests
import numpy as np
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from telegram import Bot
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moviepy.editor import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
from moviepy.video.fx.all import crop, loop

# ---------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# YouTube es opcional: si faltan estos secrets, el vídeo solo se envía por Telegram
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")
# TikTok también es opcional
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET")
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_REFRESH_TOKEN")
# Hasta que TikTok audite la app solo se permite SELF_ONLY; después, PUBLIC_TO_EVERYONE
TIKTOK_PRIVACY = os.environ.get("TIKTOK_PRIVACY") or "SELF_ONLY"

VOZ = "es-ES-AlvaroNeural"
BUSQUEDA_PEXELS = "mystery dark"
ANCHO, ALTO = 1080, 1920
AVISO_HISTORIAS_RESTANTES = 15  # Avisa por Telegram cuando queden menos de estas

FUENTES_POSIBLES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def elegir_fuente():
    for ruta in FUENTES_POSIBLES:
        if os.path.exists(ruta):
            return ruta
    print("ERROR: no se encontró ninguna fuente TrueType en el sistema.")
    sys.exit(1)


def ajustar_vertical(clip):
    """Escala y recorta al centro a 1080x1920 sin deformar la imagen."""
    clip = clip.resize(height=ALTO)
    if clip.w < ANCHO:
        clip = clip.resize(width=ANCHO)
    return crop(clip, width=ANCHO, height=ALTO, x_center=clip.w / 2, y_center=clip.h / 2)


def crear_subtitulos(texto, duracion, ruta_fuente, palabras_por_bloque=6):
    """Subtítulos amarillos con borde negro, por bloques, repartidos según la longitud de cada bloque."""
    palabras = texto.split()
    bloques = [" ".join(palabras[i:i + palabras_por_bloque]) for i in range(0, len(palabras), palabras_por_bloque)]
    total_caracteres = sum(len(b) for b in bloques)
    fuente = ImageFont.truetype(ruta_fuente, 80)
    alto_linea = 100

    clips = []
    inicio = 0.0
    for bloque in bloques:
        dur = duracion * len(bloque) / total_caracteres
        lineas = textwrap.wrap(bloque, width=18)
        alto_img = alto_linea * len(lineas) + 40
        img = Image.new("RGBA", (ANCHO, alto_img), (0, 0, 0, 0))
        dibujo = ImageDraw.Draw(img)
        y = 20
        for linea in lineas:
            ancho_txt = dibujo.textlength(linea, font=fuente)
            dibujo.text(((ANCHO - ancho_txt) / 2, y), linea, font=fuente,
                        fill=(255, 230, 0, 255), stroke_width=5, stroke_fill=(0, 0, 0, 255))
            y += alto_linea
        clip = (ImageClip(np.array(img))
                .set_start(inicio)
                .set_duration(dur)
                .set_position(("center", "center")))
        clips.append(clip)
        inicio += dur
    return clips


def descargar(url, destino):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for trozo in r.iter_content(1024 * 1024):
                f.write(trozo)


def subir_a_youtube(archivo, titulo, descripcion):
    """Sube el vídeo como Short y devuelve su enlace."""
    credenciales = Credentials(
        None, refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=credenciales, cache_discovery=False)
    cuerpo = {
        "snippet": {
            "title": titulo[:100],
            "description": descripcion,
            "tags": ["Shorts", "Misterio", "CasosReales", "HistoriasIA", "Enigma"],
            "categoryId": "24",  # Entretenimiento
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # Voz generada por IA
        },
    }
    peticion = youtube.videos().insert(
        part="snippet,status", body=cuerpo,
        media_body=MediaFileUpload(archivo, mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    respuesta = None
    while respuesta is None:
        _, respuesta = peticion.next_chunk()
    return f"https://youtube.com/shorts/{respuesta['id']}"


def subir_a_tiktok(archivo, titulo):
    """Publica el vídeo en TikTok con la Content Posting API y devuelve el publish_id."""
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": TIKTOK_CLIENT_KEY, "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": TIKTOK_REFRESH_TOKEN,
    })
    token = r.json()
    if "access_token" not in token:
        raise RuntimeError(f"no se pudo renovar el token de TikTok: {token}")

    tamano = os.path.getsize(archivo)
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/", timeout=30,
        headers={"Authorization": f"Bearer {token['access_token']}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": {"title": titulo[:2200], "privacy_level": TIKTOK_PRIVACY},
            # Un solo trozo: los vídeos pesan menos de 50 MB
            "source_info": {"source": "FILE_UPLOAD", "video_size": tamano,
                            "chunk_size": tamano, "total_chunk_count": 1},
        },
    )
    datos = r.json()
    if datos.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok rechazó la publicación: {datos.get('error')}")

    with open(archivo, "rb") as f:
        requests.put(datos["data"]["upload_url"], data=f, timeout=300, headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{tamano - 1}/{tamano}",
        }).raise_for_status()
    return datos["data"]["publish_id"]


async def main():
    # Comprobar secretos
    for nombre, valor in [("PEXELS_API_KEY", PEXELS_API_KEY),
                          ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
                          ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)]:
        if not valor:
            print(f"ERROR: falta el secret {nombre}.")
            sys.exit(1)

    ruta_fuente = elegir_fuente()

    # -----------------------------------------------------------
    # 1. Leer contador e historia
    # -----------------------------------------------------------
    print("[1/7] Iniciando lectura de archivos del repositorio...")
    if not os.path.exists("contador.txt"):
        with open("contador.txt", "w") as f:
            f.write("1")
    with open("contador.txt", "r") as f:
        n_episodio = f.read().strip() or "1"

    if not os.path.exists("historias.txt") or os.stat("historias.txt").st_size == 0:
        print("ERROR: El archivo historias.txt está vacío o no existe.")
        sys.exit(1)
    with open("historias.txt", "r", encoding="utf-8-sig") as f:
        lineas = [l for l in f.readlines() if l.strip()]
    if not lineas:
        print("ERROR: historias.txt solo contiene líneas vacías.")
        sys.exit(1)

    historia_actual = lineas[0].strip()
    historias_restantes = lineas[1:]
    print(f"Procesando: Caso Real - Episodio {n_episodio}")

    # -----------------------------------------------------------
    # 2. Voz con Edge-TTS
    # -----------------------------------------------------------
    print("[2/7] Generando locución de voz con Microsoft Edge-TTS...")
    archivo_audio = "voz_episodio.mp3"
    await edge_tts.Communicate(historia_actual, VOZ).save(archivo_audio)

    audiovoz = AudioFileClip(archivo_audio)
    duracion_objetivo = audiovoz.duration
    print(f"Duración del episodio: {duracion_objetivo:.2f} segundos.")

    # -----------------------------------------------------------
    # 3. Vídeos de fondo de Pexels
    # -----------------------------------------------------------
    print("[3/7] Buscando videos de fondo verticales en Pexels...")
    respuesta = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": BUSQUEDA_PEXELS, "orientation": "portrait", "per_page": 30},
        timeout=30,
    )
    if respuesta.status_code != 200:
        print(f"ERROR Pexels {respuesta.status_code}: {respuesta.text[:300]}")
        sys.exit(1)
    videos = respuesta.json().get("videos", [])
    if not videos:
        print("ERROR: Pexels no devolvió vídeos para la búsqueda.")
        sys.exit(1)

    print("Descargando archivos visuales...")
    random.shuffle(videos)
    clips_descargados = []
    duracion_acumulada = 0.0

    for i, vid in enumerate(videos):
        if duracion_acumulada >= duracion_objetivo:
            break
        archivos = [f for f in vid.get("video_files", []) if f.get("link") and f.get("height")]
        if not archivos:
            continue
        # Preferir verticales entre 1280 y 1920 px de alto (sin 4K, que ralentiza mucho)
        verticales = [f for f in archivos if f["height"] > (f.get("width") or 0) and 1280 <= f["height"] <= 1920]
        candidatos = verticales or [f for f in archivos if f["height"] <= 1920] or archivos
        elegido = max(candidatos, key=lambda f: f["height"])

        nombre_clip = f"clip_{i}.mp4"
        try:
            descargar(elegido["link"], nombre_clip)
            clip = ajustar_vertical(VideoFileClip(nombre_clip).without_audio())
        except Exception as e:
            print(f"Aviso: se descarta un clip por error: {e}")
            continue
        clips_descargados.append(clip)
        duracion_acumulada += clip.duration

    if not clips_descargados:
        print("ERROR: no se pudo descargar ningún clip.")
        sys.exit(1)

    # -----------------------------------------------------------
    # 4. Montaje
    # -----------------------------------------------------------
    print("[4/7] Iniciando motor de edición automatizada de video...")
    video_fondo = concatenate_videoclips(clips_descargados, method="compose")
    if video_fondo.duration >= duracion_objetivo:
        video_fondo = video_fondo.subclip(0, duracion_objetivo)
    else:
        video_fondo = loop(video_fondo, duration=duracion_objetivo)
    video_fondo = video_fondo.set_audio(audiovoz)

    subtitulos = crear_subtitulos(historia_actual, duracion_objetivo, ruta_fuente)
    video_final = CompositeVideoClip([video_fondo] + subtitulos, size=(ANCHO, ALTO))

    # -----------------------------------------------------------
    # 5. Renderizado
    # -----------------------------------------------------------
    archivo_final_mp4 = f"Episodio_{n_episodio}.mp4"
    print("[5/7] Renderizando archivo final en formato vertical...")
    video_final.write_videofile(
        archivo_final_mp4, fps=24, codec="libx264", audio_codec="aac",
        bitrate="4000k", preset="veryfast", threads=2, logger=None,
    )

    tamano_mb = os.path.getsize(archivo_final_mp4) / (1024 * 1024)
    print(f"Tamaño del vídeo: {tamano_mb:.1f} MB")
    if tamano_mb > 49:
        print("ERROR: el vídeo supera el límite de 50 MB de Telegram para bots.")
        sys.exit(1)

    # -----------------------------------------------------------
    # 6. Publicación en YouTube Shorts y TikTok, y envío a Telegram
    # -----------------------------------------------------------
    hashtags = f"#Shorts #TikTokViral #Misterio #CasosReales #HistoriasIA #ReelsMundo #Enigma #Episodio{n_episodio}"
    titulo = f"Misterios Sin Resolver - Episodio {n_episodio}"
    estados = []  # Una línea por red social para el mensaje de Telegram

    # Si una subida falla no paramos: el vídeo sigue llegando por Telegram para subirlo a mano
    if YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN:
        print("[6/7] Subiendo el vídeo a YouTube Shorts...")
        try:
            enlace = subir_a_youtube(archivo_final_mp4, f"{titulo} #Shorts",
                                     f"{historia_actual[:300]}...\n\n{hashtags}")
            print(f"Subido a YouTube: {enlace}")
            estados.append(f"▶️ YouTube Shorts: [publicado]({enlace})")
        except Exception as e:
            print(f"AVISO: no se pudo subir a YouTube: {e}")
            estados.append("⚠️ YouTube Shorts: falló, súbelo tú a mano")

    if TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN:
        print("[6/7] Subiendo el vídeo a TikTok...")
        try:
            subir_a_tiktok(archivo_final_mp4, f"{titulo} {hashtags.replace('#Shorts ', '')}")
            print("Subido a TikTok.")
            estados.append("🎵 TikTok: publicado")
        except Exception as e:
            print(f"AVISO: no se pudo subir a TikTok: {e}")
            estados.append("⚠️ TikTok: falló, súbelo tú a mano")

    if not estados:
        estados.append("📝 Descarga este archivo de video y súbelo a tus redes sociales.")

    print("[6/7] Conectando con los servidores de Telegram...")
    mensaje_texto = (
        f"🎬 ¡TU VIDEO ESTÁ LISTO!\n\n"
        f"📌 *{titulo}*\n"
        + "\n".join(estados) + "\n\n"
        f"🏷️ *Hashtags optimizados para pegar:*\n"
        f"{hashtags}"
    )

    bot = Bot(token=TELEGRAM_TOKEN)
    async with bot:
        with open(archivo_final_mp4, "rb") as video_file:
            await bot.send_video(
                chat_id=TELEGRAM_CHAT_ID, video=video_file, caption=mensaje_texto,
                parse_mode="Markdown", supports_streaming=True,
                write_timeout=300, read_timeout=300, connect_timeout=60,
            )
        print("¡Video enviado con éxito a tu aplicación móvil!")

        quedan = len(historias_restantes)
        if quedan < AVISO_HISTORIAS_RESTANTES:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⚠️ Aviso: solo quedan {quedan} historias en historias.txt. Añade más para que el bot no se pare.",
            )

    # -----------------------------------------------------------
    # 7. Guardar progreso
    # -----------------------------------------------------------
    print("[7/7] Guardando el progreso del canal en la nube...")
    with open("contador.txt", "w") as f:
        f.write(str(int(n_episodio) + 1))
    with open("historias.txt", "w", encoding="utf-8") as f:
        f.writelines(historias_restantes)
    print("Todo guardado correctamente. Sistema listo para mañana.")


if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())

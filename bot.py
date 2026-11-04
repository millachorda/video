import os
import sys
import random
import asyncio
import requests
import edge_tts
from telegram import Bot
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
from moviepy.video.fx.all import crop, loop

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

FUENTE = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
ANCHO, ALTO = 1080, 1920


def ajustar_vertical(clip):
    """Escala y recorta al centro a 1080x1920 sin deformar."""
    clip = clip.resize(height=ALTO)
    if clip.w < ANCHO:
        clip = clip.resize(width=ANCHO)
    return crop(clip, width=ANCHO, height=ALTO, x_center=clip.w / 2, y_center=clip.h / 2)


async def main():
    for nombre, valor in [("PEXELS_API_KEY", PEXELS_API_KEY), ("TELEGRAM_TOKEN", TELEGRAM_TOKEN), ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)]:
        if not valor:
            print(f"ERROR: falta el secret {nombre}.")
            sys.exit(1)

    print("[1/7] Iniciando lectura de archivos del repositorio...")
    if not os.path.exists("contador.txt"):
        with open("contador.txt", "w") as f:
            f.write("1")
    with open("contador.txt", "r") as f:
        n_episodio = f.read().strip()

    if not os.path.exists("historias.txt") or os.stat("historias.txt").st_size == 0:
        print("ERROR: El archivo historias.txt está vacío o no existe.")
        sys.exit(1)
    with open("historias.txt", "r", encoding="utf-8") as f:
        lineas = [l for l in f.readlines() if l.strip()]
    if not lineas:
        print("ERROR: historias.txt solo contiene líneas vacías.")
        sys.exit(1)

    historia_actual = lineas[0].strip()
    historias_restantes = lineas[1:]
    print(f"Procesando: Caso Real - Episodio {n_episodio}")

    # Voz con Edge-TTS (librería directa, sin os.system)
    print("[2/7] Generando locución de voz con Microsoft Edge-TTS...")
    archivo_audio = "voz_episodio.mp3"
    await edge_tts.Communicate(historia_actual, "es-ES-AlvaroNeural").save(archivo_audio)

    # Pexels: endpoint correcto de la API de vídeos
    print("[3/7] Buscando videos de fondo verticales en Pexels...")
    respuesta = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": "mystery dark", "orientation": "portrait", "per_page": 30},
        timeout=30,
    )
    if respuesta.status_code != 200:
        print(f"ERROR Pexels {respuesta.status_code}: {respuesta.text[:300]}")
        sys.exit(1)
    videos = respuesta.json().get("videos", [])
    if not videos:
        print("ERROR: Pexels no devolvió vídeos para la búsqueda.")
        sys.exit(1)

    audiovoz = AudioFileClip(archivo_audio)
    duracion_objetivo = audiovoz.duration
    print(f"Duración del episodio: {duracion_objetivo:.2f} segundos. Descargando archivos visuales...")

    clips_descargados = []
    duracion_acumulada = 0
    random.shuffle(videos)

    for i, vid in enumerate(videos):
        if duracion_acumulada >= duracion_objetivo:
            break
        archivos = [f for f in vid.get("video_files", []) if f.get("link") and f.get("height")]
        if not archivos:
            continue
        # Preferir verticales de al menos 1280 px de alto, sin pasarse a 4K
        verticales = [f for f in archivos if f["height"] > f.get("width", 0) and 1280 <= f["height"] <= 1920]
        elegido = max(verticales or archivos, key=lambda f: f["height"] if f["height"] <= 1920 else 0)

        nombre_clip = f"clip_{i}.mp4"
        with requests.get(elegido["link"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(nombre_clip, "wb") as f:
                for trozo in r.iter_content(1024 * 1024):
                    f.write(trozo)

        clip = ajustar_vertical(VideoFileClip(nombre_clip).without_audio())
        clips_descargados.append(clip)
        duracion_acumulada += clip.duration

    if not clips_descargados:
        print("ERROR: no se pudo descargar ningún clip.")
        sys.exit(1)

    print("[4/7] Iniciando motor de edición automatizada de video...")
    video_fondo = concatenate_videoclips(clips_descargados, method="compose")
    if video_fondo.duration >= duracion_objetivo:
        video_fondo = video_fondo.subclip(0, duracion_objetivo)
    else:
        video_fondo = loop(video_fondo, duration=duracion_objetivo)
    video_fondo = video_fondo.set_audio(audiovoz)

    txt_clip = TextClip(
        historia_actual, fontsize=60, color="yellow", font=FUENTE,
        stroke_color="black", stroke_width=2, size=(900, None), method="caption",
    ).set_position(("center", "center")).set_duration(duracion_objetivo)

    video_final = CompositeVideoClip([video_fondo, txt_clip], size=(ANCHO, ALTO))

    archivo_final_mp4 = f"Episodio_{n_episodio}.mp4"
    print("[5/7] Renderizando archivo final en formato vertical...")
    video_final.write_videofile(
        archivo_final_mp4, fps=24, codec="libx264", audio_codec="aac",
        bitrate="4000k", preset="veryfast", threads=2,
    )

    tamano_mb = os.path.getsize(archivo_final_mp4) / (1024 * 1024)
    print(f"Tamaño del vídeo: {tamano_mb:.1f} MB")
    if tamano_mb > 49:
        print("ERROR: el vídeo supera el límite de 50 MB de Telegram para bots.")
        sys.exit(1)

    print("[6/7] Conectando con los servidores de Telegram...")
    mensaje_texto = (
        f"🎬 ¡TU VIDEO ESTÁ LISTO!\n\n"
        f"📌 *Misterios Sin Resolver - Episodio {n_episodio}*\n"
        f"📝 Descarga este archivo de video y súbelo a tus redes sociales.\n\n"
        f"🏷️ *Hashtags optimizados para pegar:*\n"
        f"#Shorts #TikTokViral #Misterio #CasosReales #HistoriasIA #ReelsMundo #Enigma #Episodio{n_episodio}"
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

    print("[7/7] Guardando el progreso del canal en la nube...")
    with open("contador.txt", "w") as f:
        f.write(str(int(n_episodio) + 1))
    with open("historias.txt", "w", encoding="utf-8") as f:
        f.writelines(historias_restantes)
    print("Todo guardado correctamente. Sistema listo para mañana.")


if __name__ == "__main__":
    asyncio.run(main())

import os
import sys
import random
import asyncio
import requests
from telegram import Bot
from moviepy.editor import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

# 1. Configuración de Variables de Entorno (Secretos de GitHub)
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

async def main():
    print("[1/7] Iniciando lectura de archivos del repositorio...")
    
    # 2. Leer y actualizar el contador de episodios
    if not os.path.exists("contador.txt"):
        with open("contador.txt", "w") as f: f.write("1")
    
    with open("contador.txt", "r") as f:
        n_episodio = f.read().strip()
    
    # 3. Leer la historia del día
    if not os.path.exists("historias.txt") or os.stat("historias.txt").st_size == 0:
        print("ERROR: El archivo historias.txt está vacío o no existe.")
        sys.exit(1)
        
    with open("historias.txt", "r", encoding="utf-8") as f:
        lineas = f.readlines()
        
    historia_actual = lineas[0].strip()
    historias_restantes = lineas[1:]

    print(f"Procesando: Caso Real - Episodio {n_episodio}")

    # 4. Generar la Voz con la IA Gratuita de Microsoft (Edge-TTS)
    print("[2/7] Generando locución de voz con Microsoft Edge-TTS...")
    archivo_audio = "voz_episodio.mp3"
    # Usamos una voz masculina excelente en español de España
    comando_tts = f'edge-tts --voice es-ES-AlvaroNeural --text "{historia_actual}" --write-media {archivo_audio}'
    os.system(comando_tts)

    # 5. Descargar Clips de Fondo Gratis desde Pexels
    print("[3/7] Buscando videos de fondo verticales en Pexels...")
    url_pexels = "https://pexels.com"
    cabeceras = {"Authorization": PEXELS_API_KEY}
    
    respuesta = requests.get(url_pexels, headers=cabeceras).json()
    videos = respuesta.get("videos", [])
    
    if not videos:
        print("ERROR: No se encontraron videos en Pexels. Revisa tu PEXELS_API_KEY.")
        sys.exit(1)

    # Medir la duración del audio creado
    audiovoz = AudioFileClip(archivo_audio)
    duracion_objetivo = audiovoz.duration
    
    print(f"Duración del episodio: {duracion_objetivo:.2s} segundos. Descargando archivos visuales...")
    
    clips_descargados = []
    duracion_acumulada = 0
    random.shuffle(videos) # Mezclar para que los videos no sean siempre los mismos
    
    for i, vid in enumerate(videos):
        if duracion_acumulada >= duracion_objetivo:
            break
        # Obtener el enlace del archivo de video en alta calidad
        archivos_video = vid.get("video_files", [])
        enlace_mp4 = [f.get("link") for f in archivos_video if f.get("width") == 1080 or f.get("height") == 1920]
        if not enlace_mp4:
            enlace_mp4 = [archivos_video[0].get("link")]
            
        nombre_clip = f"clip_{i}.mp4"
        with open(nombre_clip, "wb") as f:
            f.write(requests.get(enlace_mp4[0]).content)
            
        clip = VideoFileClip(nombre_clip).resize(newsize=(1080, 1920))
        clips_descargados.append(clip)
        duracion_acumulada += clip.duration

    # 6. Edición Automática con MoviePy (Juntar capas, música y subtítulos)
    print("[4/7] Iniciando motor de edición automatizada de video...")
    video_fondo = concatenate_videoclips(clips_descargados).subclip(0, duracion_objetivo)
    video_fondo = video_fondo.set_audio(audiovoz)

    # Añadir subtítulo básico amarillo word-by-word en el centro
    # Para entornos Linux en la nube usamos una tipografía estándar cargada por defecto
    txt_clip = TextClip(historia_actual, fontsize=60, color='yellow', font='Liberation-Sans-Bold', size=(900, None), method='caption')
    txt_clip = txt_clip.set_position(('center', 'center')).set_duration(duracion_objetivo)

    video_final = CompositeVideoClip([video_fondo, txt_clip])
    
    archivo_final_mp4 = f"Episodio_{n_episodio}.mp4"
    print("[5/7] Renderizando archivo final en formato vertical...")
    video_final.write_videofile(archivo_final_mp4, fps=24, codec="libx264", audio_codec="aac")

    # 7. Enviar el resultado directamente a tu Telegram
    print("[6/7] Conectando con los servidores de Telegram...")
    bot = Bot(token=TELEGRAM_TOKEN)
    
    mensaje_texto = (
        f"🎬 ¡TU VIDEO ESTÁ LISTO!\n\n"
        f"📌 *Misterios Sin Resolver - Episodio {n_episodio}*\n"
        f"📝 Descarga este archivo de video y súbelo a tus redes sociales.\n\n"
        f"🏷️ *Hashtags optimizados para pegar:*\n"
        f"#Shorts #TikTokViral #Misterio #CasosReales #HistoriasIA #ReelsMundo #Enigma #Episodio{n_episodio}"
    )
    
    with open(archivo_final_mp4, "rb") as video_file:
        await bot.send_video(chat_id=TELEGRAM_CHAT_ID, video=video_file, caption=mensaje_texto, parse_mode="Markdown")
    print("¡Video enviado con éxito a tu aplicación móvil!")

    # 8. Actualizar los archivos locales para el día siguiente
    print("[7/7] Guardando el progreso del canal en la nube...")
    with open("contador.txt", "w") as f:
        f.write(str(int(n_episodio) + 1))
        
    with open("historias.txt", "w", encoding="utf-8") as f:
        f.writelines(historias_restantes)
        
    print("Todo guardado correctamente. Sistema listo para mañana.")

if __name__ == "__main__":
    asyncio.run(main())

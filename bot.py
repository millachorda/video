import os
import sys
import asyncio
import subprocess

import requests
from telegram import Bot
from historias_ia import generar_historias
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import montaje

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
# "borradores": el vídeo llega a tus borradores de TikTok y lo publicas desde la app.
# "aprobacion": queda en cola (release de GitHub) para publicar_tiktok.py, el flujo auditado.
TIKTOK_MODO = os.environ.get("TIKTOK_MODO") or "borradores"
# Gemini escribe historias nuevas cuando quedan pocas (opcional)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Modo prueba: genera el vídeo y lo manda a Telegram, sin publicar ni gastar historia
PRUEBA = os.environ.get("PRUEBA") == "true"

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


def subir_borrador_tiktok(archivo):
    """Sube el vídeo a los borradores de TikTok: llega una notificación y se publica desde la app."""
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": TIKTOK_CLIENT_KEY, "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": TIKTOK_REFRESH_TOKEN,
    })
    token = r.json()
    if "access_token" not in token:
        raise RuntimeError(f"no se pudo renovar el token de TikTok: {token}")

    tamano = os.path.getsize(archivo)
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", timeout=30,
        headers={"Authorization": f"Bearer {token['access_token']}",
                 "Content-Type": "application/json; charset=UTF-8"},
        # Un solo trozo: los vídeos pesan menos de 50 MB
        json={"source_info": {"source": "FILE_UPLOAD", "video_size": tamano,
                              "chunk_size": tamano, "total_chunk_count": 1}},
    )
    datos = r.json()
    if datos.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok rechazó el borrador: {datos.get('error')}")

    with open(archivo, "rb") as f:
        requests.put(datos["data"]["upload_url"], data=f, timeout=300, headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{tamano - 1}/{tamano}",
        }).raise_for_status()
    return datos["data"]["publish_id"]


def encolar_para_tiktok(archivo, n_episodio, titulo, texto):
    """Deja el vídeo como release de GitHub para revisarlo y publicarlo con publicar_tiktok.py."""
    subprocess.run(["gh", "release", "create", f"tiktok-ep-{n_episodio}", archivo,
                    "--title", titulo, "--notes", texto], check=True)


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
    # 2. Voz con Edge-TTS (con el momento exacto de cada palabra)
    # -----------------------------------------------------------
    print("[2/7] Generando locución de voz con Microsoft Edge-TTS...")
    archivo_audio = "voz_episodio.mp3"
    palabras = await montaje.generar_voz(historia_actual, archivo_audio)
    print(f"Locución lista: {len(palabras)} palabras sincronizadas.")

    # -----------------------------------------------------------
    # 3. Planos de fondo de Pexels, buscados según la historia
    # -----------------------------------------------------------
    print("[3/7] Buscando videos de fondo verticales en Pexels...")
    busquedas = montaje.busquedas_para(historia_actual, GEMINI_API_KEY)
    print(f"Búsquedas: {', '.join(busquedas)}")
    duracion_voz = palabras[-1][1] if palabras else 60
    planos = montaje.descargar_planos(PEXELS_API_KEY, busquedas, duracion_voz + montaje.CIERRE)

    # -----------------------------------------------------------
    # 4-5. Montaje y renderizado
    # -----------------------------------------------------------
    print("[4/7] Iniciando motor de edición automatizada de video...")
    archivo_final_mp4 = f"Episodio_{n_episodio}.mp4"
    print("[5/7] Renderizando archivo final en formato vertical...")
    montaje.montar(historia_actual, n_episodio, archivo_audio, palabras, planos, ruta_fuente, archivo_final_mp4)

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
    if YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN and not PRUEBA:
        print("[6/7] Subiendo el vídeo a YouTube Shorts...")
        try:
            enlace = subir_a_youtube(archivo_final_mp4, f"{titulo} #Shorts",
                                     f"{historia_actual[:300]}...\n\n{hashtags}")
            print(f"Subido a YouTube: {enlace}")
            estados.append(f"▶️ YouTube Shorts: [publicado]({enlace})")
        except Exception as e:
            print(f"AVISO: no se pudo subir a YouTube: {e}")
            estados.append("⚠️ YouTube Shorts: falló, súbelo tú a mano")

    if TIKTOK_MODO == "aprobacion" and not PRUEBA:
        print("[6/7] Dejando el vídeo en la cola de TikTok...")
        try:
            encolar_para_tiktok(archivo_final_mp4, n_episodio, titulo, f"{titulo} {hashtags.replace('#Shorts ', '')}")
            estados.append("🎵 TikTok: pendiente de aprobar con el programa de publicación")
        except Exception as e:
            print(f"AVISO: no se pudo dejar en la cola de TikTok: {e}")
            estados.append("⚠️ TikTok: falló, súbelo tú a mano")
    elif TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN and not PRUEBA:
        print("[6/7] Subiendo el vídeo a los borradores de TikTok...")
        try:
            subir_borrador_tiktok(archivo_final_mp4)
            print("Subido a borradores de TikTok.")
            estados.append("🎵 TikTok: en tus borradores, ábrelo en la app y publícalo")
        except Exception as e:
            print(f"AVISO: no se pudo subir a TikTok: {e}")
            estados.append("⚠️ TikTok: falló, súbelo tú a mano")

    if PRUEBA:
        estados.append("🧪 Vídeo de prueba: no se ha publicado en ninguna red")
    elif not estados:
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

        if len(historias_restantes) < AVISO_HISTORIAS_RESTANTES and GEMINI_API_KEY and not PRUEBA:
            print("Quedan pocas historias: pidiendo nuevas a Gemini...")
            try:
                ya_usadas = [l.strip() for l in open("casos_publicados.txt", encoding="utf-8")] \
                    if os.path.exists("casos_publicados.txt") else []
                en_cola = [h.strip()[:100] for h in historias_restantes]
                nuevas = generar_historias(GEMINI_API_KEY, ya_usadas + [historia_actual[:100]] + en_cola)
                historias_restantes += [h + "\n" for h in nuevas]
                print(f"Gemini ha escrito {len(nuevas)} historias nuevas.")
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=f"📝 Gemini ha escrito {len(nuevas)} historias nuevas. Échales un vistazo en historias.txt.",
                )
            except Exception as e:
                print(f"AVISO: Gemini no pudo escribir historias: {e}")

        quedan = len(historias_restantes)
        if quedan < AVISO_HISTORIAS_RESTANTES:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⚠️ Aviso: solo quedan {quedan} historias en historias.txt. Añade más para que el bot no se pare.",
            )

    # -----------------------------------------------------------
    # 7. Guardar progreso
    # -----------------------------------------------------------
    if PRUEBA:
        print("Modo prueba: no se guarda el progreso.")
        return
    print("[7/7] Guardando el progreso del canal en la nube...")
    with open("contador.txt", "w") as f:
        f.write(str(int(n_episodio) + 1))
    with open("historias.txt", "w", encoding="utf-8") as f:
        f.writelines(historias_restantes)
    # Registro de casos ya usados, para que Gemini no los repita
    with open("casos_publicados.txt", "a", encoding="utf-8") as f:
        f.write(historia_actual[:100] + "\n")
    print("Todo guardado correctamente. Sistema listo para mañana.")


if __name__ == "__main__":
    asyncio.run(main())

import os
import sys
import json
import time
import asyncio
import subprocess

import requests
from telegram import Bot
from historias_ia import generar_historias, dividir_en_partes
import montaje
import youtube
import horario
import ilustraciones
from canales import ACTUAL as CANAL, ruta

# ---------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# YouTube es opcional (youtube.py lee sus secrets): si faltan, el vídeo solo va a Telegram
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
# Deja el vídeo en la cola de publicar_tiktok.py aunque sea de prueba (para grabar la demo)
ENCOLAR_TIKTOK = os.environ.get("ENCOLAR_TIKTOK") == "true"

AVISO_HISTORIAS_RESTANTES = 15  # Avisa por Telegram cuando queden menos de estas
# Cada caso se cuenta en una serie de vídeos que acaban en suspense: la gente sigue el canal
# para ver la siguiente parte. Con 1 vuelve a ser un vídeo por caso.
PARTES_POR_CASO = CANAL["partes"] or int(os.environ.get("PARTES_POR_CASO") or 5)
CONTADOR, HISTORIAS, PUBLICADOS = ruta("contador.txt"), ruta("historias.txt"), ruta("casos_publicados.txt")
HOY = ruta("hoy.txt")  # Vídeos publicados hoy, para el horario aleatorio
# Lanzado por el horario (no a mano): se comprueba otra vez que toca, por si otra ejecución ya lo hizo
PROGRAMADO = os.environ.get("PROGRAMADO") == "true"

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


def sin_markdown(texto):
    """Quita los caracteres que rompen el formato Markdown de Telegram."""
    return "".join(c for c in texto if c not in "*_`[]")


def es_parte_pendiente(linea):
    return linea.lstrip().startswith("{")


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

    # Que el archivo llegue no basta: TikTok lo procesa después y puede rechazarlo. Ojo: a menudo
    # se queda en PROCESSING_UPLOAD aunque el borrador llegue bien, así que solo cuenta un FAILED
    publish_id = datos["data"]["publish_id"]
    for _ in range(10):
        time.sleep(6)
        estado = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/", timeout=30,
            headers={"Authorization": f"Bearer {token['access_token']}",
                     "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": publish_id},
        ).json()
        situacion = estado.get("data", {}).get("status")
        if situacion == "FAILED" or estado.get("error", {}).get("code") not in (None, "ok"):
            raise RuntimeError(f"TikTok no aceptó el borrador: {estado}")
        if situacion == "SEND_TO_USER_INBOX":
            break
    print(f"  Estado del borrador en TikTok: {situacion}")
    return publish_id


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
    print(f"Canal: {CANAL['nombre']}")
    from canales import ID
    if PROGRAMADO and not horario.toca(ID, HOY):
        print("Ahora no le toca a este canal (otra ejecución ya publicó este vídeo).")
        return
    if PROGRAMADO and not youtube.configurado():
        print("Este canal aún no está conectado a YouTube: no se hace nada.")
        return
    if not os.path.exists(CONTADOR):
        with open(CONTADOR, "w") as f:
            f.write("1")
    with open(CONTADOR, "r") as f:
        n_episodio = f.read().strip() or "1"

    if (not os.path.exists(HISTORIAS) or not open(HISTORIAS, encoding="utf-8-sig").read().strip()) and GEMINI_API_KEY:
        # Canal recién creado: Gemini escribe la primera tanda de historias
        print("No hay historias: pidiendo la primera tanda a Gemini...")
        primeras = []
        for intento in range(3):  # Si la tanda sale vacía (todas descartadas), se vuelve a pedir
            try:
                ya_usadas = [l.strip()[:100] for l in open(PUBLICADOS, encoding="utf-8")] \
                    if os.path.exists(PUBLICADOS) else []
                primeras = generar_historias(GEMINI_API_KEY, ya_usadas, CANAL["encargo_historias"])
            except Exception as e:
                print(f"AVISO: Gemini falló al escribir la primera tanda: {e}")
            if primeras:
                break
        with open(HISTORIAS, "w", encoding="utf-8") as f:
            f.writelines(h + "\n" for h in primeras)
    if not os.path.exists(HISTORIAS) or os.stat(HISTORIAS).st_size == 0:
        print("ERROR: El archivo historias.txt está vacío o no existe.")
        sys.exit(1)
    with open(HISTORIAS, "r", encoding="utf-8-sig") as f:
        lineas = [l for l in f.readlines() if l.strip()]
    if not lineas:
        print("ERROR: historias.txt solo contiene líneas vacías.")
        sys.exit(1)

    historias_restantes = lineas[1:]
    if es_parte_pendiente(lineas[0]):
        # Siguiente parte de una serie ya empezada
        serie = json.loads(lineas[0])
        historia_actual, parte, total = serie["texto"], serie["parte"], serie["total"]
        titulo_base, enlace_anterior, caso_original = serie.get("titulo"), serie.get("anterior"), serie["caso"]
    else:
        historia_actual, parte, total = lineas[0].strip(), 1, 1
        titulo_base, enlace_anterior, caso_original = None, None, lineas[0].strip()
        if PARTES_POR_CASO > 1 and GEMINI_API_KEY:
            try:
                partes = dividir_en_partes(GEMINI_API_KEY, caso_original, PARTES_POR_CASO)
                historia_actual, total = partes[0], len(partes)
                # Las demás partes quedan delante en la cola; el título y enlace se rellenan al publicar
                historias_restantes = [json.dumps({"parte": k, "total": total, "texto": t, "caso": caso_original},
                                                  ensure_ascii=False) + "\n"
                                       for k, t in enumerate(partes[1:], start=2)] + historias_restantes
                print(f"Caso dividido en {total} partes.")
            except Exception as e:
                print(f"AVISO: no se pudo dividir el caso, va en un solo vídeo: {e}")
    print(f"Procesando: episodio {n_episodio}, parte {parte}/{total}")

    # -----------------------------------------------------------
    # 2. Plan del vídeo (Gemini): gancho hablado, búsquedas y hashtags del caso
    # -----------------------------------------------------------
    plan = montaje.planificar(historia_actual, GEMINI_API_KEY)
    print(f"Gancho: {plan['gancho']}")

    # -----------------------------------------------------------
    # 2b. Voz con Edge-TTS (con el momento exacto de cada palabra)
    # -----------------------------------------------------------
    print("[2/7] Generando locución de voz con Microsoft Edge-TTS...")
    archivo_audio = "voz_episodio.mp3"
    # Con límite de tiempo: si el servicio de voz se cuelga, mejor fallar que agotar las 45 min
    palabras = await asyncio.wait_for(
        montaje.generar_voz(f"{plan['gancho']} {historia_actual}", archivo_audio), timeout=300)
    print(f"Locución lista: {len(palabras)} palabras sincronizadas.")

    # -----------------------------------------------------------
    # 3. Planos de fondo de Pexels, buscados según la historia
    # -----------------------------------------------------------
    duracion_voz = palabras[-1][1] if palabras else 60
    planos = None
    # Ilustraciones propias (stickman) si Cloudflare está configurado; si no, o si fallan, vídeos de Pexels
    if ilustraciones.configurado() and len(plan.get("escenas", [])) >= 5:
        print(f"[3/7] Dibujando {len(plan['escenas'])} ilustraciones con FLUX...")
        rutas = ilustraciones.generar_todas(plan["escenas"])
        if len(rutas) >= 5:
            planos = montaje.planos_ilustrados(rutas, duracion_voz + montaje.CIERRE)
        else:
            print("AVISO: no salieron suficientes ilustraciones; uso vídeos de Pexels.")
    if planos is None:
        print("[3/7] Buscando videos de fondo verticales en Pexels...")
        print(f"Búsquedas: {', '.join(plan['busquedas'])}")
        planos = montaje.descargar_planos(PEXELS_API_KEY, plan["busquedas"], duracion_voz + montaje.CIERRE)

    # -----------------------------------------------------------
    # 4-5. Montaje y renderizado
    # -----------------------------------------------------------
    print("[4/7] Iniciando motor de edición automatizada de video...")
    archivo_final_mp4 = f"Episodio_{n_episodio}.mp4"
    print("[5/7] Renderizando archivo final en formato vertical...")
    montaje.montar(historia_actual, plan["gancho"], parte, total, archivo_audio, palabras, planos,
                   ruta_fuente, archivo_final_mp4, rotulo=plan.get("rotulo"), pregunta=plan.get("pregunta"),
                   etiqueta=CANAL["etiqueta"].format(n=n_episodio))

    tamano_mb = os.path.getsize(archivo_final_mp4) / (1024 * 1024)
    print(f"Tamaño del vídeo: {tamano_mb:.1f} MB")
    if tamano_mb > 49:
        print("ERROR: el vídeo supera el límite de 50 MB de Telegram para bots.")
        sys.exit(1)

    # -----------------------------------------------------------
    # 6. Publicación en YouTube Shorts y TikTok, y envío a Telegram
    # -----------------------------------------------------------
    # Hashtags: los del caso concreto (Gemini) primero, luego los fijos del nicho
    del_caso = " ".join(plan["hashtags"])
    hashtags = f"{del_caso} {CANAL['hashtags_youtube']}".strip()
    hashtags_tiktok = f"{del_caso} {CANAL['hashtags_tiktok']}".strip()
    # Título: el gancho del caso (el de la parte 1 para toda la serie), que despierta curiosidad
    if not titulo_base:
        titulo_base = sin_markdown(plan["gancho"]).rstrip(".")
    titulo = (f"{titulo_base} (Parte {parte}/{total})" if total > 1
              else titulo_base[:88 - len(CANAL.get("sufijo_titulo", ""))] + CANAL.get("sufijo_titulo", ""))
    estados = []  # Una línea por red social para el mensaje de Telegram
    enlace = None

    # Si una subida falla no paramos: el vídeo sigue llegando por Telegram para subirlo a mano
    if youtube.configurado() and not PRUEBA:
        print("[6/7] Subiendo el vídeo a YouTube Shorts...")
        try:
            descripcion = (f"{CANAL['aviso']}\n\n" if CANAL.get("aviso") else "") + f"{historia_actual[:300]}...\n\n"
            if os.path.exists(ruta("ultimo_largo.txt")):
                ultimo_largo = open(ruta("ultimo_largo.txt"), encoding="utf-8").read().strip()
                if ultimo_largo:
                    descripcion += f"📺 Vídeo completo de 10 minutos: {ultimo_largo}\n\n"
            if enlace_anterior:
                descripcion += f"⏪ Parte anterior: {enlace_anterior}\n\n"
            _, enlace = youtube.subir(archivo_final_mp4, f"{titulo[:91]} #Shorts", descripcion + hashtags,
                                     CANAL["etiquetas"], categoria=CANAL["categoria"])
            print(f"Subido a YouTube: {enlace}")
            estados.append(f"▶️ YouTube Shorts: [publicado]({enlace})")
        except Exception as e:
            print(f"AVISO: no se pudo subir a YouTube: {e}")
            estados.append("⚠️ YouTube Shorts: falló, súbelo tú a mano")

    if not CANAL["tiktok"]:
        pass  # La cuenta de TikTok conectada es solo la de un canal
    elif (TIKTOK_MODO == "aprobacion" and not PRUEBA) or ENCOLAR_TIKTOK:
        print("[6/7] Dejando el vídeo en la cola de TikTok...")
        try:
            encolar_para_tiktok(archivo_final_mp4, n_episodio, titulo, f"{titulo} {hashtags_tiktok}")
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
    if not estados:
        estados.append("📝 Descarga este archivo de video y súbelo a tus redes sociales.")

    print("[6/7] Conectando con los servidores de Telegram...")
    mensaje_texto = (
        f"🎬 {sin_markdown(CANAL['nombre'])}: ¡VÍDEO LISTO!\n\n"
        f"📌 *{titulo}*\n"
        + "\n".join(estados) + "\n\n"
        f"🏷️ *Texto para TikTok:*\n"
        f"{titulo} {hashtags_tiktok}"
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

        casos_en_cola = [h for h in historias_restantes if not es_parte_pendiente(h)]
        if len(casos_en_cola) < AVISO_HISTORIAS_RESTANTES and GEMINI_API_KEY and not PRUEBA:
            print("Quedan pocas historias: pidiendo nuevas a Gemini...")
            try:
                ya_usadas = [l.strip() for l in open(PUBLICADOS, encoding="utf-8")] \
                    if os.path.exists(PUBLICADOS) else []
                en_cola = [h.strip()[:100] for h in casos_en_cola]
                nuevas = generar_historias(GEMINI_API_KEY, ya_usadas + [caso_original[:100]] + en_cola,
                                            CANAL["encargo_historias"])
                historias_restantes += [h + "\n" for h in nuevas]
                casos_en_cola += nuevas
                print(f"Gemini ha escrito {len(nuevas)} historias nuevas.")
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=f"📝 Gemini ha escrito {len(nuevas)} historias nuevas. Échales un vistazo en historias.txt.",
                )
            except Exception as e:
                print(f"AVISO: Gemini no pudo escribir historias: {e}")

        quedan = len(casos_en_cola)
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
    with open(CONTADOR, "w") as f:
        f.write(str(int(n_episodio) + 1))
    horario.apuntar(HOY)
    if historias_restantes and es_parte_pendiente(historias_restantes[0]):
        siguiente = json.loads(historias_restantes[0])
        if siguiente.get("caso") == caso_original:
            siguiente.update(titulo=titulo_base, anterior=enlace)
            historias_restantes[0] = json.dumps(siguiente, ensure_ascii=False) + "\n"
    with open(HISTORIAS, "w", encoding="utf-8") as f:
        f.writelines(historias_restantes)
    # Registro de casos ya usados, para que Gemini no los repita
    if parte == 1:
        with open(PUBLICADOS, "a", encoding="utf-8") as f:
            f.write(caso_original[:100] + "\n")
    print("Todo guardado correctamente. Sistema listo para mañana.")


if __name__ == "__main__":
    asyncio.run(main())

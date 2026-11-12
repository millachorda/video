"""
Ilustraciones para los Shorts con FLUX (Cloudflare Workers AI): escenas 2D con un personaje stickman
que cuenta la historia, en vez de vídeos de stock. Con unas 70 imágenes al día cabe en el plan gratuito.

Necesita los secrets CF_ACCOUNT_ID y CF_API_TOKEN (token con permiso "Workers AI"). Si faltan o falla,
el bot vuelve a usar vídeos de Pexels.

    CANAL=curiomind CF_ACCOUNT_ID=... CF_API_TOKEN=... python ilustraciones.py   -> genera una de prueba
"""
import base64
import os
import time

import requests

from canales import ACTUAL as CANAL

CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
MODELO = "@cf/black-forest-labs/flux-1-schnell"

# El mismo personaje en todos los canales y vídeos: es lo que da identidad al formato
PERSONAJE = ("a simple stickman character with a big round white head, two small black dot eyes, "
             "a tiny neutral mouth and a thin black stick body")
ESTILO = ("2D cartoon illustration for an animated explainer video, flat colors, clean bold black outlines, "
          "detailed background, cinematic composition, no text, no letters, no watermark")


def configurado():
    return bool(CF_ACCOUNT_ID and CF_API_TOKEN)


def prompt_de(escena):
    estilo_canal = CANAL.get("estilo_ilustracion", "")
    return f"{escena}. The main character is {PERSONAJE}. {ESTILO}, {estilo_canal}"


def generar(escena, destino, intentos=3):
    """Genera una ilustración cuadrada (1024 px) y la guarda en destino. Devuelve True si salió bien."""
    for intento in range(intentos):
        try:
            r = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{MODELO}",
                headers={"Authorization": f"Bearer {CF_API_TOKEN}"}, timeout=120,
                json={"prompt": prompt_de(escena)[:2000], "steps": 6})
            if r.ok and r.json().get("result", {}).get("image"):
                with open(destino, "wb") as f:
                    f.write(base64.b64decode(r.json()["result"]["image"]))
                return True
            print(f"  Aviso: FLUX respondió {r.status_code}: {r.text[:200]}")
            if r.status_code in (400, 401, 403):
                return False  # Token o petición incorrectos: reintentar no sirve
        except requests.RequestException as e:
            print(f"  Aviso: FLUX no respondió: {e}")
        time.sleep(5 * (intento + 1))
    return False


def generar_todas(escenas, carpeta="ilustraciones"):
    """Genera las ilustraciones de un vídeo en orden; devuelve las rutas de las que salieron bien."""
    os.makedirs(carpeta, exist_ok=True)
    rutas = []
    for i, escena in enumerate(escenas):
        destino = f"{carpeta}/escena_{i:02d}.jpg"
        if generar(escena, destino):
            rutas.append(destino)
            print(f"  ilustración {i + 1}/{len(escenas)} lista")
    return rutas


if __name__ == "__main__":
    if not configurado():
        raise SystemExit("Faltan CF_ACCOUNT_ID y CF_API_TOKEN.")
    ok = generar("the stickman stands in front of an old wooden farmhouse in a snowy German forest at dusk",
                 "prueba_ilustracion.jpg")
    print("ok" if ok else "falló")

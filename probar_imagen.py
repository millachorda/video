"""Prueba qué modelos de imagen de Gemini funcionan con la clave del bot (y si el plan gratuito los permite)."""
import base64
import os

import requests

CLAVE = os.environ["GEMINI_API_KEY"]
PROMPT = ("Vertical 9:16 2D cartoon illustration. A simple stickman character with a big round white head, "
          "two dot eyes and a thin black body stands next to an old wooden farmhouse in a snowy German forest "
          "at dusk. Flat colors, clean bold outlines, detailed background like an animated explainer video. No text.")
os.makedirs("imagenes", exist_ok=True)

for modelo in ["gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation",
               "gemini-2.0-flash-exp-image-generation"]:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
        headers={"x-goog-api-key": CLAVE}, timeout=180,
        json={"contents": [{"parts": [{"text": PROMPT}]}],
              "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
    print(modelo, r.status_code, r.text[:300].replace("\n", " ") if not r.ok else "")
    if r.ok:
        for parte in r.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in parte:
                open(f"imagenes/{modelo}.png", "wb").write(base64.b64decode(parte["inlineData"]["data"]))
                print("  imagen guardada")

for modelo in ["imagen-4.0-fast-generate-001", "imagen-3.0-generate-002"]:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:predict",
        headers={"x-goog-api-key": CLAVE}, timeout=180,
        json={"instances": [{"prompt": PROMPT}], "parameters": {"sampleCount": 1, "aspectRatio": "9:16"}})
    print(modelo, r.status_code, r.text[:300].replace("\n", " ") if not r.ok else "")
    if r.ok and r.json().get("predictions"):
        open(f"imagenes/{modelo}.png", "wb").write(base64.b64decode(r.json()["predictions"][0]["bytesBase64Encoded"]))
        print("  imagen guardada")

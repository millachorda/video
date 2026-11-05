"""
Escribe historias nuevas para historias.txt con Gemini (plan gratuito de Google AI Studio).

bot.py lo usa solo cuando quedan pocas historias. Para probarlo sin tocar ningún archivo:
    GEMINI_API_KEY=... python historias_ia.py
"""
import json
import os
import sys
import time

import requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
# Si el principal está saturado, se prueban estos en orden
MODELOS = [GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash"]
HISTORIAS_POR_TANDA = 15


def generar_historias(api_key, casos_a_evitar):
    """Pide a Gemini historias nuevas con el mismo formato que historias.txt (una por línea)."""
    lista_evitar = "\n".join(f"- {c}" for c in casos_a_evitar) or "- (ninguno)"
    instrucciones = f"""Escribe {HISTORIAS_POR_TANDA} historias para vídeos cortos de un canal de misterios reales sin resolver.

Reglas:
- Solo casos REALES, muy conocidos y bien documentados (desapariciones, señales, crímenes sin resolver, enigmas históricos). No inventes casos, nombres, fechas ni cifras; si dudas de un dato, no lo incluyas.
- En español de España, narradas en tercera persona, en un solo párrafo de entre 480 y 580 caracteres.
- Empieza con la fecha y el lugar o con un detalle inquietante, cuenta los hechos clave y termina con una pregunta abierta sobre el misterio.
- Sin títulos, sin emojis, sin comillas tipográficas raras y sin saltos de línea dentro de cada historia.
- No repitas ninguno de estos casos, que ya están publicados o en cola:
{lista_evitar}

Devuelve solo un array JSON de strings, una historia por elemento."""

    # El plan gratuito a veces responde 503/429 por saturación: reintenta con esperas
    # crecientes y, si un modelo no responde, prueba con el siguiente
    errores = []
    for modelo in MODELOS:
        for intento in range(3):
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                headers={"x-goog-api-key": api_key}, timeout=120,
                json={
                    "contents": [{"parts": [{"text": instrucciones}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
                },
            )
            if r.ok:
                print(f"Historias escritas con {modelo}.")
                break
            errores.append(f"{modelo}: {r.status_code} {r.text[:200]}")
            if r.status_code not in (429, 500, 503):
                break
            time.sleep(20 * (intento + 1))
        if r.ok:
            break
    else:
        raise RuntimeError("Gemini no respondió:\n" + "\n".join(errores))
    texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    historias = [" ".join(h.split()) for h in json.loads(texto) if isinstance(h, str)]
    # Descarta las que se salgan mucho del tamaño: los subtítulos y la duración dependen de ello
    return [h for h in historias if 380 <= len(h) <= 700]


if __name__ == "__main__":
    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        sys.exit("Falta GEMINI_API_KEY.")
    historias = generar_historias(clave, [])
    print(f"Gemini ha devuelto {len(historias)} historias válidas.\n")
    for h in historias[:3]:
        print(f"- ({len(h)} caracteres) {h}\n")
    if not historias:
        sys.exit(1)

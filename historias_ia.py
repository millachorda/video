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
LIMITE_SEGUNDOS = 12 * 60


def _pedir(api_key, instrucciones, limite_segundos, temperatura):
    """Llama a Gemini pidiendo JSON y devuelve el texto de la respuesta."""
    # El plan gratuito a veces responde 503/429 por saturación: reintenta con esperas
    # crecientes y, si un modelo no responde, prueba con el siguiente
    errores = []
    respuesta = None
    # Límite total: el bot ya ha publicado el vídeo y aún tiene que guardar el progreso
    limite = time.monotonic() + limite_segundos
    for modelo in MODELOS:
        for intento in range(3):
            if time.monotonic() > limite:
                errores.append("se agotó el tiempo total")
                break
            try:
                # Escribir varias historias puede tardar minutos
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                    headers={"x-goog-api-key": api_key},
                    timeout=max(30, min(360, limite - time.monotonic())),
                    json={
                        "contents": [{"parts": [{"text": instrucciones}]}],
                        "generationConfig": {"responseMimeType": "application/json", "temperature": temperatura},
                    },
                )
            except requests.RequestException as e:
                errores.append(f"{modelo}: {e}")
            else:
                if r.ok:
                    print(f"Gemini respondió con {modelo}.")
                    respuesta = r.json()
                    break
                errores.append(f"{modelo}: {r.status_code} {r.text[:200]}")
                if r.status_code not in (429, 500, 503):
                    break
            time.sleep(20 * (intento + 1))
        if respuesta:
            break
    else:
        raise RuntimeError("Gemini no respondió:\n" + "\n".join(errores))
    return respuesta["candidates"][0]["content"]["parts"][0]["text"]


def dividir_en_partes(api_key, historia, n):
    """Convierte un caso en una serie de n vídeos que acaban en suspense para que la gente
    siga el canal. Devuelve la lista de textos o lanza una excepción si no sale bien."""
    instrucciones = f"""Este caso real de misterio se va a contar en una serie de {n} vídeos cortos seguidos.
Escríbelo como {n} partes en español de España, en tercera persona, cada una en un solo párrafo
de entre 380 y 480 caracteres (unos 30 segundos narrada):
- Parte 1: presenta el caso con una primera frase que impacte y corta en el momento más intrigante.
- Partes intermedias: empiezan recordando en una frase dónde se quedó la anterior, avanzan con hechos
  nuevos (la investigación, las pruebas, los testigos, las teorías…) y acaban en suspense.
- Última parte: cuenta lo que se sabe hoy y termina con una pregunta abierta para que la gente comente.
- Ninguna parte debe repetir lo que ya contó otra, salvo la frase de enlace.
Usa SOLO hechos reales y documentados de este caso; puedes añadir detalles reales conocidos, pero
no inventes nombres, fechas, cifras ni escenas. Si no hay tantos hechos, profundiza en el contexto
histórico, la investigación y las teorías publicadas. Sin títulos, sin emojis y sin saltos de línea.

Caso:
{historia}

Devuelve solo un array JSON con {n} strings, una parte por elemento, en orden."""
    partes = [" ".join(str(p).split()) for p in json.loads(_pedir(api_key, instrucciones, 5 * 60, 0.7))]
    if len(partes) != n or not all(300 <= len(p) <= 650 for p in partes):
        raise ValueError(f"la serie no salió bien: {len(partes)} partes, tamaños {[len(p) for p in partes]}")
    return partes


def generar_historias(api_key, casos_a_evitar):
    """Pide a Gemini historias nuevas con el mismo formato que historias.txt (una por línea)."""
    lista_evitar = "\n".join(f"- {c}" for c in casos_a_evitar) or "- (ninguno)"
    instrucciones = f"""Escribe {HISTORIAS_POR_TANDA} historias para vídeos cortos de un canal de misterios reales sin resolver.

Reglas:
- Solo casos REALES, muy conocidos y bien documentados (desapariciones, señales, crímenes sin resolver, enigmas históricos). No inventes casos, nombres, fechas ni cifras; si dudas de un dato, no lo incluyas.
- En español de España, narradas en tercera persona, en un solo párrafo de entre 400 y 480 caracteres (unos 30 segundos narrada).
- La primera frase tiene que impactar por sí sola (un dato inquietante, no una introducción), cuenta los hechos clave y termina con una pregunta abierta sobre el misterio.
- Sin títulos, sin emojis, sin comillas tipográficas raras y sin saltos de línea dentro de cada historia.
- No repitas ninguno de estos casos, que ya están publicados o en cola:
{lista_evitar}

Devuelve solo un array JSON de strings, una historia por elemento."""

    texto = _pedir(api_key, instrucciones, LIMITE_SEGUNDOS, 0.9)
    historias = [" ".join(h.split()) for h in json.loads(texto) if isinstance(h, str)]
    # Descarta las que se salgan mucho del tamaño: los subtítulos y la duración dependen de ello
    return [h for h in historias if 330 <= len(h) <= 650]


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

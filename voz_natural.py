"""
Voz más humana con Chatterbox (código abierto, licencia MIT): imita el timbre de una voz de referencia y
le da entonación natural. Se ejecuta en un entorno de Python aparte (lo prepara montaje.py) para que
sus librerías no choquen con las del montaje.

    python voz_natural.py texto.txt referencia.wav salida.wav tiempos.json [expresividad]

Genera la voz frase a frase y guarda en tiempos.json [[inicio, fin, palabra], ...]: el principio y el
final de cada frase son exactos y las palabras se reparten dentro según su longitud (para los subtítulos).
Las cifras se leen en palabras ("10" -> "diez"), pero en los subtítulos siguen saliendo en número.
"""
import json
import re
import sys

import numpy as np
import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from num2words import num2words

PAUSA = 0.18  # Segundos de silencio entre frases


def leer_cifras(frase):
    def cambiar(m):
        numero = m.group().replace(".", "")
        try:
            return num2words(int(numero), lang="es")
        except Exception:
            return m.group()
    return re.sub(r"\d[\d.]*", cambiar, frase)


def frases(texto):
    trozos = re.split(r"(?<=[.!?…])\s+", texto.strip())
    salida = []
    for t in trozos:  # Las muy largas se parten por comas para no pasar del límite del modelo
        while len(t) > 220 and "," in t[:220]:
            corte = t[:220].rfind(",") + 1
            salida.append(t[:corte].strip())
            t = t[corte:].strip()
        if t:
            salida.append(t)
    return salida


def main():
    archivo_texto, referencia, salida, archivo_tiempos = sys.argv[1:5]
    expresividad = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
    texto = open(archivo_texto, encoding="utf-8").read()
    torch.manual_seed(7)
    modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    trozos_audio, tiempos, t = [], [], 0.0
    silencio = np.zeros(int(PAUSA * modelo.sr), dtype=np.float32)
    for frase in frases(texto):
        wav = modelo.generate(leer_cifras(frase), language_id="es", audio_prompt_path=referencia,
                              exaggeration=expresividad).squeeze(0).numpy().astype(np.float32)
        duracion = len(wav) / modelo.sr
        palabras = frase.split()
        pesos = [len(p) + 2 for p in palabras]
        total, acumulado = sum(pesos), 0.0
        for p, peso in zip(palabras, pesos):
            inicio = t + duracion * acumulado / total
            acumulado += peso
            tiempos.append([round(inicio, 3), round(t + duracion * acumulado / total, 3), p])
        trozos_audio += [wav, silencio]
        t += duracion + PAUSA
        print(f"  frase lista ({duracion:.1f} s): {frase[:60]}", flush=True)
    sf.write(salida, np.concatenate(trozos_audio), modelo.sr)
    json.dump(tiempos, open(archivo_tiempos, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()

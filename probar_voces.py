"""Prueba voces gratuitas y de código abierto más naturales que las de Microsoft (para elegir de oído)."""
import asyncio
import os
import subprocess
import time
import traceback

TEXTO = ("¿Y si el océano Pacífico se congelara entero? En un segundo, el agua dejaría de moverse. "
         "A los diez minutos, las costas de medio planeta quedarían atrapadas bajo el hielo. "
         "Y tras tres días, el clima de la Tierra cambiaría para siempre.")
os.makedirs("voces", exist_ok=True)


def medir(nombre, funcion):
    t0 = time.time()
    try:
        funcion()
        print(f"OK {nombre}: {time.time() - t0:.0f} s")
    except Exception:
        print(f"FALLO {nombre}:")
        traceback.print_exc()


# Referencias para clonar el timbre (Chatterbox imita la voz y le da entonación más humana)
async def referencias():
    import edge_tts
    for voz in ["es-ES-AlvaroNeural", "es-ES-XimenaNeural"]:
        await edge_tts.Communicate(TEXTO, voz).save(f"voces/ref_{voz}.mp3")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"voces/ref_{voz}.mp3", "-ar", "24000",
                        "-ac", "1", f"voces/ref_{voz}.wav"], check=True)
asyncio.run(referencias())


def kokoro():
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    tubo = KPipeline(lang_code="e")  # Español
    for voz in ["ef_dora", "em_alex", "em_santa"]:
        audio = np.concatenate([a for _, _, a in tubo(TEXTO, voice=voz, speed=1.05)])
        sf.write(f"voces/kokoro_{voz}.wav", audio, 24000)


def chatterbox():
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    modelo = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    for ref in ["es-ES-AlvaroNeural", "es-ES-XimenaNeural"]:
        for expresividad in (0.5, 0.8):
            wav = modelo.generate(TEXTO, language_id="es", audio_prompt_path=f"voces/ref_{ref}.wav",
                                  exaggeration=expresividad)
            torchaudio.save(f"voces/chatterbox_{ref}_exp{expresividad}.wav", wav, modelo.sr)


medir("Kokoro", kokoro)
medir("Chatterbox", chatterbox)

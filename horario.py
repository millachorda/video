"""
Horas de publicación aleatorias: cada día, cada canal sortea 5 horas distintas entre las 8:00 y las
22:59 (hora de España), separadas al menos 2 horas. GitHub lanza el bot cada hora y solo publica el
canal al que ya le toca; los minutos los decide una espera aleatoria en el workflow.

Si GitHub se retrasa o se salta una hora, en la siguiente se recupera el vídeo pendiente: se compara
cuántos vídeos tocaban hasta ahora con cuántos se han publicado hoy (archivo hoy.txt de cada canal).

    python horario.py            -> lista JSON de los canales a los que les toca ahora
    python horario.py ver        -> horas de hoy de cada canal
"""
import datetime
import json
import random
import sys
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("Europe/Madrid")
PRIMERA, ULTIMA = 8, 22   # Horas posibles (España): de 8:xx a 22:xx (lo atrasado, hasta las 23:59)
POR_DIA = 5
SEPARACION = 2            # Horas mínimas entre dos vídeos del mismo canal


def ahora():
    return datetime.datetime.now(ZONA)


def horas_de_hoy(canal, fecha):
    """Siempre las mismas para un canal y un día (la semilla es la fecha), distintas cada día."""
    r = random.Random(f"{fecha}-{canal}")
    while True:
        horas = sorted(r.sample(range(PRIMERA, ULTIMA + 1), POR_DIA))
        if all(b - a >= SEPARACION for a, b in zip(horas, horas[1:])):
            return horas


def publicados_hoy(archivo, fecha):
    try:
        dia, n = open(archivo, encoding="utf-8").read().split()
        return int(n) if dia == str(fecha) else 0
    except (OSError, ValueError):
        return 0


def toca(canal, archivo):
    momento = ahora()
    if not PRIMERA <= momento.hour <= ULTIMA + 1:
        return False  # Fuera de horario no se recupera nada: mejor perder un vídeo que publicarlo a las 3:00
    debidos = sum(h <= momento.hour for h in horas_de_hoy(canal, momento.date()))
    return publicados_hoy(archivo, momento.date()) < debidos


def apuntar(archivo):
    """Suma un vídeo publicado hoy."""
    hoy = ahora().date()
    with open(archivo, "w", encoding="utf-8") as f:
        f.write(f"{hoy} {publicados_hoy(archivo, hoy) + 1}\n")


if __name__ == "__main__":
    import os
    from canales import CANALES
    archivo = lambda c: os.path.join(CANALES[c]["carpeta"], "hoy.txt")
    if sys.argv[1:] == ["ver"]:
        for c in CANALES:
            print(c, horas_de_hoy(c, ahora().date()), "publicados hoy:", publicados_hoy(archivo(c), ahora().date()))
    else:
        print(json.dumps([c for c in CANALES if toca(c, archivo(c))]))

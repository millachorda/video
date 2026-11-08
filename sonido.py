"""
Banda sonora generada por código (sin derechos de autor): ambiente oscuro con latidos y notas
sueltas, "whoosh" en cada corte y golpes graves en los momentos clave. Baja cuando habla la voz.
"""
import numpy as np
from scipy.signal import lfilter

FS = 44100
rng = np.random.default_rng()


def _t(segundos):
    return np.arange(int(segundos * FS)) / FS


def _ruido_grave(segundos, alfa):
    """Ruido filtrado con un paso bajo de un polo (alfa pequeño = más grave y suave)."""
    return lfilter([alfa], [1, alfa - 1], rng.standard_normal(int(segundos * FS)))


def ambiente(duracion):
    """Zumbido grave en La menor que respira lentamente, con un viento de fondo."""
    t = _t(duracion)
    zumbido = np.zeros_like(t)
    for frec, vol in [(55.0, 1.0), (82.41, 0.55), (110.0, 0.35), (130.81, 0.25)]:
        desafino = 1 + 0.003 * np.sin(2 * np.pi * 0.07 * t + frec)
        zumbido += vol * np.sin(2 * np.pi * frec * desafino * t)
    zumbido *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.08 * t) ** 2  # Respira cada ~6 s
    viento = _ruido_grave(duracion, 0.01)
    viento /= np.abs(viento).max() + 1e-9
    return 0.55 * zumbido / 2.2 + 0.25 * viento * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t))


def latidos(duracion, inicio=2.5, periodo=1.15):
    """Dos golpes graves (pum-pum) cada ~1,15 s, que se aceleran un poco hacia el final."""
    salida = np.zeros(int(duracion * FS))
    golpe_t = _t(0.18)
    golpe = np.sin(2 * np.pi * 52 * golpe_t) * np.exp(-golpe_t * 28)
    pos = inicio
    while pos < duracion - 0.5:
        for desfase, vol in [(0, 1.0), (0.22, 0.7)]:
            i = int((pos + desfase) * FS)
            trozo = golpe[: max(0, min(len(golpe), len(salida) - i))]
            salida[i:i + len(trozo)] += vol * trozo
        pos += periodo * (1 - 0.15 * pos / duracion)
    return salida


def notas(duracion):
    """Notas sueltas agudas tipo caja de música, cada 2-4 s, de una escala menor."""
    salida = np.zeros(int(duracion * FS))
    escala = [440.0, 523.25, 587.33, 659.25, 783.99, 880.0]
    nota_t = _t(2.5)
    pos = 1.0
    while pos < duracion - 1:
        f = rng.choice(escala)
        nota = (np.sin(2 * np.pi * f * nota_t) + 0.3 * np.sin(2 * np.pi * 2 * f * nota_t)) * np.exp(-nota_t * 2.2)
        i = int(pos * FS)
        trozo = nota[: len(salida) - i]
        salida[i:i + len(trozo)] += trozo
        pos += rng.uniform(2.0, 4.0)
    return salida / 1.3


def whoosh(segundos=0.45):
    """Ráfaga de aire que sube y baja: marca cada cambio de plano."""
    t = _t(segundos)
    ruido = _ruido_grave(segundos, 0.08)
    ruido /= np.abs(ruido).max() + 1e-9
    return ruido * np.sin(np.pi * t / segundos) ** 2


def impacto(segundos=1.6):
    """Golpe grave con caída de tono: para el final del gancho y el cierre."""
    t = _t(segundos)
    frec = 70 * np.exp(-t * 1.5) + 30
    fase = 2 * np.pi * np.cumsum(frec) / FS
    return np.sin(fase) * np.exp(-t * 2.8) + 0.3 * _ruido_grave(segundos, 0.02) * np.exp(-t * 6) * 3


def _poner(pista, efecto, segundo, vol):
    i = int(segundo * FS)
    if i >= len(pista):
        return
    trozo = efecto[: len(pista) - i]
    pista[i:i + len(trozo)] += vol * trozo


def banda_sonora(duracion, palabras, cortes, fin_gancho, inicio_cierre):
    """Devuelve un array estéreo (n, 2) listo para mezclar bajo la voz."""
    n = int(duracion * FS)
    musica = (0.9 * ambiente(duracion) + 0.55 * latidos(duracion) + 0.18 * notas(duracion))[:n]

    # Ducking: la música baja mientras suena la voz y sube en las pausas
    hablando = np.zeros(n)
    for inicio, fin, _ in palabras:
        hablando[int(inicio * FS):int((fin + 0.15) * FS)] = 1
    ventana = int(0.25 * FS)
    # Media móvil con sumas acumuladas (np.convolve con esta ventana tarda casi un minuto)
    acumulada = np.concatenate([[0], np.cumsum(hablando)])
    i = np.arange(n)
    hablando = (acumulada[np.minimum(i + ventana // 2, n)] - acumulada[np.maximum(i - ventana // 2, 0)]) / ventana
    musica *= 0.16 * (1 - 0.45 * hablando)

    efectos = np.zeros(n)
    w = whoosh()
    for c in cortes:
        _poner(efectos, w, c - 0.2, 0.10)
    imp = impacto()
    _poner(efectos, imp, 0.0, 0.5)
    _poner(efectos, imp, fin_gancho, 0.35)
    _poner(efectos, imp, inicio_cierre, 0.45)

    mezcla = musica + efectos
    # Fundido solo de salida: al empezar tiene que sonar ya, sin entrada suave
    fundido = int(0.3 * FS)
    mezcla[-fundido:] *= np.linspace(1, 0, fundido)
    mezcla = np.clip(mezcla, -0.95, 0.95)
    # Un poco de anchura estéreo desfasando 12 ms un canal
    retardo = int(0.012 * FS)
    derecha = np.concatenate([np.zeros(retardo), mezcla[:-retardo]])
    return np.stack([mezcla, derecha], axis=1).astype(np.float32)

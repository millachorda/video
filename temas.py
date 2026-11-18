"""
Detecta historias que repiten un tema ya publicado, aunque Gemini lo cuente con otras palabras
(por ejemplo "Blockbuster rechazó Netflix" y "Netflix fue rechazada por 50 millones").

1. Sospecha: la historia comparte un nombre propio poco común (marca, persona, lugar) con una publicada.
   Los nombres muy repetidos en el canal (como "Tierra" en ¿Y Si…?) no cuentan.
2. Confirmación: si hay sospecha, Gemini decide si es de verdad la misma historia (dos casos distintos
   en California no son el mismo tema). Si Gemini no responde, la historia se da por buena.
"""
import json
import os
import re
from collections import Counter

PALABRA = re.compile(r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü'’-]{2,}")
# Palabras que van en mayúscula por empezar frase o por costumbre, no por ser un nombre propio.
# Puede colarse alguna (un verbo al empezar frase): no pasa nada, Gemini confirma después.
COMUNES = {
    "El", "La", "Los", "Las", "Un", "Una", "Unos", "Unas", "En", "Con", "Sin", "Por", "Para", "De", "Del", "Al",
    "Su", "Sus", "Tu", "Tus", "Mi", "Mis", "Este", "Esta", "Estos", "Estas", "Ese", "Esa", "Eso", "Esto", "Aquel",
    "Qué", "Que", "Cómo", "Como", "Cuando", "Cuándo", "Donde", "Dónde", "Quién", "Quien", "Cuál", "Cual", "Pero",
    "Si", "No", "Sí", "Nadie", "Nunca", "Todo", "Todos", "Toda", "Todas", "Hoy", "Ayer", "Hace", "Tras",
    "Durante", "Después", "Antes", "Luego", "Así", "Ahora", "Mientras", "Aunque", "Incluso", "Solo", "Sólo",
    "Algo", "Alguien", "Nada", "Cada", "Otro", "Otra", "Otros", "Otras", "Dato", "Primero", "Segundo", "Tercero",
    "Imagina", "Sabías", "Ojo", "Pues", "Entonces", "Además", "Fue", "Era", "Es", "Son", "Hay", "Tiene", "Tenía",
    "Según", "Desde", "Hasta", "Entre", "Sobre", "Bajo", "Contra", "Muy", "Más", "Menos", "Casi", "Parte", "Shorts",
}


def nombres(texto):
    """Nombres propios del principio de la historia (donde se dice de qué va), en minúsculas."""
    return {p.lower().strip("'’-") for p in PALABRA.findall(texto[:220]) if p not in COMUNES}


def sospechosos(texto, publicados):
    """Temas ya publicados que comparten algún nombre propio poco común con esta historia."""
    if not publicados:
        return []
    vistos = [nombres(p) for p in publicados]
    frecuencia = Counter(n for conjunto in vistos for n in conjunto)
    # Un nombre que sale en más de un 20 % de los temas del canal es de fondo (Tierra, Sol…), no un tema
    limite = max(2, int(len(publicados) * 0.2))
    propios = {n for n in nombres(texto) if frecuencia[n] <= limite}
    return [p for p, conjunto in zip(publicados, vistos) if propios & conjunto]


def repetida(texto, publicados, api_key=None):
    """True si la historia cuenta el mismo tema que alguna ya publicada."""
    parecidos = sospechosos(texto, publicados)
    if not parecidos:
        return False
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return True  # Sin Gemini no se puede confirmar: mejor no arriesgarse a repetir
    try:
        from historias_ia import _pedir, MODELOS_LIGEROS
        lista = "\n".join(f"- {p[:220]}" for p in parecidos[:6])
        respuesta = _pedir(api_key, f"""¿Esta historia nueva cuenta el MISMO tema que alguna de las ya publicadas?
Es el mismo tema si trata de la misma marca, persona, caso o fenómeno principal, aunque lo cuente de otra forma
o desde otro ángulo. NO es el mismo tema si solo coinciden en un lugar, una época o un detalle secundario.

Historia nueva:
{texto[:300]}

Ya publicadas:
{lista}

Devuelve solo un objeto JSON: {{"repetido": true}} o {{"repetido": false}}.""", 90, 0.1, espera_maxima=40, intentos=1,
                           modelos=MODELOS_LIGEROS)
        return bool(json.loads(respuesta).get("repetido"))
    except Exception as e:
        print(f"Aviso: no se pudo confirmar si el tema se repite ({e}); se da por bueno.")
        return False

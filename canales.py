"""
Un mismo bot para varios canales de YouTube: cada uno con su tema, su estilo y sus archivos.

El canal se elige con la variable de entorno CANAL (por defecto, CurioMind). Para añadir un canal:
copia una entrada, crea su carpeta en canales/<id>/ y conéctalo con
    python conectar_youtube.py client_secret.json <id>
"""
import os

CANALES = {
    "curiomind": {
        "nombre": "CurioMind",
        "carpeta": ".",               # El primer canal guarda sus archivos en la raíz (como siempre)
        "secret_youtube": "YT_REFRESH_TOKEN",
        "tiktok": True,               # La cuenta de TikTok conectada es la de este canal
        "partes": None,               # None = la variable PARTES_POR_CASO (5)
        "release": "partes",          # Donde se guardan las partes hasta montar el vídeo completo
        "serie": ("Este caso real de misterio", "la investigación, las pruebas, los testigos, las teorías…",
                  "cuenta lo que se sabe hoy",
                  "Usa SOLO hechos reales y documentados de este caso; puedes añadir detalles reales conocidos, "
                  "pero no inventes nombres, fechas, cifras ni escenas. Si no hay tantos hechos, profundiza en el "
                  "contexto histórico, la investigación y las teorías publicadas."),
        "completo": {"etiqueta": "CASO COMPLETO", "titulo": "{caso} | El caso completo",
                     "intro": "Este es el caso completo. {caso}. Todas las partes, de principio a fin.",
                     "fin": ("¿TÚ QUÉ CREES?", "Comenta tu teoría y suscríbete: cada día un caso nuevo"),
                     "descripcion": "{caso}: el caso completo, con todas sus partes seguidas.\n¿Tú qué crees "
                                    "que pasó? Cuéntamelo en los comentarios y suscríbete: cada día un caso nuevo.",
                     "hashtags": "#misterio #casosreales #sinresolver #enigma #casocompleto",
                     "etiquetas": ["Misterio", "CasosReales", "SinResolver", "Enigma", "CasoCompleto"]},
        "etiqueta": "CASO SIN RESOLVER",
        "color_etiqueta": (220, 30, 45),
        "musica": "misterio",
        "oscuro": True,
        "categoria": "24",            # Entretenimiento
        "tema": "historia de misterio real",
        "ejemplos_gancho": "'Desaparecieron 39 personas en pleno vuelo', "
                           "'Encontraron su diario escrito por otra persona'",
        "ganchos_genericos": ["Este caso sigue sin resolverse.", "Nadie ha conseguido explicar lo que pasó.",
                              "Lo que ocurrió aquí sigue siendo un misterio."],
        "estilo_busquedas": "atmosféricos y oscuros",
        "busquedas_genericas": ["dark forest fog", "abandoned house", "night sky stars", "old documents",
                                "foggy road night", "candle dark", "dark corridor", "storm clouds"],
        "palabras_clave": ["NADIE", "NUNCA", "JAMÁS", "MUERTE", "MUERTOS", "ASESINATO", "DESAPARECIÓ",
                           "DESAPARECIERON", "DESAPARICIÓN", "SANGRE", "CADÁVER", "MISTERIO", "INEXPLICABLE",
                           "SECRETO", "EXTRAÑO", "TERROR", "SEÑAL", "NINGUNA", "NINGÚN"],
        "cierre": [("¿TÚ QUÉ CREES?", True), ("COMENTA TU TEORÍA", False), ("Y SÍGUEME PARA MÁS", False)],
        "hashtags_youtube": "#misterio #casosreales #sinresolver #enigma #shorts",
        "hashtags_tiktok": "#misterio #casosreales #sinresolver #parati #fyp",
        "etiquetas": ["Shorts", "Misterio", "CasosReales", "SinResolver", "Enigma"],
        "encargo_historias": """historias para vídeos cortos de un canal de misterios reales sin resolver.

Reglas:
- Solo casos REALES, muy conocidos y bien documentados (desapariciones, señales, crímenes sin resolver, enigmas históricos). No inventes casos, nombres, fechas ni cifras; si dudas de un dato, no lo incluyas.
- La primera frase tiene que impactar por sí sola (un dato inquietante, no una introducción), cuenta los hechos clave y termina con una pregunta abierta sobre el misterio.""",
    },
    "ysi": {
        "nombre": "¿Y Si…?",
        "carpeta": "canales/ysi",
        "secret_youtube": "YT_REFRESH_TOKEN_YSI",
        "tiktok": False,
        "partes": None,
        "release": "partes-ysi",
        "serie": ("Este escenario hipotético", "las consecuencias siguientes en orden (segundos, horas, días, "
                  "años…), cada vez más extremas", "cuenta cómo quedaría todo al final",
                  "Usa ciencia real: cifras y hechos científicos conocidos; si algo es incierto, dilo así. "
                  "No inventes datos."),
        "completo": {"etiqueta": "COMPLETO", "titulo": "{caso} | Todo lo que pasaría",
                     "intro": "Esto es todo lo que pasaría. {caso}. Todas las partes seguidas.",
                     "fin": ("¿TÚ QUÉ HARÍAS?", "Coméntalo y suscríbete: cada día una pregunta nueva"),
                     "descripcion": "{caso}: todas las partes seguidas, explicado con ciencia real.\n"
                                    "¿Tú qué harías? Cuéntamelo en los comentarios y suscríbete.",
                     "hashtags": "#quepasariasi #ciencia #curiosidades #ysi",
                     "etiquetas": ["QuePasariaSi", "Ciencia", "Curiosidades", "Hipotetico"]},
        "etiqueta": "¿QUÉ PASARÍA SI…?",
        "color_etiqueta": (30, 110, 230),
        "musica": "epica",
        "oscuro": False,
        "categoria": "28",            # Ciencia y tecnología
        "tema": "situación hipotética explicada con ciencia real",
        "ejemplos_gancho": "'¿Y si la Luna desapareciera esta noche?', "
                           "'Si dejaras de dormir, en 11 días pasaría esto'",
        "ganchos_genericos": ["¿Y si esto pasara mañana?", "Esto es lo que pasaría de verdad.",
                              "La ciencia tiene una respuesta inquietante."],
        "estilo_busquedas": "espectaculares (espacio, naturaleza, ciudades, ciencia)",
        "busquedas_genericas": ["earth from space", "city timelapse night", "ocean waves aerial",
                                "galaxy stars", "lightning storm", "volcano eruption", "laboratory science",
                                "sunrise planet"],
        "palabras_clave": ["NADIE", "NUNCA", "TODOS", "PLANETA", "TIERRA", "SOL", "LUNA", "DESAPARECERÍA",
                           "MORIRÍAMOS", "SEGUNDOS", "MINUTOS", "HORAS", "DÍAS", "AÑOS", "MILLONES",
                           "IMPOSIBLE", "CATÁSTROFE"],
        "cierre": [("¿TÚ QUÉ HARÍAS?", True), ("COMÉNTALO", False), ("Y SÍGUEME PARA MÁS", False)],
        "hashtags_youtube": "#quepasariasi #ciencia #curiosidades #ysi #shorts",
        "hashtags_tiktok": "#quepasariasi #ciencia #curiosidades #parati #fyp",
        "etiquetas": ["Shorts", "QuePasariaSi", "Ciencia", "Curiosidades", "Hipotetico"],
        "encargo_historias": """guiones para vídeos cortos de un canal de "¿Qué pasaría si…?" (escenarios hipotéticos explicados con ciencia).

Reglas:
- Cada guion plantea UNA situación hipotética llamativa (la Tierra deja de girar, un humano en Marte sin traje, desaparecen las abejas, nunca duermes, cae un rayo en el mar a tu lado…) y explica paso a paso lo que pasaría según la ciencia real. No inventes datos: usa cifras y hechos científicos conocidos; si algo es incierto, dilo así.
- La primera frase es la pregunta "¿Qué pasaría si…?" o un dato que la haga irresistible, después una progresión que vaya a más (en segundos, en horas, en días…) y termina con una pregunta al espectador.""",
    },
    "decero": {
        "nombre": "De Cero a Millón",
        "carpeta": "canales/decero",
        "secret_youtube": "YT_REFRESH_TOKEN_DECERO",
        "tiktok": False,
        "partes": None,
        "release": "partes-decero",
        "serie": ("Esta historia real de emprendimiento", "los primeros pasos, los fracasos, las decisiones "
                  "clave, cómo creció…", "cuenta dónde está hoy y qué se puede aprender",
                  "Usa SOLO hechos reales y documentados; no inventes nombres, fechas, cifras ni escenas. "
                  "Sin consejos de inversión."),
        "completo": {"etiqueta": "HISTORIA COMPLETA", "titulo": "{caso} | La historia completa",
                     "intro": "Esta es la historia completa. {caso}. Todas las partes, de principio a fin.",
                     "fin": ("¿TÚ LO HABRÍAS HECHO?", "Coméntalo y suscríbete: cada día una historia nueva"),
                     "descripcion": "{caso}: la historia completa, con todas sus partes seguidas.\n"
                                    "¿Tú lo habrías hecho? Cuéntamelo en los comentarios y suscríbete.",
                     "hashtags": "#emprender #emprendedores #negocios #historiasreales",
                     "etiquetas": ["Emprender", "Emprendedores", "Negocios", "HistoriasReales"]},
        "etiqueta": "HISTORIA REAL",
        "color_etiqueta": (20, 160, 80),
        "musica": "epica",
        "oscuro": False,
        "categoria": "27",            # Educación
        "tema": "historia real de un emprendedor o una empresa",
        "ejemplos_gancho": "'Le despidieron y creó una empresa de 1.000 millones', "
                           "'Empezó vendiendo desde un garaje'",
        "ganchos_genericos": ["Empezó sin nada.", "Todos le dijeron que era imposible.",
                              "Así nació una empresa gigante."],
        "estilo_busquedas": "de negocios, ciudad, trabajo y éxito",
        "busquedas_genericas": ["city skyline", "office work night", "money counting", "startup team",
                                "factory production", "stock market screen", "laptop typing", "shop opening"],
        "palabras_clave": ["NADIE", "NUNCA", "TODOS", "MILLONES", "MILLÓN", "DÓLARES", "EUROS", "QUIEBRA",
                           "FRACASO", "ÉXITO", "IMPOSIBLE", "GARAJE", "DESPEDIDO", "PRIMERA", "IMPERIO"],
        "cierre": [("¿TÚ LO HABRÍAS HECHO?", True), ("COMÉNTALO", False), ("Y SÍGUEME PARA MÁS", False)],
        "hashtags_youtube": "#emprender #emprendedores #negocios #historiasreales #shorts",
        "hashtags_tiktok": "#emprender #emprendedores #negocios #parati #fyp",
        "etiquetas": ["Shorts", "Emprender", "Emprendedores", "Negocios", "HistoriasReales"],
        "encargo_historias": """historias para vídeos cortos de un canal sobre emprendedores y empresas que empezaron desde cero.

Reglas:
- Solo historias REALES y bien documentadas de emprendedores o empresas conocidas (cómo empezaron, el momento en que casi lo pierden todo, la decisión clave, cómo crecieron). No inventes nombres, fechas ni cifras; si dudas de un dato, no lo incluyas.
- Cuenta la historia, no des consejos de inversión ni prometas dinero fácil.
- La primera frase tiene que impactar por sí sola (un contraste, una cifra, un fracaso), cuenta los momentos clave y termina con una pregunta al espectador.""",
    },
    "relatos": {
        "nombre": "Relatos de Medianoche",
        "carpeta": "canales/relatos",
        "secret_youtube": "YT_REFRESH_TOKEN_RELATOS",
        "tiktok": False,
        "partes": None,
        "release": "partes-relatos",
        "aviso": "Relato de ficción: personajes y hechos inventados.",
        "serie": ("Este relato de terror y suspense de ficción", "la tensión que crece, pistas inquietantes y "
                  "giros", "revela el giro final",
                  "Es ficción original: inventa personajes y escenas, pero no uses nombres de personas reales "
                  "ni presentes hechos reales como ciertos. Nada de violencia explícita ni gore: el miedo viene "
                  "de lo que se insinúa."),
        "completo": {"etiqueta": "RELATO COMPLETO", "titulo": "{caso} | Relato completo",
                     "intro": "Este es el relato completo. {caso}. Apaga la luz y escucha hasta el final.",
                     "fin": ("¿QUÉ HABRÍAS HECHO TÚ?", "Coméntalo y suscríbete: cada noche un relato nuevo"),
                     "descripcion": "{caso}: el relato completo, con todas sus partes seguidas.\n"
                                    "Relato de ficción: personajes y hechos inventados.",
                     "hashtags": "#relatos #historiasdeterror #creepypasta #ficcion",
                     "etiquetas": ["Relatos", "HistoriasDeTerror", "Creepypasta", "Ficcion"]},
        "etiqueta": "RELATO DE FICCIÓN",
        "color_etiqueta": (120, 40, 200),
        "musica": "misterio",
        "oscuro": True,
        "categoria": "24",
        "tema": "relato corto de terror y suspense de ficción",
        "ejemplos_gancho": "'Mi vecino lleva tres días sin parpadear', "
                           "'Las 3:33 y alguien llama desde mi móvil'",
        "ganchos_genericos": ["Esto empezó una noche normal.", "Nunca debí abrir esa puerta.",
                              "Escucha esto antes de dormir."],
        "estilo_busquedas": "nocturnos, oscuros e inquietantes",
        "busquedas_genericas": ["dark hallway night", "old house night", "flickering light", "foggy forest night",
                                "full moon clouds", "empty street night", "door opening dark", "rain window night"],
        "palabras_clave": ["NADIE", "NUNCA", "JAMÁS", "MUERTO", "SANGRE", "OSCURIDAD", "PUERTA", "SOMBRA", "GRITO",
                           "MEDIANOCHE", "SOLO", "SOLA", "DETRÁS", "SILENCIO", "ALGUIEN"],
        "cierre": [("¿QUÉ HABRÍAS HECHO TÚ?", True), ("COMÉNTALO", False), ("Y SÍGUEME PARA MÁS", False)],
        "hashtags_youtube": "#relatos #historiasdeterror #creepypasta #ficcion #shorts",
        "hashtags_tiktok": "#relatos #historiasdeterror #creepypasta #parati #fyp",
        "etiquetas": ["Shorts", "Relatos", "HistoriasDeTerror", "Creepypasta", "Ficcion"],
        "encargo_historias": """relatos cortos de ficción de terror y suspense para un canal de historias inventadas.

Reglas:
- Ficción original: inventa personajes y situaciones (en primera o tercera persona). No uses nombres de personas reales ni presentes hechos reales como si fueran ciertos.
- Miedo psicológico y suspense (algo que no encaja, una presencia, una regla que no se debe romper…), sin violencia explícita ni gore.
- La primera frase tiene que inquietar por sí sola y el final deja un giro o una pregunta inquietante.""",
    },
    "datos": {
        "nombre": "Datos Imposibles",
        "carpeta": "canales/datos",
        "secret_youtube": "YT_REFRESH_TOKEN_DATOS",
        "tiktok": False,
        "partes": None,
        "release": "partes-datos",
        "serie": ("Este tema de curiosidades reales", "datos cada vez más sorprendentes sobre el mismo tema",
                  "remata con el dato más increíble de todos",
                  "Solo datos REALES y verificables (ciencia, historia, naturaleza, cuerpo humano…); no inventes "
                  "cifras: si dudas de un dato, no lo uses."),
        "completo": {"etiqueta": "COMPLETO", "titulo": "{caso} | Todos los datos",
                     "intro": "Aquí tienes todos los datos seguidos. {caso}.",
                     "fin": ("¿CUÁL NO SABÍAS?", "Coméntalo y suscríbete: cada día datos nuevos"),
                     "descripcion": "{caso}: todas las partes seguidas.\n¿Cuál no sabías? Cuéntamelo en los "
                                    "comentarios y suscríbete.",
                     "hashtags": "#datoscuriosos #curiosidades #sabiasque #datos",
                     "etiquetas": ["DatosCuriosos", "Curiosidades", "SabiasQue", "Datos"]},
        "etiqueta": "DATO REAL",
        "color_etiqueta": (240, 120, 0),
        "musica": "epica",
        "oscuro": False,
        "categoria": "27",
        "tema": "curiosidad real sorprendente",
        "ejemplos_gancho": "'Tu cuerpo brilla, pero no lo puedes ver', "
                           "'Hay más árboles en la Tierra que estrellas en la galaxia'",
        "ganchos_genericos": ["Esto parece mentira, pero es real.", "Seguro que no sabías esto.",
                              "La ciencia lo confirma."],
        "estilo_busquedas": "llamativos y coloridos (naturaleza, ciencia, cuerpo humano, espacio, animales)",
        "busquedas_genericas": ["colorful nature macro", "human eye closeup", "ocean animals", "galaxy stars",
                                "microscope cells", "ancient ruins aerial", "wild animals", "city timelapse"],
        "palabras_clave": ["NADIE", "NUNCA", "TODOS", "MILLONES", "MILES", "AÑOS", "REAL", "IMPOSIBLE", "MÁS",
                           "CUERPO", "PLANETA", "CEREBRO", "SEGUNDOS", "VECES"],
        "cierre": [("¿CUÁL NO SABÍAS?", True), ("COMÉNTALO", False), ("Y SÍGUEME PARA MÁS", False)],
        "hashtags_youtube": "#datoscuriosos #curiosidades #sabiasque #datos #shorts",
        "hashtags_tiktok": "#datoscuriosos #curiosidades #sabiasque #parati #fyp",
        "etiquetas": ["Shorts", "DatosCuriosos", "Curiosidades", "SabiasQue", "Datos"],
        "encargo_historias": """guiones para vídeos cortos de un canal de datos curiosos reales que parecen imposibles.

Reglas:
- Cada guion trata UN tema (el cuerpo humano, el pulpo, las pirámides, el sueño, la Luna…) y encadena 4 o 5 datos REALES y verificables sobre él, cada uno más sorprendente que el anterior. No inventes cifras: si dudas de un dato, no lo uses.
- La primera frase es el dato más chocante o una pregunta irresistible y termina con una pregunta al espectador.""",
    },
}

ID = os.environ.get("CANAL") or "curiomind"
if ID not in CANALES:
    raise SystemExit(f"Canal desconocido: {ID}. Opciones: {', '.join(CANALES)}")
ACTUAL = CANALES[ID]


def ruta(archivo):
    """Ruta de un archivo de estado (contador, historias…) del canal actual."""
    os.makedirs(ACTUAL["carpeta"], exist_ok=True)
    return os.path.join(ACTUAL["carpeta"], archivo)

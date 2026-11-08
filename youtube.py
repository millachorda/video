"""Subida a YouTube con las credenciales guardadas como secrets (las crea conectar_youtube.py)."""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")


def configurado():
    return bool(YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN)


def _cliente():
    credenciales = Credentials(
        None, refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=credenciales, cache_discovery=False)


def subir(archivo, titulo, descripcion, etiquetas, short=True):
    """Sube el vídeo en público y devuelve (id, enlace)."""
    youtube = _cliente()
    cuerpo = {
        "snippet": {
            "title": titulo[:100],
            "description": descripcion[:5000],
            "tags": etiquetas,
            "categoryId": "24",  # Entretenimiento
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # Voz generada por IA
        },
    }
    peticion = youtube.videos().insert(
        part="snippet,status", body=cuerpo,
        media_body=MediaFileUpload(archivo, mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    respuesta = None
    while respuesta is None:
        _, respuesta = peticion.next_chunk()
    vid = respuesta["id"]
    return vid, (f"https://youtube.com/shorts/{vid}" if short else f"https://youtu.be/{vid}")


def poner_miniatura(video_id, imagen):
    """Miniatura personalizada (solo vídeos largos; requiere el canal verificado por teléfono)."""
    _cliente().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(imagen, mimetype="image/png")).execute()

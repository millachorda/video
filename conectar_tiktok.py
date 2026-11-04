"""
Conecta el bot con tu cuenta de TikTok (se ejecuta una sola vez, en tu ordenador).

Uso:
    python conectar_tiktok.py

Pide el Client key y el Client secret de tu app de developers.tiktok.com,
abre el navegador para que des permiso a tu cuenta y guarda las credenciales
directamente como secrets del repositorio (TIKTOK_CLIENT_KEY,
TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN), sin mostrarlas por pantalla.

En la app de TikTok hay que registrar esta Redirect URI: http://localhost:8765/callback/
"""
import getpass
import hashlib
import http.server
import secrets
import shutil
import subprocess
import urllib.parse
import webbrowser

import requests

REPO = "millachorda/video"
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
PUERTO = 8765
REDIRECT_URI = f"http://localhost:{PUERTO}/callback/"

client_key = input("Client key: ").strip()
client_secret = getpass.getpass("Client secret (no se verá al pegarlo): ").strip()

# PKCE de TikTok para apps de escritorio: el challenge es el SHA256 en hexadecimal
verificador = secrets.token_urlsafe(48)
estado = secrets.token_urlsafe(16)
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": client_key,
    "scope": "user.info.basic,video.publish",
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "state": estado,
    "code_challenge": hashlib.sha256(verificador.encode()).hexdigest(),
    "code_challenge_method": "S256",
})

respuesta = {}


class Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        respuesta.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Listo, ya puedes cerrar esta pestaña.".encode())

    def log_message(self, *args):
        pass


print("Abriendo TikTok en el navegador para que des permiso...")
webbrowser.open(url)
http.server.HTTPServer(("localhost", PUERTO), Callback).handle_request()

if respuesta.get("state", [None])[0] != estado or "code" not in respuesta:
    raise SystemExit(f"TikTok no devolvió el permiso: {respuesta}")

token = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
    "client_key": client_key, "client_secret": client_secret,
    "code": respuesta["code"][0], "grant_type": "authorization_code",
    "redirect_uri": REDIRECT_URI, "code_verifier": verificador,
}).json()
if "refresh_token" not in token:
    raise SystemExit(f"No se pudo obtener el token de TikTok: {token}")

for nombre, valor in [("TIKTOK_CLIENT_KEY", client_key),
                      ("TIKTOK_CLIENT_SECRET", client_secret),
                      ("TIKTOK_REFRESH_TOKEN", token["refresh_token"])]:
    subprocess.run([GH, "secret", "set", nombre, "-R", REPO], input=valor, text=True, check=True)

print("Listo: TikTok conectado. El bot publicará los vídeos automáticamente.")

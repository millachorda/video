"""
Conecta el bot con tu canal de YouTube (se ejecuta una sola vez, en tu ordenador).

Uso:
    pip install google-auth-oauthlib
    python conectar_youtube.py ruta/al/client_secret.json

Abre el navegador para que des permiso a tu canal y guarda las credenciales
directamente como secrets del repositorio (YT_CLIENT_ID, YT_CLIENT_SECRET,
YT_REFRESH_TOKEN), sin mostrarlas por pantalla.
"""
import json
import shutil
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

REPO = "millachorda/video"
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"

if len(sys.argv) != 2:
    print(__doc__)
    sys.exit(1)

with open(sys.argv[1], encoding="utf-8") as f:
    cliente = json.load(f)["installed"]

flow = InstalledAppFlow.from_client_secrets_file(
    sys.argv[1], scopes=["https://www.googleapis.com/auth/youtube.upload"])
credenciales = flow.run_local_server(port=0, access_type="offline", prompt="consent")

for nombre, valor in [("YT_CLIENT_ID", cliente["client_id"]),
                      ("YT_CLIENT_SECRET", cliente["client_secret"]),
                      ("YT_REFRESH_TOKEN", credenciales.refresh_token)]:
    subprocess.run([GH, "secret", "set", nombre, "-R", REPO], input=valor, text=True, check=True)

print("Listo: YouTube conectado. El bot subirá los Shorts automáticamente.")

"""
App local para revisar y publicar en TikTok los vídeos pendientes del bot.

Uso:
    python publicar_tiktok.py

Abre http://localhost:8765 en el navegador. Inicias sesión con TikTok, ves cada
vídeo pendiente (releases "tiktok-ep-N" de GitHub), eliges quién puede verlo y
las opciones, y lo publicas tú con un clic. Al terminar se borra la release.

Client key/secret: variables TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET o el archivo
%APPDATA%\\BotVideos\\tiktok.json (se piden una vez y se guardan ahí, junto a los tokens).
"""
import getpass
import hashlib
import html
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

REPO = "millachorda/video"
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
PUERTO = 8765
REDIRECT_URI = f"http://localhost:{PUERTO}/callback/"
API = "https://open.tiktokapis.com"
CARPETA = Path(os.environ.get("APPDATA", Path.home())) / "BotVideos"
CONFIG = CARPETA / "tiktok.json"
VIDEOS = CARPETA / "videos"
TAG_OK = re.compile(r"^tiktok-ep-\d+$")
PRIVACIDAD = {"PUBLIC_TO_EVERYONE": "Todo el mundo", "MUTUAL_FOLLOW_FRIENDS": "Amigos",
              "FOLLOWER_OF_CREATOR": "Seguidores", "SELF_ONLY": "Solo yo"}
URL_MUSICA = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
URL_MARCA = "https://www.tiktok.com/legal/page/global/bc-policy/en"
e = html.escape
sesion = {}   # verificador y estado PKCE del login en curso
estados = {}  # tag -> {"texto", "fin", "ok"} de cada publicación


# --- Configuración y tokens -------------------------------------------------

def leer_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(cfg):
    CARPETA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def credenciales():
    cfg = leer_config()
    key = os.environ.get("TIKTOK_CLIENT_KEY") or cfg.get("client_key")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET") or cfg.get("client_secret")
    if not (key and secret):
        key = input("Client key: ").strip()
        secret = getpass.getpass("Client secret (no se verá al pegarlo): ").strip()
        cfg.update(client_key=key, client_secret=secret)
        guardar_config(cfg)
    return key, secret


CLIENT_KEY, CLIENT_SECRET = credenciales()


def pedir_token(**datos):
    r = requests.post(f"{API}/v2/oauth/token/", timeout=30, data={
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, **datos}).json()
    if "access_token" not in r:
        raise RuntimeError(f"TikTok no dio el token: {r.get('error')} {r.get('error_description', '')}")
    cfg = leer_config()
    cfg["tokens"] = {"access_token": r["access_token"], "refresh_token": r["refresh_token"],
                     "expira": time.time() + r.get("expires_in", 0) - 60}
    guardar_config(cfg)
    return r["access_token"]


def token():
    """Access token válido (lo renueva si caducó) o None si no hay sesión."""
    t = leer_config().get("tokens")
    if not t:
        return None
    if time.time() < t["expira"]:
        return t["access_token"]
    try:
        return pedir_token(grant_type="refresh_token", refresh_token=t["refresh_token"])
    except Exception:
        return None


def tiktok(ruta, cuerpo):
    """POST a la API de TikTok; devuelve data o lanza RuntimeError con error.code/message."""
    r = requests.post(API + ruta, json=cuerpo, timeout=30, headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json; charset=UTF-8"})
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"Respuesta inválida de TikTok (HTTP {r.status_code})")
    err = j.get("error", {})
    if err.get("code", "ok") != "ok":
        raise RuntimeError(f"{err.get('code')}: {err.get('message', '')}")
    return j.get("data", {})


# --- Vídeos pendientes (releases de GitHub) ---------------------------------

def gh(*args):
    return subprocess.run([GH, *args, "-R", REPO], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def pendientes():
    lista = json.loads(gh("release", "list", "--json", "tagName,name", "--limit", "50"))
    videos = []
    for rel in lista:
        tag = rel["tagName"]
        if not TAG_OK.match(tag):
            continue
        info = json.loads(gh("release", "view", tag, "--json", "name,body"))
        carpeta = VIDEOS / tag
        if not list(carpeta.glob("*.mp4")):
            carpeta.mkdir(parents=True, exist_ok=True)
            gh("release", "download", tag, "-D", str(carpeta), "-p", "*.mp4", "--clobber")
        mp4 = next(iter(sorted(carpeta.glob("*.mp4"))), None)
        if mp4:
            videos.append({"tag": tag, "titulo": info["name"] or tag,
                           "caption": info["body"] or "", "mp4": mp4, "dur": duracion(mp4)})
    return sorted(videos, key=lambda v: int(v["tag"].rsplit("-", 1)[1]))


def archivo(tag):
    return next(iter(sorted((VIDEOS / tag).glob("*.mp4"))), None) if TAG_OK.match(tag) else None


def duracion(mp4):
    """Segundos del vídeo con ffprobe si está instalado; None si no se puede medir."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        return float(subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", str(mp4)], capture_output=True,
                                    text=True, check=True).stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


# --- Publicación ------------------------------------------------------------

def publicar(tag, mp4, post_info):
    est = estados[tag]
    try:
        tam = mp4.stat().st_size
        est["texto"] = "Iniciando publicación…"
        data = tiktok("/v2/post/publish/video/init/", {"post_info": post_info, "source_info": {
            "source": "FILE_UPLOAD", "video_size": tam, "chunk_size": tam, "total_chunk_count": 1}})
        est["texto"] = "Subiendo el vídeo…"
        with open(mp4, "rb") as f:
            r = requests.put(data["upload_url"], data=f, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(tam),
                "Content-Range": f"bytes 0-{tam - 1}/{tam}"})
        if r.status_code >= 300:
            raise RuntimeError(f"Fallo al subir el vídeo (HTTP {r.status_code}): {r.text[:200]}")
        for _ in range(40):  # ~2 minutos
            time.sleep(3)
            st = tiktok("/v2/post/publish/status/fetch/", {"publish_id": data["publish_id"]})
            estado = st.get("status", "?")
            if estado == "FAILED":
                raise RuntimeError(f"TikTok rechazó la publicación: {st.get('fail_reason', 'sin motivo')}")
            if estado == "PUBLISH_COMPLETE":
                gh("release", "delete", tag, "--yes", "--cleanup-tag")
                shutil.rmtree(VIDEOS / tag, ignore_errors=True)
                est.update(texto="¡Publicado! Puede tardar unos minutos en aparecer en tu perfil.",
                           fin=True, ok=True)
                return
            est["texto"] = f"Estado: {estado}…"
        est.update(texto="TikTok sigue procesando el vídeo. Revisa tu perfil en unos minutos.", fin=True)
    except Exception as ex:
        est.update(texto=f"Error: {ex}", fin=True)


# --- HTML -------------------------------------------------------------------

CSS = """body{font-family:system-ui,sans-serif;background:#f4f4f6;color:#161823;margin:0}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:1.3em}
.card{background:#fff;border-radius:12px;padding:16px;margin:16px 0;box-shadow:0 1px 3px #0002}
.yo{display:flex;align-items:center;gap:12px}.yo img{width:48px;height:48px;border-radius:50%}
.yo span{flex:1}video{width:100%;max-height:60vh;background:#000;border-radius:8px}
textarea,select{width:100%;box-sizing:border-box;font:inherit;padding:8px;margin:6px 0 12px}
label{display:block;margin:6px 0}label.off{color:#aaa}.marcas{margin-left:24px}
.nota{color:#666;font-size:.9em}.aviso{color:#a15c00}.err{color:#c0002a}.ok{color:#0a7d2c}
button,.btn{background:#fe2c55;color:#fff;border:0;border-radius:6px;padding:10px 20px;
font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button:disabled{background:#ccc;cursor:not-allowed}a{color:#fe2c55}"""

JS = """function upd(f){
const com=f.comercial.checked,org=f.organic.checked,bc=f.branded.checked,mb=com&&bc;
f.querySelector('.marcas').hidden=!com;
const so=f.privacy.querySelector('option[value=SELF_ONLY]');
if(so){so.disabled=mb;if(mb&&f.privacy.value=='SELF_ONLY')f.privacy.value='';}
f.querySelector('.aviso').textContent=mb?"Tu foto/vídeo se etiquetará como 'Colaboración pagada'."
:(com&&org?"Tu foto/vídeo se etiquetará como 'Contenido promocional'.":'');
f.querySelectorAll('.solo-bc').forEach(x=>x.hidden=!mb);
const falta=com&&!org&&!bc;f.querySelector('.falta').hidden=!falta;
f.pub.disabled=!f.privacy.value||falta||f.dataset.bloqueado=='1';}
document.querySelectorAll('form.post').forEach(f=>{['input','change'].forEach(ev=>
f.addEventListener(ev,()=>upd(f)));upd(f);f.addEventListener('submit',()=>{
f.pub.disabled=true;f.pub.textContent='Publicando…';});});
const st=document.getElementById('estado');
if(st){const tick=()=>fetch('/estado?tag='+encodeURIComponent(st.dataset.tag)).then(r=>r.json())
.then(j=>{st.textContent=j.texto;st.className=j.fin?(j.ok?'ok':'err'):'';if(!j.fin)setTimeout(tick,3000);});tick();}"""


def pagina(cuerpo):
    return (f"<!doctype html><html lang=es><head><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>Publicar en TikTok</title>"
            f"<style>{CSS}</style></head><body><main>{cuerpo}</main><script>{JS}</script></body></html>")


def form_video(v, info, bloqueado):
    tag, maxd, dur = v["tag"], info.get("max_video_post_duration_sec"), v["dur"]
    largo = bool(maxd and dur and dur > maxd)
    opciones = "".join(f"<option value='{e(o)}'>{e(PRIVACIDAD.get(o, o))}</option>"
                       for o in info.get("privacy_level_options", []))

    def casilla(nombre, texto, clave):
        off = info.get(clave)
        return (f"<label class='{'off' if off else ''}'><input type=checkbox name={nombre}"
                f"{' disabled' if off else ''}> {texto}</label>")

    dur_txt = f"{dur:.0f} s" if dur else "sin medir"
    return f"""<div class=card><h2>{e(v['titulo'])}</h2>
<video controls preload=metadata src='/video?tag={e(tag)}'></video>
<p class=nota>Duración: {dur_txt}{f' · máximo permitido: {maxd} s' if maxd else ''}</p>
{'<p class=err>El vídeo supera la duración máxima que permite tu cuenta.</p>' if largo else ''}
<form class=post method=post action=/publicar data-bloqueado='{1 if bloqueado or largo else 0}'>
<input type=hidden name=tag value='{e(tag)}'>
<label>Título / descripción</label><textarea name=caption rows=4 maxlength=2200>{e(v['caption'])}</textarea>
<label>¿Quién puede ver este vídeo?</label><select name=privacy required>
<option value='' selected disabled>Elige quién puede verlo</option>{opciones}</select>
<p class='nota solo-bc' hidden>La visibilidad del contenido de marca no puede ser privada.</p>
{casilla('comentarios', 'Permitir comentarios', 'comment_disabled')}
{casilla('duo', 'Permitir Dúo', 'duet_disabled')}
{casilla('stitch', 'Permitir Stitch', 'stitch_disabled')}
<label><input type=checkbox name=comercial> Divulgación de contenido comercial</label>
<div class=marcas hidden><p class=nota>Indica si este contenido promociona a ti, a un tercero o a ambos.</p>
<label><input type=checkbox name=organic> Tu marca <span class=nota>(promocionas tu propio producto o negocio)</span></label>
<label><input type=checkbox name=branded> Contenido de marca <span class=nota>(promocionas a un tercero)</span></label>
<p class='err falta' hidden>Debes indicar si tu contenido promociona a ti, a un tercero o a ambos.</p></div>
<p class=aviso></p><p class=nota>Se marcará como contenido generado con IA.</p>
<p class=nota>Al publicar, aceptas <span class=solo-bc hidden>la <a href='{URL_MARCA}' target=_blank>Política
de contenido de marca</a> y </span>la <a href='{URL_MUSICA}' target=_blank>Declaración de uso de música</a> de TikTok.</p>
<button name=pub disabled>Publicar</button>
<p class=nota>Tras publicar, el vídeo puede tardar unos minutos en aparecer en tu perfil.</p></form></div>"""


def principal(publicando=None):
    try:
        info, aviso = tiktok("/v2/post/publish/creator_info/query/", {}), ""
    except Exception as ex:
        info, aviso = {}, f"No puedes publicar ahora mismo: {ex}"
    nombre = info.get("creator_nickname") or info.get("creator_username") or "tu cuenta"
    avatar = f"<img src='{e(info['creator_avatar_url'])}' alt=''>" if info.get("creator_avatar_url") else ""
    usuario = f" <span class=nota>@{e(info['creator_username'])}</span>" if info.get("creator_username") else ""
    html_ = (f"<h1>Publicar en TikTok</h1><div class='card yo'>{avatar}<span><b>{e(nombre)}</b>{usuario}"
             f"</span><a href=/logout>Cerrar sesión</a></div>")
    if aviso:
        html_ += f"<p class='card err'>{e(aviso)}</p>"
    if publicando and TAG_OK.match(publicando):
        html_ += f"<p class=card><b>{e(publicando)}:</b> <span id=estado data-tag='{e(publicando)}'>…</span></p>"
    try:
        videos = pendientes()
    except Exception as ex:
        return pagina(html_ + f"<p class='card err'>No se pudieron leer los vídeos de GitHub: {e(str(ex))}</p>")
    if not videos:
        html_ += "<p class=card>No hay vídeos pendientes.</p>"
    for v in videos:
        html_ += form_video(v, info, bool(aviso) or not estados.get(v["tag"], {"fin": True})["fin"])
    return pagina(html_)


# --- Servidor ---------------------------------------------------------------

class App(http.server.BaseHTTPRequestHandler):
    def responder(self, cuerpo, tipo="text/html; charset=utf-8", codigo=200):
        datos = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def ir(self, destino):
        self.send_response(303)
        self.send_header("Location", destino)
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/login":
            sesion.update(verificador=secrets.token_urlsafe(48), estado=secrets.token_urlsafe(16))
            return self.ir("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
                "client_key": CLIENT_KEY, "scope": "user.info.basic,video.publish,video.upload",
                "response_type": "code", "redirect_uri": REDIRECT_URI, "state": sesion["estado"],
                # PKCE de TikTok para escritorio: SHA256 en hexadecimal
                "code_challenge": hashlib.sha256(sesion["verificador"].encode()).hexdigest(),
                "code_challenge_method": "S256"}))
        if url.path.startswith("/callback"):
            if not q.get("code") or q.get("state") != sesion.pop("estado", None):
                return self.responder(pagina(f"<p class='card err'>TikTok no dio permiso: "
                                             f"{e(q.get('error_description') or q.get('error') or 'estado inválido')}"
                                             f"</p><a class=btn href=/login>Reintentar</a>"))
            try:
                pedir_token(grant_type="authorization_code", code=q["code"],
                            redirect_uri=REDIRECT_URI, code_verifier=sesion.pop("verificador", ""))
            except Exception as ex:
                return self.responder(pagina(f"<p class='card err'>{e(str(ex))}</p>"))
            return self.ir("/")
        if url.path == "/logout":
            cfg = leer_config()
            cfg.pop("tokens", None)
            guardar_config(cfg)
            return self.ir("/")
        if url.path == "/estado":
            return self.responder(json.dumps(estados.get(q.get("tag", ""), {"texto": "…", "fin": False})),
                                  "application/json")
        if url.path == "/video":
            return self.video(archivo(q.get("tag", "")))
        if url.path != "/":
            return self.responder("No encontrado", "text/plain; charset=utf-8", 404)
        if not token():
            return self.responder(pagina("<h1>Publicar en TikTok</h1><div class=card><p>Inicia sesión con "
                                         "tu cuenta de TikTok para revisar y publicar los vídeos pendientes."
                                         "</p><a class=btn href=/login>Continuar con TikTok</a></div>"))
        self.responder(principal(q.get("publicando")))

    def video(self, mp4):
        """Sirve el mp4 con soporte de Range para que el reproductor pueda avanzar."""
        if not mp4:
            return self.responder("No encontrado", "text/plain; charset=utf-8", 404)
        tam = mp4.stat().st_size
        ini, fin = 0, tam - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and m.group(1):
            ini, fin = int(m.group(1)), min(int(m.group(2) or fin), fin)
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fin - ini + 1))
        if m:
            self.send_header("Content-Range", f"bytes {ini}-{fin}/{tam}")
        self.end_headers()
        with open(mp4, "rb") as f:
            f.seek(ini)
            try:
                self.wfile.write(f.read(fin - ini + 1))
            except ConnectionError:
                pass

    def do_POST(self):
        if self.path != "/publicar":
            return self.responder("No encontrado", "text/plain; charset=utf-8", 404)
        largo = int(self.headers.get("Content-Length", 0))
        f = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(largo).decode()).items()}
        tag, mp4 = f.get("tag", ""), archivo(f.get("tag", ""))
        try:
            if not mp4:
                raise ValueError("Vídeo no encontrado.")
            if not estados.get(tag, {"fin": True})["fin"]:
                raise ValueError("Este vídeo ya se está publicando.")
            info = tiktok("/v2/post/publish/creator_info/query/", {})
            com, org, bc = "comercial" in f, "organic" in f, "branded" in f
            privacidad, caption = f.get("privacy", ""), f.get("caption", "")
            if privacidad not in info.get("privacy_level_options", []):
                raise ValueError("Elige quién puede ver el vídeo.")
            if com and not (org or bc):
                raise ValueError("Debes indicar si tu contenido promociona a ti, a un tercero o a ambos.")
            if com and bc and privacidad == "SELF_ONLY":
                raise ValueError("La visibilidad del contenido de marca no puede ser privada.")
            if len(caption) > 2200:
                raise ValueError("La descripción supera los 2200 caracteres.")
            maxd, dur = info.get("max_video_post_duration_sec"), duracion(mp4)
            if maxd and dur and dur > maxd:
                raise ValueError(f"El vídeo dura {dur:.0f} s y el máximo es {maxd} s.")
        except Exception as ex:
            return self.responder(pagina(f"<p class='card err'>{e(str(ex))}</p><a class=btn href=/>Volver</a>"))
        post_info = {
            "title": caption, "privacy_level": privacidad,
            "disable_comment": info.get("comment_disabled", False) or "comentarios" not in f,
            "disable_duet": info.get("duet_disabled", False) or "duo" not in f,
            "disable_stitch": info.get("stitch_disabled", False) or "stitch" not in f,
            "brand_content_toggle": com and bc, "brand_organic_toggle": com and org,
            "is_aigc": True,
        }
        estados[tag] = {"texto": "Preparando…", "fin": False}
        threading.Thread(target=publicar, args=(tag, mp4, post_info), daemon=True).start()
        self.ir("/?publicando=" + urllib.parse.quote(tag))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    servidor = http.server.ThreadingHTTPServer(("localhost", PUERTO), App)
    print(f"Abierto en http://localhost:{PUERTO}  (Ctrl+C para salir)")
    webbrowser.open(f"http://localhost:{PUERTO}/")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass

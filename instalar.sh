#!/usr/bin/env bash
# Prepara ffmpeg/ffprobe (para el vídeo largo) y la fuente Liberation Sans Bold sin depender de los
# servidores de paquetes de Ubuntu, que a veces se cuelgan o fallan durante horas.
# - Lo que ya venga en el servidor de GitHub, se usa tal cual.
# - Si falta, se descarga de GitHub (versiones estáticas), que es mucho más fiable.
# - Ubuntu (apt) queda como último recurso, con límite de tiempo.
# Los Shorts no necesitan ffmpeg del sistema: moviepy usa el que trae imageio-ffmpeg.
set -u
FUENTE=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf

# --- Fuente --------------------------------------------------------------------------------------
if [ ! -f "$FUENTE" ]; then
  echo "Descargando la fuente Liberation Sans..."
  tmp=$(mktemp -d)
  if curl -fsSL --retry 3 --max-time 120 -o "$tmp/f.tar.gz" \
       https://github.com/liberationfonts/liberation-fonts/releases/download/2.1.5/liberation-fonts-ttf-2.1.5.tar.gz; then
    tar -xzf "$tmp/f.tar.gz" -C "$tmp"
    sudo mkdir -p "$(dirname "$FUENTE")"
    sudo cp "$tmp"/liberation-fonts-ttf-*/LiberationSans-*.ttf "$(dirname "$FUENTE")/"
  fi
  [ -f "$FUENTE" ] || sudo timeout 240 apt-get -o Acquire::Retries=2 install -y fonts-liberation || true
fi
if [ -f "$FUENTE" ]; then echo "Fuente lista."; else echo "AVISO: sin Liberation Sans; se usará otra fuente."; fi

# --- ffmpeg y ffprobe ----------------------------------------------------------------------------
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Descargando ffmpeg estático..."
  tmp=$(mktemp -d)
  if curl -fsSL --retry 3 --max-time 300 -o "$tmp/ff.tar.xz" \
       https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz; then
    tar -xJf "$tmp/ff.tar.xz" -C "$tmp"
    sudo cp "$tmp"/ffmpeg-*/bin/ffmpeg "$tmp"/ffmpeg-*/bin/ffprobe /usr/local/bin/
  fi
  if ! command -v ffmpeg >/dev/null; then
    sudo timeout 180 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 update || true
    sudo timeout 300 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 install -y ffmpeg || true
  fi
fi
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  echo "ffmpeg listo: $(ffmpeg -version | head -1)"
else
  echo "AVISO: sin ffmpeg del sistema (los Shorts funcionan igual; el vídeo largo lo necesita)."
fi
echo "Paquetes listos."

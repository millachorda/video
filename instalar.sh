#!/usr/bin/env bash
# Instala ffmpeg, ImageMagick y las fuentes Liberation solo si faltan, con límite de tiempo y reintentos:
# a veces los servidores de paquetes de Ubuntu se quedan colgados y bloqueaban el bot media hora o más.
set -u

falta() {
  ! command -v ffmpeg >/dev/null || ! command -v convert >/dev/null || ! fc-list 2>/dev/null | grep -qi "liberation"
}

for intento in 1 2 3; do
  falta || break
  echo "Instalando paquetes (intento $intento)..."
  sudo timeout 180 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 update -qq || true
  sudo timeout 300 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 install -y -qq \
    ffmpeg imagemagick fonts-liberation && break
  sleep 15
done

if falta; then
  echo "ERROR: no se pudieron instalar ffmpeg, ImageMagick o las fuentes."
  exit 1
fi

# Permitir a ImageMagick leer los archivos de texto que usa MoviePy
for politica in /etc/ImageMagick-6/policy.xml /etc/ImageMagick-7/policy.xml; do
  [ -f "$politica" ] && sudo sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/' "$politica"
done
echo "Paquetes listos."

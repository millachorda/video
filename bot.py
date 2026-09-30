name: Bot Shorts Misterio

on:
  schedule:
    - cron: "0 17 * * *"   # todos los días a las 17:00 UTC
  workflow_dispatch:        # botón para lanzarlo a mano

permissions:
  contents: write           # necesario para guardar contador.txt e historias.txt

jobs:
  generar:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Fuentes
        run: sudo apt-get update && sudo apt-get install -y fonts-dejavu-core

      - name: Dependencias
        run: pip install -r requirements.txt

      - name: Generar y enviar episodio
        env:
          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python bot.py

      - name: Guardar progreso
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
          git add contador.txt historias.txt
          git diff --cached --quiet || git commit -m "Episodio publicado [skip ci]"
          git push

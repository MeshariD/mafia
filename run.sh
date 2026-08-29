#!/bin/sh
# تشغيل محلي: ./run.sh  ثم افتح http://localhost:8000  (غيّر المنفذ بـ PORT=8123 ./run.sh)
PORT="${PORT:-8000}" exec python3 "$(dirname "$0")/server.py"

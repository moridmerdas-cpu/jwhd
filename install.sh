#!/bin/bash
set -e
[ -d /root/tg_env ] || python3 -m venv /root/tg_env
source /root/tg_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p sessions proxies logs models tests
[ -f .env ] || cp .env.example .env
python3 -c "from models.database import init_db; init_db()"
echo "نصب کامل"

# TG Master Bot

## Install

1. apt update
2. apt install -y python3 python3-pip python3-venv
3. cd /root && python3 -m venv tg_env
4. source tg_env/bin/activate
5. pip install -r requirements.txt
6. cp .env.example .env
7. nano .env
8. mkdir -p sessions proxies logs models tests
9. python3 -c "from models.database import init_db; init_db()"
10. python3 main.py

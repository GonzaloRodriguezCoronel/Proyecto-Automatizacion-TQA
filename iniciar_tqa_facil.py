"""Inicia TQA en Windows y abre automáticamente el navegador local."""
import os
from pathlib import Path
from threading import Timer
import webbrowser
import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')
host = '127.0.0.1'  # La interfaz sencilla es local: no se publica en la red.
port = int(os.getenv('APP_PORT', '8022'))
url = f'http://{host}:{port}'
print(f'\nTQA Facil listo en {url}\n')
Timer(2.5, lambda: webbrowser.open(url)).start()
uvicorn.run('app.main:app', host=host, port=port, log_level='info')

"""Configura credenciales de una cuenta de prueba SIN mostrarlas ni versionarlas."""
from pathlib import Path
from getpass import getpass
import os
import re

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.env'
TEMPLATE = ROOT / '.env.example'


def set_secret(text: str, name: str, value: str) -> str:
    # Conserva las demás variables y comentarios de SMTP/CIARÁ del usuario.
    escaped = '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    rows = text.splitlines()
    found = False
    for idx, row in enumerate(rows):
        if re.match(r'^\s*' + re.escape(name) + r'\s*=', row) and not found:
            rows[idx] = name + '=' + escaped
            found = True
    if not found:
        rows.append(name + '=' + escaped)
    return '\n'.join(rows).rstrip() + '\n'


def main():
    print('TQA · Acceso de pruebas de CIARÁ')
    print('Los datos se guardan solo en el archivo .env de tu computadora.')
    print('No se escriben en el proyecto ZIP, en los casos Selenium ni en los informes.\n')
    user = input('Nombre de usuario de prueba: ').strip()
    password = getpass('Contraseña de prueba (oculta): ')
    if not user or not password or any(ord(c) < 32 for c in user + password):
        print('Datos vacíos o inválidos: no se modificó ninguna configuración.')
        return 1
    if len(user) > 150 or len(password) > 200:
        print('Los datos son demasiado largos: no se guardaron.')
        return 1
    if not ENV.exists() and not TEMPLATE.exists():
        print('Falta el archivo .env.example de TQA.')
        return 1
    text = ENV.read_text(encoding='utf-8') if ENV.exists() else TEMPLATE.read_text(encoding='utf-8')
    text = set_secret(set_secret(text, 'CIARA_TEST_USERNAME', user), 'CIARA_TEST_PASSWORD', password)
    tmp = ENV.with_suffix('.env.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, ENV)
        if os.name != 'nt':
            ENV.chmod(0o600)
    except OSError:
        tmp.unlink(missing_ok=True)
        print('No se pudo actualizar .env; revisa permisos de la carpeta.')
        return 1
    print('\nAcceso configurado. Cierra y vuelve a abrir TQA para usar estas variables.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

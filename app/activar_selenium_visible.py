"""Activa Chrome visible en la configuración local sin mostrar ni modificar las claves SMTP."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env_path = root / '.env'
if not env_path.exists():
    example = root / '.env.example'
    if not example.exists():
        raise SystemExit('No existe .env ni .env.example; configura primero el proyecto.')
    env_path.write_text(example.read_text(encoding='utf-8'), encoding='utf-8')

lines = env_path.read_text(encoding='utf-8-sig').splitlines()
settings = {'SELENIUM_HEADLESS': 'false', 'SELENIUM_STEP_DELAY_MS': '900'}
found = set()
updated = []
for line in lines:
    key = line.split('=', 1)[0].strip()
    if key in settings and not line.lstrip().startswith('#'):
        if key not in found:
            updated.append(f'{key}={settings[key]}')
            found.add(key)
        continue
    updated.append(line)
for key, value in settings.items():
    if key not in found:
        updated.append(f'{key}={value}')
env_path.write_text('\n'.join(updated).rstrip() + '\n', encoding='utf-8')
print('Modo visual activado: Chrome visible, pausa de 900 ms entre pasos.')
print('La configuración SMTP y la clave API no se han mostrado ni cambiado.')
print('Reinicia TQA con run.bat para aplicar los cambios.')

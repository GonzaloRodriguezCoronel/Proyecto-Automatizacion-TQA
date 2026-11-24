"""Generador supervisado de proyectos Selenium IDE para suites nuevas.

La salida .side contiene comandos estándar; los chequeos no funcionales pertenecen
al motor TQA (metadatos 'tqa') y NO son comandos nativos de Selenium IDE.
Ningún caso se considera PASS por ser generado: tiene que ejecutarse realmente.
"""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime, timezone
from .robot_engine import validate_path
from .selenium_ide import parse_side, resolve_url, SideValidationError

TEMPLATES = {
    'Funcionales': {
        'Smoke': {'pagina': 'Apertura y estructura HTML', 'elemento': 'Elemento presente'},
        'Sanity': {'pagina': 'Apertura y estructura de página', 'elemento': 'Elemento visible'},
        'Regresión': {'elemento': 'Comprobar elemento después de cambios', 'login_ok': 'Login de demostración: válido', 'login_fail': 'Login de demostración: inválido'},
        'Integración': {'pagina': 'Integración: carga de interfaz', 'elemento': 'Integración: elemento visible'},
        'E2E': {'login_ok': 'Flujo de inicio de sesión (demo)', 'login_fail': 'Validación de credenciales incorrectas (demo)'},
    },
    'No funcionales': {
        'Rendimiento': {'tiempo': 'Tiempo de carga de página (navegador único)'},
        'Accesibilidad': {'accesibilidad': 'Chequeo básico de nombres y etiquetas'},
        'Responsividad': {'responsive': 'Desbordamiento horizontal en móvil'},
        'Estabilidad': {'repetir': 'Apertura de página en 3 intentos'},
    },
}
DEFAULTS = {'pagina': 'Apertura de página', 'elemento': 'Validación de elemento', 'login_ok': 'Inicio de sesión válido',
            'login_fail': 'Rechazo de credenciales inválidas', 'tiempo': 'Tiempo de carga',
            'accesibilidad': 'Accesibilidad básica', 'responsive': 'Diseño adaptable', 'repetir': 'Estabilidad de navegación'}


def template_catalog():
    return {'kinds': TEMPLATES, 'notice': 'Selenium comprueba UI y métricas de un navegador. Carga, estrés y concurrencia requieren un motor de rendimiento distinto.'}


def _command(command, target='', value=''):
    return {'id': uuid.uuid4().hex[:14], 'comment': '', 'command': command, 'target': target, 'targets': [], 'value': value}


def make_test(*, target: str, kind: str, category: str, template: str,
              name: str = '', page_path: str = '/demo/login', selector: str = 'css=body',
              max_ms: int = 3000) -> dict:
    if kind not in TEMPLATES or category not in TEMPLATES[kind] or template not in TEMPLATES[kind][category]:
        raise ValueError('El tipo, categoría y plantilla seleccionados no coinciden')
    page_path = validate_path(page_path)
    if template in ('login_ok', 'login_fail') and (target != 'Demo local' or page_path != '/demo/login'):
        raise ValueError('El login automático preconfigurado solo funciona con Demo local /demo/login')
    if template == 'elemento':
        # No se permite evaluar JavaScript generado por el usuario ni URLs remotas.
        if (not re.fullmatch(r'(?:css=|xpath=|id=|name=|//)[^\r\n\t]{1,190}', selector)
                or re.search(r'(?i)password|token|secret|api[_-]?key', selector)):
            raise ValueError('Selector inválido: utiliza css=..., xpath=..., id=... o //... (sin datos privados)')
    if not (100 <= max_ms <= 60000):
        raise ValueError('Tiempo máximo entre 100 y 60 000 ms')
    title = (name.strip() or DEFAULTS[template])[:90]
    if not title or any(c in title for c in '\r\n\t'):
        raise ValueError('Nombre del caso inválido')
    commands = []
    if template == 'responsive':
        commands.append(_command('setWindowSize', '375x812'))
    if template == 'repetir':
        for _ in range(3):
            commands.extend([_command('open', page_path), _command('assertElementPresent', 'css=body')])
    else:
        commands.append(_command('open', page_path))
        if template in ('pagina', 'tiempo', 'accesibilidad', 'responsive'):
            commands.append(_command('assertElementPresent', 'css=body'))
        elif template == 'elemento':
            commands.append(_command('waitForElementVisible', selector))
        elif template in ('login_ok', 'login_fail'):
            commands.extend([
                _command('type', 'id=usuario', 'demo' if template == 'login_ok' else 'usuario_incorrecto'),
                _command('type', 'id=password', 'Demo123!' if template == 'login_ok' else 'clave_incorrecta'),
                _command('click', 'id=entrar'),
                _command('assertText', 'id=resultado', 'Acceso correcto' if template == 'login_ok' else 'Credenciales incorrectas')])
    metadata = {'kind': kind, 'category': category, 'template': template, 'target': target,
                'page_path': page_path, 'max_ms': max_ms, 'checks': template in ('tiempo','accesibilidad','responsive')}
    case_id = 'tqa_'+uuid.uuid4().hex[:12]
    test = {'id': case_id, 'name': title, 'commands': commands, 'tqa': metadata}
    project = {'id': uuid.uuid4().hex[:12], 'version': '3.17.2', 'name': 'TQA | '+title,
               'url': '', 'tests': [test], 'suites': [{'id':uuid.uuid4().hex[:12], 'name':category, 'persistSession':False, 'parallel':False, 'timeout':300,'tests':[case_id]}],
               'urls': []}
    parse_side(json.dumps(project, ensure_ascii=False).encode('utf-8'))
    return project


def measure_check(driver, metadata: dict) -> dict:
    """Mediciones leídas del Chrome real; sin acceso a códigos de respuesta sintetizados."""
    template = metadata['template']
    if template == 'tiempo':
        value = driver.execute_script('''const n=performance.getEntriesByType('navigation')[0];
          return n && Number.isFinite(n.duration) && n.duration>0 ? Math.round(n.duration) : null;''')
        if not isinstance(value, (int, float)) or value <= 0:
            return {'status': 'NOT RUN', 'observed': 'El navegador no devolvió una métrica Navigation Timing válida.'}
        limit = metadata['max_ms']
        return {'status': 'PASS' if value <= limit else 'FAIL',
                'observed': f'Duración de navegación: {value} ms. Límite configurado: {limit} ms. No equivale a una prueba de carga.'}
    if template == 'accesibilidad':
        result = driver.execute_script('''return (() => {
          const imgs=[...document.images].filter(e=>!e.hasAttribute('alt'));
          const inputs=[...document.querySelectorAll('input:not([type=hidden]),select,textarea')]
            .filter(e=>{const style=getComputedStyle(e);return style.display!=='none'&&style.visibility!=='hidden'});
          const unnamed=inputs.filter(e=>!e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')
              && !e.labels?.length && !(e.id && document.querySelector('label[for="'+CSS.escape(e.id)+'"]')));
          const buttons=[...document.querySelectorAll('button')].filter(e=>!e.textContent.trim() && !e.getAttribute('aria-label'));
          return {missingAlt:imgs.length,unlabeledInputs:unnamed.length,unnamedButtons:buttons.length};
        })();''')
        if not isinstance(result, dict):
            return {'status': 'NOT RUN', 'observed': 'No se pudo evaluar el DOM de la página.'}
        count = sum(int(result.get(k, 0)) for k in ('missingAlt','unlabeledInputs','unnamedButtons'))
        return {'status': 'PASS' if count == 0 else 'FAIL',
                'observed': (f'Revisión básica: imágenes sin alt={result.get("missingAlt",0)}, '
                             f'campos sin etiqueta={result.get("unlabeledInputs",0)}, botones sin nombre={result.get("unnamedButtons",0)}. '
                             'No sustituye una auditoría WCAG completa.')}
    if template == 'responsive':
        result = driver.execute_script('''return {viewport:document.documentElement.clientWidth,
          content:document.documentElement.scrollWidth};''')
        if not isinstance(result, dict) or not result.get('viewport'):
            return {'status': 'NOT RUN', 'observed': 'No se pudo medir el ancho de la página.'}
        viewport = int(result['viewport']); content = int(result['content'])
        return {'status': 'PASS' if content <= viewport+8 else 'FAIL',
                'observed': f'Viewport móvil: {viewport}px, contenido: {content}px. Tolerancia de 8px.'}
    return {'status': 'NOT RUN', 'observed': 'Esta plantilla no tiene medición no funcional especial.'}

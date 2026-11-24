"""Robot Framework real: inspección Playwright, XPath verificado y SeleniumLibrary.

Solo inspecciona URLs locales / destinos explícitamente configurados por el administrador.
Para páginas desconocidas genera pruebas de SOLO LECTURA (presencia de elementos).
"""
import importlib.util
import os
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import httpx
from pathlib import Path
from urllib.parse import urlsplit

from .gherkin import gherkin_for_page

DEFAULT_PATH = {'Demo local': '/demo/login', 'CIARÁ': '/'}
ALLOWED_PATH = re.compile(r'^/[A-Za-z0-9_/-]{0,180}$')


class RobotPrerequisiteError(Exception):
    pass


def validate_path(path: str):
    if not isinstance(path, str) or not ALLOWED_PATH.fullmatch(path) or '//' in path or '..' in path:
        raise ValueError('La ruta debe ser local, comenzar con / y no contener dominios, consultas ni ../')
    return path


def safe_cell(value: str) -> str:
    """Impide caracteres de control y sintaxis de variables Robot inyectada desde una página."""
    if any(x in value for x in ['\n', '\r', '\t', '${', '@{', '%{', '&{', '\x00']):
        raise ValueError('Selector no válido para generar Robot Framework')
    return value


# No obtiene contenido de campos de entrada: evita extraer contraseñas y tokens.
INSPECT_JS = r'''() => {
    const xpathLiteral = v => {
      if (!v.includes("'")) return "'"+v+"'";
      if (!v.includes('"')) return '"'+v+'"';
      return 'concat(' + v.split("'").map((s,i)=> (i?',"\'",':'') + "'"+s+"'").join('') + ')';
    };
    const matches = x => {try {
      return document.evaluate(x, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength;
    } catch(_) {return 0;}};
    const path = el => {
      const chunks=[]; let current=el;
      while(current && current.nodeType===1){
        const tag=current.tagName.toLowerCase();
        const siblings=current.parentElement ? [...current.parentElement.children].filter(e=>e.tagName===current.tagName) : [current];
        const nth=siblings.indexOf(current)+1;
        chunks.unshift(tag+'['+nth+']');current=current.parentElement;
      }
      return '/'+chunks.join('/');
    };
    return [...document.querySelectorAll('input,button,select,textarea,a[href],[role="button"],[aria-live]')]
      .filter(el=>el.getClientRects().length && getComputedStyle(el).visibility!=='hidden')
      .slice(0,40).map(el=>{
        const tag=el.tagName.toLowerCase();
        const kind=el.getAttribute('type')||'';
        const props=['id','data-testid','name','aria-label','placeholder'];
        const candidates=[];
        for(const attr of props){
          const val=el.getAttribute(attr);
          if(val && val.length<100 && !/[\n\r\t]/.test(val)){
            if(attr==='id') candidates.push('//*[@id='+xpathLiteral(val)+']');
            else candidates.push('//'+tag+'[@'+attr+'='+xpathLiteral(val)+']');
          }
        }
        const txt=(el.innerText||'').replace(/\s+/g,' ').trim();
        if(txt && txt.length<65) candidates.push('//'+tag+'[normalize-space(.)='+xpathLiteral(txt)+']');
        candidates.push(path(el));
        const xpath=candidates.find(x=>matches(x)===1)||'';
        return {tag, type:kind, label:(el.getAttribute('aria-label')||el.getAttribute('placeholder')||txt||el.getAttribute('name')||el.getAttribute('id')||tag).slice(0,90),
          id:el.id||'',xpath,verified: Boolean(xpath)&&matches(xpath)===1};
      }).filter(x=>x.verified);
}'''


def discover(base_url: str, path: str):
    """Abre la página real y devuelve SOLO XPath comprobados en su DOM."""
    validate_path(path)
    from playwright.sync_api import sync_playwright
    url = base_url.rstrip('/') + path
    try:
        with sync_playwright() as pw:
            browser_path = os.getenv('CHROMIUM_EXECUTABLE')
            browser = pw.chromium.launch(headless=True, executable_path=browser_path or None,
                                         args=['--no-sandbox'] if browser_path else None)
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 800})
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    if not response:
                        raise RobotPrerequisiteError('La página no respondió al navegador')
                    http_status = response.status
                    inspection_mode = 'Navegación real de Playwright'
                except Exception as exc:
                    if 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(exc):
                        raise
                    # Algunos laboratorios restringen localhost desde Chromium.
                    # Se analiza el HTML obtenido por HTTP; no equivale a probar JS remoto.
                    with httpx.Client(trust_env=False, timeout=8) as client:
                        result = client.get(url)
                    http_status = result.status_code
                    if http_status >= 400:
                        raise RobotPrerequisiteError(f'La página respondió HTTP {http_status}')
                    page.set_content(result.text, wait_until='domcontentloaded')
                    inspection_mode = 'HTML recuperado por HTTP (navegador restringido)'
                if http_status >= 400:
                    raise RobotPrerequisiteError(f'La página respondió HTTP {http_status}')
                # No inspeccionar páginas fuera del origen configurado tras redirecciones.
                if inspection_mode == 'Navegación real de Playwright' and urlsplit(page.url).netloc != urlsplit(base_url).netloc:
                    raise RobotPrerequisiteError('La página redirigió fuera del destino autorizado; inspección cancelada.')
                title = page.title()[:90]
                elements = page.evaluate(INSPECT_JS)
                return {'url': url, 'path': path, 'http_status': http_status,
                        'title': title, 'inspection_mode':inspection_mode, 'elements': elements}
            finally:
                browser.close()
    except RobotPrerequisiteError:
        raise
    except Exception as exc:
        name = type(exc).__name__
        if 'Executable doesn' in str(exc) or 'browserType.launch' in str(exc):
            raise RobotPrerequisiteError('Chromium de Playwright no instalado. Ejecuta: .\\.venv\\Scripts\\python.exe -m playwright install chromium') from exc
        raise RobotPrerequisiteError(f'No se pudo inspeccionar la página con Playwright ({name}). Verifica que el servidor está encendido.') from exc


def find_by_id(elements, value):
    return next((e for e in elements if e['id'] == value and e['verified']), None)


def generate_suite(scan: dict, *, demo_login: bool) -> str:
    """Genera .robot con aserciones reales; generic = SOLO existencia (no validación funcional)."""
    elements = scan['elements']
    if not elements:
        raise RobotPrerequisiteError('No se encontraron elementos interactivos visibles; no se inventan XPath.')
    login = demo_login and all(find_by_id(elements, x) for x in ('usuario', 'password', 'entrar', 'resultado'))
    # El resultado no es visible antes de iniciar sesión: se conoce por el DOM del formulario de prueba.
    suite = [
        '*** Settings ***',
        'Library    SeleniumLibrary    run_on_failure=NONE',
        'Suite Teardown    Close All Browsers',
        '',
        '*** Variables ***',
        '${URL}    ' + safe_cell(scan['url']),
    ]
    if login:
        for symbol, id_ in [('USUARIO','usuario'),('PASSWORD','password'),('ENTRAR','entrar')]:
            element = find_by_id(elements, id_)
            suite.append('${'+symbol+'}    xpath='+safe_cell(element['xpath']))
        suite.append('${RESULTADO}    xpath='+safe_cell(find_by_id(elements, 'resultado')['xpath']))
        suite.extend([
            '', '*** Test Cases ***', 'Inicio de sesion correcto - Demo TQA',
            '    [Documentation]    Flujo real con cuenta de demostracion. La asercion valida el mensaje visible.',
            '    Open Browser    ${URL}    chrome    options=add_argument("--headless=new")',
            '    Wait Until Element Is Visible    ${USUARIO}    10s',
            '    Input Text    ${USUARIO}    demo',
            '    Input Password    ${PASSWORD}    Demo123!',
            '    Click Element    ${ENTRAR}',
            '    Wait Until Element Contains    ${RESULTADO}    Acceso correcto    timeout=10s',
            '    Capture Page Screenshot    evidencia_robot_login.png',
            '',
        ])
    else:
        listed = elements[:15]
        for idx, e in enumerate(listed, 1):
            suite.append('${ELEMENTO_'+str(idx)+'}    xpath='+safe_cell(e['xpath']))
        suite.extend([
            '', '*** Test Cases ***', 'Elementos visibles y localizables - Smoke',
            '    [Documentation]    Prueba no destructiva: verifica presencia en DOM. No certifica procesos de negocio.',
            '    Open Browser    ${URL}    chrome    options=add_argument("--headless=new")',
        ])
        for idx, _ in enumerate(listed, 1):
            suite.append('    Wait Until Page Contains Element    ${ELEMENTO_'+str(idx)+'}    timeout=10s')
        suite.append('')
    return '\n'.join(suite)


def execute_auto(*, target: str, base_url: str, page_path: str, evidence_dir: Path) -> dict:
    started = time.perf_counter()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    images = []
    artifacts = []
    steps = []
    status = 'NOT RUN'
    obs = 'Ejecución no iniciada'
    title = 'Pruebas automáticas de página web con Robot Framework'
    objective = 'Inspeccionar DOM, verificar XPath, generar script Robot Framework y ejecutarlo.'
    expected = 'El caso generado se ejecuta con aserciones y presenta PASS o FAIL según la ejecución real.'
    try:
        validate_path(page_path)
        steps.append({'action': 'Abrir página e inspeccionar DOM con Playwright',
                      'expected':'Elementos reales y XPath únicos', 'observed':'Inspección iniciada', 'status':'PASS'})
        scan = discover(base_url, page_path)
        elements = scan['elements']
        if not elements:
            raise RobotPrerequisiteError('No hay elementos interactivos visibles; no es posible crear una prueba de XPath.')
        login = target == 'Demo local' and page_path == '/demo/login' and all(find_by_id(elements,x) for x in ('usuario','password','entrar','resultado'))
        feature = gherkin_for_page(scan['title'], page_path, bool(login), len(elements))
        feature += '\n\n  # XPath localizados y verificados en el DOM de esta página:'
        for element in elements[:15]:
            feature += f"\n  # {element['tag']} ({element['label']}): {element['xpath']}"
        robot_code = generate_suite(scan, demo_login=bool(login))
        for name, content in [('escenario_gherkin.feature', feature), ('prueba_automatizada.robot', robot_code)]:
            (evidence_dir / name).write_text(content, encoding='utf-8')
            artifacts.append(name)
        (evidence_dir / 'locators_validados.json').write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding='utf-8')
        artifacts.append('locators_validados.json')
        steps[-1]['observed'] = f'{len(elements)} elementos inspeccionados con XPath únicos y verificados'
        steps.append({'action':'Generar Gherkin, archivo .robot y localizadores',
                      'expected':'Archivos con datos reales', 'observed':'3 archivos generados', 'status':'PASS'})
        if importlib.util.find_spec('robot') is None or importlib.util.find_spec('SeleniumLibrary') is None:
            raise RobotPrerequisiteError('Falta Robot Framework/SeleniumLibrary. Ejecuta instalar_robot_windows.bat')
        cmd = [sys.executable, '-m', 'robot', '--outputdir', str(evidence_dir),
               '--output', 'robot_output.xml', '--log', 'robot_log.html',
               '--report', 'robot_report.html', str(evidence_dir / 'prueba_automatizada.robot')]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=80, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RobotPrerequisiteError('La prueba Robot superó el límite de 80 segundos (infraestructura).') from exc
        for name in ('robot_output.xml', 'robot_log.html', 'robot_report.html'):
            if (evidence_dir / name).exists():
                artifacts.append(name)
        xml_file = evidence_dir / 'robot_output.xml'
        if not xml_file.exists():
            raise RobotPrerequisiteError('Robot no generó output.xml. ' + (proc.stderr or proc.stdout)[-250:])
        doc = ET.parse(xml_file)
        statuses = doc.findall('.//test/status')
        message = '; '.join((node.text or '').strip()[:250] for node in statuses if node.attrib.get('status') == 'FAIL').strip('; ')
        if not statuses:
            raise RobotPrerequisiteError('Robot no registró casos ejecutados. Revisa robot_log.html')
        failures = [node for node in statuses if node.attrib.get('status') == 'FAIL']
        infrastructure_tokens = ('web driver', 'webdriver', 'chromedriver', 'session not created', 'unable to obtain driver', 'no module named', 'failed to create', 'browser initialization', 'could not start a new session', 'could not find chrome binary')
        if failures and any(token in message.lower() for token in infrastructure_tokens):
            raise RobotPrerequisiteError('No fue posible iniciar Chrome/Selenium en tu equipo. Comprueba Chrome y Selenium Manager. ' + message[:150])
        status = 'FAIL' if failures else 'PASS'
        obs = (message or f'Robot Framework ejecutó {len(statuses)} caso(s) con resultado PASS.')
        steps.append({'action':'Ejecutar el archivo con Robot Framework y SeleniumLibrary',
                      'expected':'Aserciones automáticas correctas', 'observed':obs, 'status':status})
        for img in evidence_dir.glob('*.png'):
            # Las capturas sólo se habilitan para el formulario demo, no para páginas desconocidas.
            if login:
                images.append(img.name)
    except (RobotPrerequisiteError, ValueError) as exc:
        obs = str(exc)
        status = 'NOT RUN'
        steps.append({'action':'Prerrequisitos de ejecución Robot', 'expected':'Herramientas y página disponibles',
                      'observed':obs, 'status':'NOT RUN'})
    except Exception as exc:
        status = 'NOT RUN'
        obs = f'Error de infraestructura durante Robot: {type(exc).__name__}'
        steps.append({'action':'Ejecutar integración Robot', 'expected':'Ejecución real', 'observed':obs, 'status':'NOT RUN'})
    result = {
        'id':'TC-ROB-AUTO', 'name':title, 'kind':'Funcionales', 'suite':'Robot Framework',
        'objective':objective, 'preconditions':'Página local autorizada y navegadores de automatización instalados.',
        'expected':expected, 'planned_steps':['Inspeccionar el DOM', 'Generar XPath únicos', 'Crear un escenario Gherkin y archivo .robot', 'Ejecutar SeleniumLibrary', 'Registrar evidencias'],
        'status':status, 'failure_class':'infraestructura' if status=='NOT RUN' else 'funcional',
        'duration_s':round(time.perf_counter()-started,3), 'steps':steps,
        'observation':obs, 'evidence':images, 'artifacts':artifacts,
    }
    return result

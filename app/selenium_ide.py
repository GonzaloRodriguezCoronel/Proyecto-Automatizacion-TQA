"""Importador seguro Selenium IDE (.side) + reproductor de comandos sobre Selenium WebDriver.

No ejecuta comandos JavaScript arbitrarios ni navega a dominios externos. Los videos son
RECONSTRUCCIONES de capturas del navegador tras cada paso, no grabaciones continuas.
"""
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

SUPPORTED = {
    'open', 'click', 'doubleClick', 'type', 'sendKeys', 'select', 'check', 'uncheck',
    'assertText', 'verifyText', 'assertValue', 'verifyValue', 'assertElementPresent',
    'verifyElementPresent', 'assertElementNotPresent', 'assertTitle', 'verifyTitle',
    'waitForElementVisible', 'waitForElementPresent', 'waitForElementNotVisible',
    'pause', 'setWindowSize', 'mouseOver', 'echo',
    # Comandos internos que TQA genera para CIARÁ, no comandos estándar de .side.
    'ciaraSignIn', 'ciaraBrowse', 'ciaraRepeat',
}
MAX_BYTES = 512_000
MAX_TESTS = 35
MAX_COMMANDS = 90


class SideValidationError(ValueError):
    pass


class SideAssertionFailed(AssertionError):
    pass


class SideUnsupportedError(RuntimeError):
    pass


def parse_side(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise SideValidationError('El proyecto .side supera 500 KB')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SideValidationError('Archivo .side inválido: debe ser JSON UTF-8') from None
    if not isinstance(data, dict) or not isinstance(data.get('tests'), list) or not data['tests']:
        raise SideValidationError('El proyecto .side debe contener una lista tests no vacía')
    if len(data['tests']) > MAX_TESTS:
        raise SideValidationError(f'Máximo {MAX_TESTS} pruebas por proyecto')
    ids = set()
    for test in data['tests']:
        if not isinstance(test, dict) or not isinstance(test.get('commands'), list):
            raise SideValidationError('Cada prueba necesita una lista commands')
        if not isinstance(test.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,90}', test['id']):
            raise SideValidationError('Cada prueba necesita un identificador simple')
        if test['id'] in ids:
            raise SideValidationError('Los identificadores de pruebas deben ser únicos')
        ids.add(test['id'])
        if len(test['commands']) > MAX_COMMANDS:
            raise SideValidationError(f'Máximo {MAX_COMMANDS} comandos por prueba')
        for cmd in test['commands']:
            if not isinstance(cmd, dict) or not isinstance(cmd.get('command'), str):
                raise SideValidationError('Comando .side inválido')
            if len(str(cmd.get('target', ''))) > 600 or len(str(cmd.get('value', ''))) > 600:
                raise SideValidationError('Un selector o dato excede la longitud permitida')
    # Nunca usar la URL base proporcionada en el .side como destino; la decide el operador.
    return data


def is_sensitive(command: dict):
    target = str(command.get('target', '')).lower()
    return bool(re.search(r'password|passwd|pwd|token|secret|api[-_]?key', target))


def preview_project(data: dict) -> dict:
    tests = []
    for test in data['tests']:
        commands = []
        for cmd in test['commands']:
            action = cmd.get('command', '')
            commands.append({
                'command': action, 'target': str(cmd.get('target', '')),
                'value': '••••••••' if is_sensitive(cmd) else str(cmd.get('value', '')),
                'supported': action in SUPPORTED,
            })
        tests.append({'id': test['id'], 'name': str(test.get('name', test['id']))[:140],
                      'count': len(commands), 'kind': test.get('tqa',{}).get('kind','Funcionales'), 'category': test.get('tqa',{}).get('category','Grabadas'), 'target': test.get('tqa',{}).get('target', ''), 'unsupported': [c['command'] for c in commands if not c['supported']],
                      'commands': commands})
    suites = [{'name': str(s.get('name', 'Suite'))[:120],
               'tests': [x for x in s.get('tests', []) if x in {t['id'] for t in data['tests']}]} 
              for s in data.get('suites', []) if isinstance(s, dict)]
    return {'name': str(data.get('name', 'Proyecto Selenium IDE'))[:120],
            'tests': tests, 'suites': suites, 'count': len(tests),
            'notice': 'La ejecución acepta únicamente rutas del objetivo configurado. No se ejecuta código JavaScript importado.'}


def resolve_url(base_url: str, target: str) -> str:
    base = urlsplit(base_url)
    if base.scheme not in ('http', 'https') or not base.netloc:
        raise SideValidationError('El objetivo administrado no es HTTP/HTTPS')
    target = target.strip()
    if not target or target.startswith(('#', '//')) or any(c in target for c in ('\\', '\r', '\n', '\t')):
        raise SideValidationError('La ruta open del .side debe ser una ruta relativa válida')
    destination = urljoin(base_url.rstrip('/') + '/', target)
    parsed = urlsplit(destination)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc or parsed.username or parsed.password:
        raise SideValidationError('El .side intenta navegar fuera de la aplicación autorizada')
    if parsed.path.startswith('//'):
        raise SideValidationError('Ruta no permitida')
    return destination


def _by_selector(target: str):
    from selenium.webdriver.common.by import By
    target = target.strip()
    if target.startswith('xpath='):
        return By.XPATH, target[6:]
    if target.startswith('//') or target.startswith('('):
        return By.XPATH, target
    if target.startswith('css='):
        return By.CSS_SELECTOR, target[4:]
    for prefix, by in [('id=', By.ID), ('name=', By.NAME), ('linkText=', By.LINK_TEXT),
                       ('link=', By.LINK_TEXT), ('partialLinkText=', By.PARTIAL_LINK_TEXT),
                       ('tag=', By.TAG_NAME), ('class=', By.CLASS_NAME)]:
        if target.startswith(prefix):
            return by, target[len(prefix):]
    return By.CSS_SELECTOR, target


def _locator_variants(cmd: dict):
    selectors = [cmd.get('target') or '']
    selectors += [candidate[0] for candidate in cmd.get('targets', [])
                  if isinstance(candidate, list) and candidate and isinstance(candidate[0], str)]
    return list(dict.fromkeys(s for s in selectors if s))[:12]


def _find(driver, cmd, *, visible=False, timeout=8):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    selectors = _locator_variants(cmd)
    if not selectors:
        raise SideAssertionFailed('El comando no tiene un localizador')
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        for selector in selectors:
            try:
                el = driver.find_element(*_by_selector(selector))
                if not visible or el.is_displayed():
                    return el, selector
            except Exception as exc:
                last = exc
        time.sleep(.2)
    raise SideAssertionFailed('No se encontró el elemento con los localizadores indicados')


def _xpath(driver, element):
    script = '''const el=arguments[0]; const esc=s=>s.replace(/'/g,"\\\\'");
      if(el.id && document.querySelectorAll('#'+CSS.escape(el.id)).length===1)
        return '//*[@id="'+el.id.replace(/"/g,'')+'"]';
      if(el.name){const v=el.name.replace(/"/g,'');const x='//'+el.tagName.toLowerCase()+'[@name="'+v+'"]';
        if(document.evaluate(x,document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null).snapshotLength===1)return x;}
      let p=el, parts=[]; while(p&&p.nodeType===1){let n=1,q=p.previousElementSibling;
        while(q){if(q.tagName===p.tagName)n++;q=q.previousElementSibling;}
        parts.unshift(p.tagName.toLowerCase()+'['+n+']');p=p.parentElement;} return '/'+parts.join('/');'''
    try:
        xp = driver.execute_script(script, element)
        return xp if len(driver.find_elements(*_by_selector('xpath=' + xp))) == 1 else ''
    except Exception:
        return ''


def _observe_driver_origin(driver, base_url):
    current = urlsplit(driver.current_url)
    allowed = urlsplit(base_url)
    if current.scheme != allowed.scheme or current.netloc != allowed.netloc:
        raise SideValidationError('La prueba navegó fuera del destino permitido; se detuvo')


def _execute_command(driver, command: dict, base_url: str):
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import Select
    action = command.get('command', '')
    target = str(command.get('target', ''))
    value = str(command.get('value', ''))
    found = None
    selector = ''
    if action == 'open':
        driver.get(resolve_url(base_url, target))
        detail = f'Página cargada: {urlsplit(driver.current_url).path}'
    elif action == 'setWindowSize':
        match = re.fullmatch(r'(\d{3,4})x(\d{3,4})', target)
        if not match:
            raise SideAssertionFailed('Dimensión inválida: usa 1024x768')
        driver.set_window_size(min(int(match[1]), 1600), min(int(match[2]), 1000))
        detail = f'Ventana {match[1]}x{match[2]}'
    elif action == 'pause':
        ms = min(max(int(target or 0), 0), 3000)
        time.sleep(ms/1000)
        detail = f'Pausa {ms} ms'
    elif action == 'echo':
        detail = target[:100]
    elif action == 'waitForElementNotVisible':
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            present = False
            for loc in _locator_variants(command):
                try:
                    present = any(el.is_displayed() for el in driver.find_elements(*_by_selector(loc)))
                    if present: break
                except Exception:
                    continue
            if not present: break
            time.sleep(.2)
        else:
            raise SideAssertionFailed('Se esperaba que el elemento dejara de ser visible')
        detail = 'Elemento ya no visible'
    elif action == 'assertElementNotPresent':
        if any(driver.find_elements(*_by_selector(s)) for s in _locator_variants(command)):
            raise SideAssertionFailed('Se esperaba que el elemento no estuviera presente')
        detail = 'Elemento no presente'
    else:
        found, selector = _find(driver, command, visible=action not in (
            'assertElementPresent', 'verifyElementPresent', 'waitForElementPresent'))
        if action == 'click':
            found.click(); detail = 'Clic realizado'
        elif action == 'doubleClick':
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).double_click(found).perform(); detail = 'Doble clic realizado'
        elif action == 'mouseOver':
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).move_to_element(found).perform(); detail = 'Cursor situado sobre elemento'
        elif action == 'type':
            found.clear(); found.send_keys(value); detail = 'Texto introducido (dato protegido)' if is_sensitive(command) else 'Texto introducido'
        elif action == 'sendKeys':
            keys = {'${KEY_ENTER}': Keys.ENTER, '${KEY_TAB}': Keys.TAB, '${KEY_ESC}': Keys.ESCAPE,
                    '${KEY_BACKSPACE}': Keys.BACKSPACE, '${KEY_SPACE}': Keys.SPACE}
            found.send_keys(keys.get(value, value)); detail = 'Teclas enviadas'
        elif action == 'check':
            if not found.is_selected(): found.click()
            detail = 'Control marcado'
        elif action == 'uncheck':
            if found.is_selected(): found.click()
            detail = 'Control desmarcado'
        elif action == 'select':
            chooser = Select(found)
            if value.startswith('label='): chooser.select_by_visible_text(value[6:])
            elif value.startswith('value='): chooser.select_by_value(value[6:])
            elif value.startswith('index='): chooser.select_by_index(int(value[6:]))
            else: chooser.select_by_visible_text(value)
            detail = 'Opción seleccionada'
        elif action in ('assertText', 'verifyText'):
            observed = found.text.strip()
            if observed != value:
                raise SideAssertionFailed(f'Se esperaba texto «{value[:80]}», se observó «{observed[:80]}»')
            detail = f'Texto correcto: {observed[:80]}'
        elif action in ('assertValue', 'verifyValue'):
            observed = found.get_attribute('value') or ''
            if observed != value:
                raise SideAssertionFailed('El valor del campo no coincide con lo esperado')
            detail = 'Valor del campo correcto'
        elif action in ('assertElementPresent', 'verifyElementPresent', 'waitForElementPresent'):
            detail = 'Elemento encontrado'
        elif action in ('waitForElementVisible',):
            detail = 'Elemento visible'
        elif action in ('assertTitle', 'verifyTitle'):
            if driver.title != target:
                raise SideAssertionFailed(f'Título esperado: {target[:80]}, obtenido: {driver.title[:80]}')
            detail = 'Título correcto'
        else:
            raise SideUnsupportedError(f'Comando no soportado: {action}')
    _observe_driver_origin(driver, base_url)
    return detail, (selector if found is not None else ''), (_xpath(driver, found) if found is not None else '')


def _ciara_sign_in(driver, base_url: str) -> str:
    """Inicia una sesión de prueba sin persistir ni registrar las credenciales.

    Se ejecuta únicamente en proyectos internos de CIARÁ marcados para login.
    No acepta contraseñas suministradas en archivos .side ni en la interfaz web.
    """
    import os
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException

    username = os.getenv('CIARA_TEST_USERNAME', '').strip()
    password = os.getenv('CIARA_TEST_PASSWORD', '')
    if not username or not password:
        raise SideValidationError('Configura CIARA_TEST_USERNAME y CIARA_TEST_PASSWORD en el .env local.')
    _observe_driver_origin(driver, base_url)
    wait = WebDriverWait(driver, 12)
    try:
        passwd = wait.until(lambda d: next((e for e in d.find_elements(By.CSS_SELECTOR, 'input[type="password"]') if e.is_displayed()), None))
    except TimeoutException:
        raise SideAssertionFailed('No se encontró el formulario de acceso a CIARÁ.') from None
    try:
        form = passwd.find_element(By.XPATH, 'ancestor::form[1]')
    except Exception:
        form = driver
    candidates = [
        'input[name="username" i]', 'input[name="usuario" i]', 'input[name="user" i]',
        'input[autocomplete="username"]', 'input[placeholder*="usuario" i]',
        'input[type="text"]', 'input[type="email"]',
    ]
    user_input = next((element for css in candidates for element in form.find_elements(By.CSS_SELECTOR, css)
                       if element.is_displayed() and element.is_enabled() and element != passwd), None)
    if user_input is None:
        raise SideAssertionFailed('No se encontró el campo de usuario en CIARÁ.')
    old_path = urlsplit(driver.current_url).path
    user_input.clear()
    user_input.send_keys(username)
    passwd.clear()
    passwd.send_keys(password)
    buttons = form.find_elements(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"], button:not([type="button"])')
    submit = next((b for b in buttons if b.is_displayed() and b.is_enabled()), None)
    if submit is not None:
        submit.click()
    else:
        # Respeta también formularios que admiten Enter sin botón explícito.
        from selenium.webdriver.common.keys import Keys
        passwd.send_keys(Keys.ENTER)

    def authenticated(d):
        _observe_driver_origin(d, base_url)
        visible_passwords = [e for e in d.find_elements(By.CSS_SELECTOR, 'input[type="password"]') if e.is_displayed()]
        if visible_passwords:
            return False
        body = d.find_element(By.TAG_NAME, 'body')
        # No confundir un mensaje de credenciales incorrectas o una pantalla
        # vacía con un inicio de sesión aprobado.
        visible_text = body.text.strip()
        if re.search(r'(?i)(credenciales incorrectas|usuario o contrase.n?a incorrect|'
                     r'contrase.n?a inv.lida|acceso denegado|invalid credentials|login failed)', visible_text):
            return False
        return bool(body.is_displayed() and len(visible_text) >= 15)

    try:
        WebDriverWait(driver, 18).until(authenticated)
    except TimeoutException:
        raise SideAssertionFailed('CIARÁ no confirmó el inicio de sesión. Revisa la cuenta de prueba y el mensaje del formulario.') from None
    current = urlsplit(driver.current_url).path or '/'
    return ('Acceso de prueba confirmado: formulario de contraseña cerrado y pantalla interna visible. '
            f'Ruta actual: {current[:100]}')


def _ciara_browse(driver, base_url: str, limit: int) -> str:
    """Visita enlaces internos seguros de solo lectura manteniendo la sesión."""
    from selenium.webdriver.common.by import By
    from urllib.parse import urljoin
    import re
    _observe_driver_origin(driver, base_url)
    origin = urlsplit(base_url)
    links = []
    for link in driver.find_elements(By.CSS_SELECTOR, 'a[href]'):
        href = link.get_attribute('href') or ''
        target = urlsplit(urljoin(driver.current_url, href))
        if (target.scheme != origin.scheme or target.netloc != origin.netloc or
            not target.path or re.search(r'(?i)(logout|salir|cerrar.sesion|delete|remove|eliminar|destroy|borrar|descargar|export)', target.path)):
            continue
        if target.query or target.fragment:
            continue
        candidate = target.geturl()
        if candidate not in links and candidate != driver.current_url:
            links.append(candidate)
    if not links:
        raise SideAssertionFailed('No se encontraron enlaces internos de solo lectura para comprobar la navegación.')
    visited = 0
    for candidate in links[:max(1, min(limit, 8))]:
        driver.get(candidate)
        _observe_driver_origin(driver, base_url)
        if not driver.find_element(By.TAG_NAME, 'body').is_displayed():
            raise SideAssertionFailed('Una pantalla interna no mostró contenido visible.')
        if any(e.is_displayed() for e in driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')):
            raise SideAssertionFailed('CIARÁ regresó al login al visitar una pantalla interna.')
        visited += 1
    return f'Navegación autenticada: {visited} pantallas internas comprobadas sin salir de CIARÁ.'


def _ciara_repeat(driver, base_url: str) -> str:
    from selenium.webdriver.common.by import By
    for _ in range(3):
        driver.refresh()
        _observe_driver_origin(driver, base_url)
        if not driver.find_element(By.TAG_NAME, 'body').is_displayed():
            raise SideAssertionFailed('La pantalla no respondió durante la repetición.')
        if any(e.is_displayed() for e in driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')):
            raise SideAssertionFailed('La sesión caducó al repetir la navegación.')
    return 'Estabilidad básica: tres recargas autenticadas correctas; no equivale a soak prolongado.'


def _make_video(frames: list[Path], destination: Path):
    """Video MP4 reproducible de pasos (captura por comando). No es screencast continuo."""
    if not frames:
        return False
    try:
        import imageio_ffmpeg
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        width, height = 900, 540
        write = imageio_ffmpeg.write_frames(str(destination), (width, height), fps=3,
                                             codec='libx264', pix_fmt_in='rgb24', pix_fmt_out='yuv420p',
                                             output_params=['-movflags', '+faststart'])
        next(write)
        try:
            for index, image_path in enumerate(frames[:90], 1):
                with Image.open(image_path) as original:
                    img = Image.new('RGB', (width, height), '#0c1c31')
                    shot = ImageOps.contain(original.convert('RGB'), (width, height - 74))
                    img.paste(shot, ((width - shot.width)//2, 58 + (height - 74 - shot.height)//2))
                    draw = ImageDraw.Draw(img)
                    draw.text((24, 19), f'SELENIUM IDE · PASO {index}/{len(frames)}', fill='#ffffff')
                    draw.text((24, 41), 'Evidencia visual reconstruida a partir de capturas por paso', fill='#a9bdd8')
                    raw = img.tobytes()
                    for _ in range(4):
                        write.send(raw)
        finally:
            write.close()
        return destination.exists() and destination.stat().st_size > 1000
    except Exception:
        destination.unlink(missing_ok=True)
        return False


def gherkin_from_commands(case: dict) -> str:
    """Documentación natural, de pasos importados. No utiliza IA ni inventa acciones."""
    name = str(case.get('name', case['id'])).replace('\n',' ')[:100]
    actions = []
    expectations = []
    for cmd in case['commands']:
        kind = cmd.get('command', '')
        where = str(cmd.get('target',''))[:95]
        value = str(cmd.get('value', ''))[:95]
        if kind == 'open': actions.append(f'abro la página "{where}"')
        elif kind == 'type':
            actions.append(f'ingreso los datos de prueba en "{where}"' if not is_sensitive(cmd) else f'ingreso la contraseña de prueba en "{where}"')
        elif kind == 'ciaraSignIn': actions.append('ingreso a CIARÁ con la cuenta de prueba configurada de forma privada')
        elif kind == 'ciaraBrowse': actions.append('reviso pantallas internas usando una sesión autenticada')
        elif kind == 'ciaraRepeat': actions.append('recargo tres veces la pantalla interna')
        elif kind == 'click': actions.append(f'hago clic en "{where}"')
        elif kind == 'select': actions.append(f'selecciono la opción "{value}" en "{where}"')
        elif kind.startswith('assert') or kind.startswith('verify'):
            if kind in ('assertText','verifyText'):
                expectations.append(f'el elemento "{where}" debe mostrar "{value}"')
            elif kind in ('assertTitle','verifyTitle'):
                expectations.append(f'el título de la página debe ser "{where}"')
            else: expectations.append(f'se cumple la validación {kind} para "{where}"')
    if not actions:
        actions=['consulto la página configurada y reviso los elementos grabados']
    if len(actions)==1:
        actions.append('compruebo que el navegador ha completado la acción grabada')
    if case.get('tqa',{}).get('checks'):
        expectations.append('el indicador no funcional cumple el criterio configurado y medido en el navegador')
    if not expectations:
        expectations=['todos los comandos grabados se ejecutan sin errores']
    return (f'Feature: Reproducción de {name}\n  Scenario: {name}\n'
            '    Given que la aplicación de pruebas está disponible\n'
            f'    When {actions[0]}\n'
            + ''.join(f'    And {a}\n' for a in actions[1:])
            + f'    Then {expectations[0]}\n'
            + ''.join(f'    And {e}\n' for e in expectations[1:]))


def robot_from_commands(case: dict, base_url: str, locators: list[dict]) -> str:
    """Genera artefacto Robot de referencia. Contraseñas requieren variable de entorno."""
    title = re.sub(r'[^a-zA-Z0-9 áéíóúÁÉÍÓÚñÑ_-]', '', str(case.get('name','Caso SIDE')))[:95]
    lines = ['*** Settings ***', 'Library    SeleniumLibrary', 'Library    OperatingSystem', '',
             '*** Variables ***', f'${{BASE_URL}}    {base_url}', '',
             '*** Test Cases ***', title or 'Caso SIDE',
             '    Open Browser    ${BASE_URL}    chrome', '    Set Window Size    1200    800']
    lookup = {l['step']:l.get('xpath','') for l in locators}
    for idx, cmd in enumerate(case.get('commands',[]),1):
        kind = cmd.get('command','')
        raw = str(cmd.get('target',''))
        val = str(cmd.get('value',''))
        if any(char in raw+val for char in ('\r','\n','\t')) or '${' in raw or '${' in val:
            lines.append(f'    # Paso {idx}: valor requiere revisión; no se genera código inseguro')
            continue
        xpath = lookup.get(idx,'')
        locator = ('xpath:' + xpath) if xpath else raw.replace('=',':',1)
        if kind=='open':
            try:
                final=resolve_url(base_url,raw)
                lines.append('    Go To    '+final)
            except SideValidationError:
                lines.append(f'    # Paso {idx}: URL no autorizada')
        elif kind=='ciaraSignIn':
            lines.append('    # Acceso CIARÁ gestionado por TQA con variables de entorno privadas')
            lines.append('    # Configurar CIARA_TEST_USERNAME y CIARA_TEST_PASSWORD en el equipo local')
        elif kind in ('ciaraBrowse', 'ciaraRepeat'):
            lines.append('    # Recorrido interno de TQA: requiere implementación adicional en Robot')
        elif kind=='type':
            if is_sensitive(cmd):
                lines.append('    ${CLAVE_PRUEBA}    Get Environment Variable    TQA_TEST_PASSWORD')
                lines.append(f'    Input Password    {locator}    ${{CLAVE_PRUEBA}}')
            else:
                lines.append(f'    Input Text    {locator}    {val}')
        elif kind=='click': lines.append(f'    Click Element    {locator}')
        elif kind in ('assertText','verifyText'): lines.append(f'    Element Text Should Be    {locator}    {val}')
        elif kind in ('assertTitle','verifyTitle'): lines.append(f'    Title Should Be    {raw}')
        elif kind in ('assertElementPresent','verifyElementPresent'): lines.append(f'    Page Should Contain Element    {locator}')
        elif kind=='waitForElementVisible': lines.append(f'    Wait Until Element Is Visible    {locator}    timeout=8s')
        elif kind=='check': lines.append(f'    Select Checkbox    {locator}')
        elif kind=='uncheck': lines.append(f'    Unselect Checkbox    {locator}')
        elif kind=='select' and val.startswith('label='): lines.append(f'    Select From List By Label    {locator}    {val[6:]}')
        elif kind=='pause': lines.append(f'    Sleep    {min(int(raw) if raw.isdigit() else 0,3000)/1000} s')
        else: lines.append(f'    # Paso {idx}: {kind} requiere conversión manual a Robot Framework')
    lines.append('    [Teardown]    Close Browser')
    lines.append('')
    return '\n'.join(lines)


def run_side_test(project: dict, test_id: str, target: str, base_url: str, evidence_dir: Path, progress=None, view_mode: str | None = None) -> dict:
    case = next((t for t in project['tests'] if t['id'] == test_id), None)
    if not case:
        raise SideValidationError('Caso .side no encontrado')
    started = time.monotonic()
    commands = [c for c in case['commands'] if c.get('command') and not c.get('comment', '').startswith('TQA:OMITIR')]
    name = str(case.get('name', test_id))[:130]
    prefix = f'SIDE_{re.sub(r"[^a-zA-Z0-9_-]", "_", test_id)[:60]}'
    metadata = case.get('tqa', {})
    report = {'id': prefix, 'name': name, 'kind': metadata.get('kind', 'Funcionales'), 'suite': metadata.get('category', 'Selenium IDE'),
              'objective': f'Reproducir los pasos grabados por Selenium IDE: {name}',
              'preconditions': f'Chrome instalado y aplicación autorizada disponible ({target}). Usar datos de prueba.',
              'expected': ('Todos los comandos y la medición configurada deben cumplir sus condiciones.' if metadata.get('checks') else 'Todos los comandos compatibles y las aserciones grabadas deben completarse.'),
              'planned_steps': [str(c['command']) + ': ' + str(c.get('target',''))[:140] for c in commands] + (['Evaluar métrica no funcional: '+metadata.get('template','')] if metadata.get('checks') else []),
              'steps': [], 'evidence': [], 'artifacts': [], 'duration_s': 0.,
              'status': 'NOT RUN', 'observation': '', 'locators': [], 'video': None,
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    driver = None
    frames = []
    # Eventos de progreso visibles antes de que termine la prueba.
    def notify(kind, **payload):
        if progress:
            try:
                progress({'type': kind, 'case': prefix, 'name': name, **payload})
            except Exception:
                pass  # Un error al actualizar la vista nunca debe cambiar PASS/FAIL.
    notify('case_start', total=len(commands), name=name)
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        options = Options()
        options.add_argument('--window-size=1200,800')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-extensions')
        # Perfil limpio; no se utilizan sesiones o contraseñas personales del navegador.
        import os
        if (view_mode == 'integrated') or (view_mode is None and os.getenv('SELENIUM_HEADLESS', 'false').lower() == 'true'):
            options.add_argument('--headless=new')
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(25)
        notify('browser_open', status='EN CURSO', observed='Chrome abierto con Selenium WebDriver')
        # Permite apreciar los clics y entradas en la ventana visible durante una demostración.
        try:
            delay_ms = max(0, min(int(os.getenv('SELENIUM_STEP_DELAY_MS', '750')), 3000))
        except ValueError:
            delay_ms = 750
        for i, command in enumerate(commands, 1):
            action = str(command['command'])
            started_step = time.monotonic()
            notify('step_start', step=i, total=len(commands), command=action,
                   target=str(command.get('target', ''))[:125], status='EN CURSO')
            result = {'action': action + ' — ' + str(command.get('target', ''))[:125],
                      'expected': 'Comando compatible y condición satisfecha', 'observed': '', 'status': 'PASS',
                      'locator': '', 'xpath': ''}
            if action not in SUPPORTED:
                report['status'] = 'NOT RUN'
                result['status'] = 'NOT RUN'
                result['observed'] = f'Comando .side no compatible: {action}'
                report['steps'].append(result)
                report['observation'] = result['observed']
                notify('step_done', step=i, total=len(commands), command=action,
                       status='NOT RUN', observed=result['observed'])
                break
            try:
                if action in ('ciaraSignIn', 'ciaraBrowse', 'ciaraRepeat'):
                    if target == 'Demo local' or target != metadata.get('target') or not metadata.get('ciara_login'):
                        raise SideValidationError('Comando reservado para suites internas CIARÁ.')
                    if action == 'ciaraSignIn':
                        details = _ciara_sign_in(driver, base_url)
                    elif action == 'ciaraBrowse':
                        details = _ciara_browse(driver, base_url, int(command.get('value') or 4))
                    else:
                        details = _ciara_repeat(driver, base_url)
                    used, xp = '', ''
                elif action in ('assertTitle', 'verifyTitle'):
                    _observe_driver_origin(driver, base_url)
                    if driver.title != str(command.get('target','')):
                        raise SideAssertionFailed('El título de página no coincide con el esperado')
                    details, used, xp = 'Título correcto', '', ''
                else:
                    details, used, xp = _execute_command(driver, command, base_url)
                result['observed'] = details
                result['locator'], result['xpath'] = used, xp
                if used:
                    report['locators'].append({'step': i, 'command': action, 'selector': used,
                                               'xpath': xp, 'verified': bool(xp)})
            except SideAssertionFailed as exc:
                result['observed'] = str(exc)[:260]
                result['status'] = 'FAIL'
                report['status'] = 'FAIL'
                report['observation'] = f'Falló el paso {i}: {result["observed"]}'
            except SideValidationError as exc:
                result['observed'] = str(exc)[:260]
                result['status'] = 'NOT RUN'
                report['status'] = 'NOT RUN'
                report['observation'] = f'Ejecución detenida por seguridad: {result["observed"]}'
            except Exception as exc:
                # Errores de elementos ausentes/estado inválido son fallas observables de la prueba.
                result['observed'] = ('Error interno al autenticar: ' + type(exc).__name__ if action == 'ciaraSignIn'
                                      else f'{type(exc).__name__}: {str(exc)[:170]}')
                result['status'] = 'FAIL'
                report['status'] = 'FAIL'
                report['observation'] = f'Falló el paso {i}: {result["observed"]}'
            result['duration_s'] = round(time.monotonic() - started_step, 3)
            try:
                fname = f'{prefix}_paso_{i:02d}.png'
                driver.save_screenshot(str(evidence_dir / fname))
                frames.append(evidence_dir / fname)
                # Se muestran sólo algunas capturas en PDF/HTML para evitar informes enormes.
                if i < 9 or result['status'] != 'PASS':
                    report['evidence'].append(fname)
                result['screenshot'] = fname
            except Exception:
                pass
            report['steps'].append(result)
            notify('step_done', step=i, total=len(commands), command=action,
                   target=str(command.get('target', ''))[:125], status=result['status'],
                   observed=result['observed'], screenshot=result.get('screenshot'),
                   xpath=result.get('xpath', ''), elapsed_s=result['duration_s'])
            if delay_ms and result['status'] == 'PASS':
                time.sleep(delay_ms / 1000)
            if result['status'] != 'PASS':
                break
        else:
            report['status'] = 'PASS'
            report['observation'] = f'{len(commands)} comandos de Selenium IDE ejecutados correctamente.'
        # Para casos no funcionales, no confundir una navegación exitosa con la
        # validación del requisito. Las mediciones son reales y obligatorias.
        if report['status'] == 'PASS' and metadata.get('checks'):
            from .selenium_generator import measure_check
            step_num = len(commands)+1
            notify('step_start', step=step_num, total=step_num, command='Medición no funcional', status='EN CURSO')
            stamp = time.monotonic()
            try:
                measurement = measure_check(driver, metadata)
                extra_status, observed = measurement['status'], measurement['observed']
            except Exception as exc:
                extra_status, observed = 'NOT RUN', f'No se pudo medir el criterio de prueba: {type(exc).__name__}.'
            extra = {'action': 'Evaluar '+metadata.get('template', 'criterio'),
                     'expected': 'Cumplir el límite o verificación seleccionados',
                     'observed': observed, 'status': extra_status,
                     'duration_s': round(time.monotonic()-stamp,3), 'locator': '', 'xpath': ''}
            try:
                fname = f'{prefix}_criterio_{step_num:02d}.png'
                driver.save_screenshot(str(evidence_dir/fname))
                frames.append(evidence_dir/fname)
                extra['screenshot'] = fname
                report['evidence'].append(fname)
            except Exception:
                pass
            report['steps'].append(extra)
            report['status'] = extra_status
            report['observation'] = observed
            notify('step_done', step=step_num, total=step_num, command='Medición no funcional',
                   status=extra_status, observed=observed, screenshot=extra.get('screenshot'), elapsed_s=extra['duration_s'])
    except ImportError:
        report['status'] = 'NOT RUN'
        report['observation'] = 'Falta Selenium; ejecuta instalar_selenium_windows.bat.'
    except Exception as exc:
        report['status'] = 'NOT RUN'
        report['observation'] = f'Error de infraestructura Selenium/Chrome: {type(exc).__name__}. Comprueba la instalación de Chrome y Selenium Manager.'
    finally:
        if driver is not None:
            try: driver.quit()
            except Exception: pass
        report['duration_s'] = round(time.monotonic() - started, 3)
        report['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        notify('case_done', status=report['status'], observed=report['observation'],
               elapsed_s=report['duration_s'])
        try:
            feature_name = f'{prefix}_gherkin.feature'
            robot_name = f'{prefix}_robot_generado.robot'
            (evidence_dir / feature_name).write_text(gherkin_from_commands(case), encoding='utf-8')
            (evidence_dir / robot_name).write_text(robot_from_commands(case,base_url,report['locators']),encoding='utf-8')
            report['artifacts'].extend([feature_name,robot_name])
        except Exception:
            pass
        try:
            locname = f'{prefix}_xpath_validados.json'
            (evidence_dir / locname).write_text(json.dumps(report['locators'], ensure_ascii=False, indent=2), encoding='utf-8')
            report['artifacts'].append(locname)
        except Exception:
            pass
        if frames:
            name_video = f'{prefix}_video.mp4'
            if _make_video(frames, evidence_dir / name_video):
                report['video'] = name_video
                report['artifacts'].append(name_video)
        # Registro legible de comandos y resultados (se elimina cualquier valor de contraseña).
        try:
            filename = f'{prefix}_pasos.json'
            safe_steps = [{'action': s['action'], 'status': s['status'], 'observed': s['observed'],
                           'xpath': s.get('xpath', ''), 'duration_s': s.get('duration_s', 0)}
                          for s in report['steps']]
            (evidence_dir / filename).write_text(json.dumps(safe_steps, ensure_ascii=False, indent=2), encoding='utf-8')
            report['artifacts'].append(filename)
        except Exception:
            pass
    return report

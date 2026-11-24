"""Modo sencillo para Selenium, construido sobre el motor real de TQA v7.

Únicamente ejecuta pruebas de lectura/inspección contra orígenes configurados
por el administrador en .env. No escribe en bases de datos ni envía formularios.
"""
import csv
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .robot_engine import validate_path
from .selenium_suites import make_general, make_screen
from .selenium_generator import make_test
from .selenium_discovery import crawl_site, inspect_page

router = APIRouter(prefix='/api/simple', tags=['Modo sencillo'])

TYPES = [
    {'id': 'rapida', 'name': 'Smoke', 'group': 'Funcionales', 'detail': 'Inicia sesión en CIARÁ y comprueba que se abre el panel interno.', 'icon': 'zap'},
    {'id': 'navegacion', 'name': 'Navegación', 'group': 'Funcionales', 'detail': 'Recorre hasta cuatro páginas públicas internas.', 'icon': 'compass'},
    {'id': 'regresion', 'name': 'Regresión básica', 'group': 'Funcionales', 'detail': 'Comprueba de nuevo hasta ocho pantallas y sus elementos.', 'icon': 'repeat'},
    {'id': 'login', 'name': 'Sanity del login', 'group': 'Funcionales', 'detail': 'Ingresa a CIARÁ con una cuenta de prueba y verifica el acceso al panel interno.', 'icon': 'lock'},
    {'id': 'rendimiento', 'name': 'Rendimiento de página', 'group': 'No funcionales', 'detail': 'Mide una navegación de Chrome; no es una prueba de carga.', 'icon': 'clock'},
    {'id': 'accesibilidad', 'name': 'Accesibilidad básica', 'group': 'No funcionales', 'detail': 'Revisa etiquetas de campos, imágenes y botones.', 'icon': 'eye'},
    {'id': 'responsive', 'name': 'Diseño adaptable / móvil', 'group': 'No funcionales', 'detail': 'Detecta desbordamiento horizontal a 375 px.', 'icon': 'smartphone'},
    {'id': 'estabilidad', 'name': 'Estabilidad básica', 'group': 'No funcionales', 'detail': 'Abre tres veces la misma página y valida su cuerpo.', 'icon': 'shield'},
    {'id': 'api_estado', 'name': 'Estado de API', 'group': 'Funcionales', 'detail': 'Comprueba GET /api/ml/estado de CIARÁ. Requiere que exista este endpoint.', 'icon': 'link'},
    {'id': 'integracion_api', 'name': 'Integración', 'group': 'Funcionales', 'detail': 'Comprueba POST /api/ml/predecir con datos de prueba. Requiere ese endpoint y un servicio de pruebas autorizado.', 'icon': 'link'},
    {'id': 'retesting', 'name': 'Retesting', 'group': 'Funcionales', 'detail': 'Repite el último caso FAIL de CIARÁ; requiere que exista un caso fallido real en el historial.', 'icon': 'repeat'},
    {'id': 'carga_api', 'name': 'Carga controlada (API HTTP)', 'group': 'No funcionales', 'detail': 'Envía 20 GET a /api/ml/estado, hasta 4 concurrentes. No utiliza Selenium; solo en CIARÁ local de pruebas.', 'icon': 'activity'},
    {'id': 'estres_api', 'name': 'Estrés limitado (API HTTP)', 'group': 'No funcionales', 'detail': 'Envía 40 GET a /api/ml/estado, hasta 8 concurrentes. Solo en entorno local autorizado.', 'icon': 'gauge'},
    {'id': 'resistencia_api', 'name': 'Resistencia breve (API HTTP)', 'group': 'No funcionales', 'detail': 'Hace 12 solicitudes GET espaciadas durante unos 6 segundos.', 'icon': 'clock'},
]
MAP = {x['id']: x for x in TYPES}


def core():
    # Se importa diferido: evita el ciclo cuando app.main registra este router.
    from . import main
    return main


class SimpleRunInput(BaseModel):
    target: str = Field(min_length=1, max_length=50)
    test_type: str = Field(min_length=1, max_length=32)
    path: str = Field(default='/', max_length=160)
    visible: bool = True
    email: str = Field(default='', max_length=254)
    selected_names: list[str] | None = None


class QuickRunInput(BaseModel):
    test_type: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=5, max_length=254)
    selected_names: list[str] | None = None

    @classmethod
    def _check_email(cls, value: str) -> str:
        from .main import RunInput
        return RunInput.email_valid(value)

    from pydantic import field_validator
    @field_validator('selected_names')
    @classmethod
    def validate_cases(cls, values):
        if values is not None and (not values or len(values) > 20 or len(values) != len(set(values)) or any(not name.strip() or len(name) > 200 for name in values)):
            raise ValueError('Selecciona entre 1 y 20 casos diferentes')
        return values

    @field_validator('email')
    @classmethod
    def validate_email(cls, value: str) -> str:
        return cls._check_email(value)


def ciara_target():
    app = core()
    preferred = (app.os.getenv('TQA_WEB_NAME', '').strip() or 'CIARÁ Web')[:50]
    if 'CIARÁ Web' in app.TARGETS:
        return 'CIARÁ Web'
    if app.os.getenv('TQA_WEB_URL', '').strip() and preferred in app.TARGETS:
        return preferred
    if 'CIARÁ' in app.TARGETS:
        return 'CIARÁ'
    raise HTTPException(422, 'Configura CIARA_API_URL o TQA_WEB_URL en .env')


def _looks_like_laravel_welcome(screen: dict) -> bool:
    """Un HTTP 200 con la portada de Laravel NO es una prueba Smoke de CIARÁ."""
    title = str(screen.get('title', '')).strip().lower()
    return title in ('laravel', 'laravel 13', 'welcome to laravel') and int(screen.get('forms', 0)) == 0


def _resolve_ciara_path(target: str, preferred: str | None = None) -> tuple[str, dict]:
    app = core()
    base = app.TARGETS[target]
    first = preferred or (app.CIARA_WEB_PATH if target != 'CIARÁ' else '/')
    candidates = list(dict.fromkeys([first, '/login', '/admin/login', '/inicio-sesion', '/']))
    saw_welcome = False
    problem = None
    for path in candidates:
        try:
            screen = inspect_page(base, validate_path(path))
            if _looks_like_laravel_welcome(screen):
                saw_welcome = True
                continue
            # Un HTML accesible no garantiza login exitoso ni módulos privados.
            return path, screen
        except (httpx.HTTPError, ValueError) as exc:
            problem = type(exc).__name__
            continue
    if saw_welcome:
        raise ValueError('El puerto responde, pero solo muestra la portada de Laravel. CIARÁ no está en esa dirección. Pulsa «Cambiar URL» y escribe la dirección REAL donde abre CIARÁ (por ejemplo http://127.0.0.1:8000/login).')
    raise ValueError('No se encontró una pantalla web de CIARÁ. Comprueba que su servidor está encendido y configura la URL correcta. ' + (problem or ''))


class WebConnectionInput(BaseModel):
    url: str = Field(min_length=10, max_length=190)


@router.post('/configure-web')
def configure_web(spec: WebConnectionInput):
    """Solo guarda direcciones HTTP(S) del propio equipo para evitar SSRF/redes externas."""
    app = core()
    raw = spec.url.strip()
    parts = urlsplit(raw)
    try:
        port = parts.port
    except ValueError:
        raise HTTPException(422, 'El puerto de la URL no es válido.') from None
    if (parts.scheme not in ('http', 'https') or parts.hostname not in ('localhost', '127.0.0.1', '::1')
        or port is None or parts.username or parts.password or parts.query or parts.fragment
        or '\\' in raw or any(ord(x) < 32 for x in raw)):
        raise HTTPException(422, 'Ingresa una URL local con puerto, por ejemplo http://127.0.0.1:8000/login (sin usuario ni contraseña).')
    try:
        path = validate_path(parts.path or '/')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    origin = urlunsplit((parts.scheme, parts.netloc, '', '', '')).rstrip('/')
    data = json.dumps({'url': origin, 'path': path}, ensure_ascii=False, indent=2)
    # Archivo separado del .env: NO modifica ni expone credenciales SMTP.
    temp = app.CIARA_WEB_CONFIG.with_suffix('.json.tmp')
    try:
        temp.write_text(data, encoding='utf-8')
        temp.replace(app.CIARA_WEB_CONFIG)
    except OSError:
        raise HTTPException(500, 'No se pudo guardar la configuración local de CIARÁ.') from None
    app.TARGETS['CIARÁ Web'] = origin
    app.CIARA_WEB_PATH = path
    try:
        resolved, screen = _resolve_ciara_path('CIARÁ Web', path)
        return {'saved': True, 'selenium_ready': True, 'url': origin + resolved,
                'message': 'CIARÁ listo para pruebas web. Pantalla: ' + (screen.get('title') or resolved)}
    except ValueError as exc:
        return {'saved': True, 'selenium_ready': False, 'url': origin + path, 'message': str(exc)}


@router.get('/setup')
def setup():
    app = core()
    targets = list(app.TARGETS)
    ciara = ciara_target()
    return {'targets': targets, 'default_target': ciara, 'ciara_url': app.TARGETS[ciara],
            'types': TYPES, 'version': '8.5', 'smtp_configured': app.smtp_available(),
            'ciara_login_configured': ciara_auth_configured(),
            'notice': 'El acceso a CIARÁ usa variables de entorno privadas. El correo solo recibe el reporte.'}


@router.get('/check')
def check(target: str, path: str = '/'):
    app = core()
    if target not in app.TARGETS:
        raise HTTPException(422, 'Aplicación no configurada')
    if target not in ('CIARÁ', 'CIARÁ Web'):
        # Compatibilidad con el comprobador genérico usado por TQA v6/v7.
        try:
            base = app.TARGETS[target].rstrip('/')
            with httpx.Client(timeout=7, trust_env=False, follow_redirects=False) as client:
                result = client.get(base + validate_path(path))
            return {'connected': result.status_code < 400,
                    'selenium_ready': result.status_code < 400 and 'text/html' in result.headers.get('content-type','').lower(),
                    'status_code': result.status_code, 'message': ('Conexión HTML disponible' if 'text/html' in result.headers.get('content-type','').lower() else 'La respuesta es una API/datos, no HTML') if result.status_code < 400 else 'Error HTTP'}
        except (ValueError, httpx.HTTPError):
            return {'connected': False, 'selenium_ready': False, 'message': 'No se pudo conectar'}
    try:
        selected, screen = _resolve_ciara_path(target, path if path != '/' else None)
        return {'connected': True, 'selenium_ready': True, 'resolved_path': selected,
                'url': app.TARGETS[target] + selected, 'title': screen.get('title',''),
                'message': 'Pantalla web disponible: ' + (screen.get('title') or selected) + '. Las funciones privadas requieren iniciar sesión.'}
    except (ValueError, httpx.HTTPError) as exc:
        return {'connected': False, 'selenium_ready': False, 'needs_configuration': True,
                'url': app.TARGETS[target], 'message': str(exc)}


def ciara_auth_configured() -> bool:
    app = core()
    return bool(app.os.getenv('CIARA_TEST_USERNAME', '').strip() and app.os.getenv('CIARA_TEST_PASSWORD', ''))


def _build_authenticated_project(spec, app):
    """Casos con acceso real. Los secretos NO se almacenan en el proyecto SIDE."""
    from .selenium_suites import _command, _project, _new_id
    typ = spec.test_type
    definition = MAP[typ]
    path = validate_path(spec.path)
    commands = [_command('open', path), _command('ciaraSignIn'), _command('assertElementPresent', 'css=body')]
    if typ == 'navegacion':
        commands.append(_command('ciaraBrowse', value='4'))
    elif typ == 'regresion':
        commands.append(_command('ciaraBrowse', value='8'))
    elif typ == 'responsive':
        commands.append(_command('setWindowSize', '375x812'))
    elif typ == 'estabilidad':
        commands.append(_command('ciaraRepeat'))
    category = ('Sanity' if typ == 'login' else 'Smoke' if typ == 'rapida'
                else 'Regresión' if typ == 'regresion' else 'Navegación' if typ == 'navegacion'
                else definition['name'])
    nonfunctional = typ in ('rendimiento', 'accesibilidad', 'responsive', 'estabilidad')
    templates = {'rendimiento':'tiempo', 'accesibilidad':'accesibilidad',
                 'responsive':'responsive'}
    case = {'id':'tqa_'+_new_id(), 'name':category+' · CIARÁ con sesión iniciada',
            'commands':commands,
            'tqa':{'target':spec.target, 'kind':definition['group'], 'category':category,
                   'ciara_login':True, 'checks':typ in templates,
                   'template':templates.get(typ,'autenticacion'), 'max_ms':3000,
                   'page_path':path}}
    return _project('TQA | '+category+' · CIARÁ autenticado', [case], category)


def _build_project(spec, app):
    if spec.target == ciara_target() and ciara_auth_configured() and spec.test_type in (
        'rapida', 'login', 'navegacion', 'regresion', 'rendimiento',
        'accesibilidad', 'responsive', 'estabilidad'):
        return _build_authenticated_project(spec, app)
    # La herramienta principal sigue siendo Selenium WebDriver del sistema original.
    target, path, t = spec.target, validate_path(spec.path), spec.test_type
    if t in ('navegacion', 'regresion'):
        scanned = crawl_site(app.TARGETS[target], path, 4 if t == 'navegacion' else 8)
        project = make_general(target=target, scanned=scanned)
        project['name'] = ('TQA · Navegación' if t == 'navegacion' else 'TQA · Regresión básica')
        for case in project['tests']:
            case['tqa']['category'] = 'Navegación' if t == 'navegacion' else 'Regresión'
        return project
    if t in ('rapida', 'login'):
        screen = inspect_page(app.TARGETS[target], path)
        category = 'Smoke' if t == 'rapida' else 'Sanity'
        name = 'Smoke · ' + path if t == 'rapida' else 'Sanity del login · ' + path
        project = make_screen(target=target, kind='Funcionales', category=category, name=name, screen=screen)
        if t == 'login':
            # Validación real por Selenium: debe existir un campo de contraseña.
            project['tests'][0]['commands'].append({'id':uuid.uuid4().hex[:12], 'comment':'',
                'command':'assertElementPresent', 'target':'css=input[type=password]', 'targets':[], 'value':''})
        return project
    params = {
        'rendimiento': ('Rendimiento', 'tiempo'),
        'accesibilidad': ('Accesibilidad', 'accesibilidad'),
        'responsive': ('Responsividad', 'responsive'),
        'estabilidad': ('Estabilidad', 'repetir'),
    }
    category, template = params[t]
    # Inspección previa impide declarar Selenium satisfactorio si se apunta a un API JSON.
    inspect_page(app.TARGETS[target], path)
    return make_test(target=target, kind='No funcionales', category=category,
                     template=template, name=MAP[t]['name'] + ' · ' + path,
                     page_path=path, max_ms=3000)




def _latest_failed_ciara(app):
    """Recupera un caso realmente FAIL de CIARÁ; nunca usa fallos de la demo local."""
    ciara_names = {'CIARÁ', ciara_target()}
    with app.connect() as con:
        rows = con.execute("SELECT r.id,r.target,r.kind,r.side_project_id,r.view_mode,r.created_at,"
                           "z.case_id,z.data_json FROM runs r JOIN results z ON z.run_id=r.id "
                           "WHERE r.status IN ('FINALIZADA','FALLIDA') ORDER BY r.created_at DESC LIMIT 150").fetchall()
    for row in rows:
        if row['target'] not in ciara_names:
            continue
        try:
            case = json.loads(row['data_json'])
        except (TypeError,ValueError):
            continue
        if case.get('status')=='FAIL':
            return dict(row),case
    return None,None


@router.get('/preview')
def preview(test_type: str):
    """Muestra qué casos existen sin fingir resultados; el usuario puede desmarcar casos."""
    app=core()
    apis = {
        'api_estado':'TC-CIA-SMK', 'integracion_api':'TC-CIA-INT',
        'carga_api':'TC-LOAD-001', 'estres_api':'TC-STR-001', 'resistencia_api':'TC-SOAK-001',
    }
    if test_type in apis:
        from .catalog import CATALOG
        case=CATALOG[apis[test_type]]
        return {'cases':[{'name':case.name,'id':case.id,'expected':case.expected}], 'engine':'HTTP'}
    if test_type=='retesting':
        row,case=_latest_failed_ciara(app)
        if not row:
            raise HTTPException(422,'No hay casos fallidos de CIARÁ en el historial para repetir.')
        return {'cases':[{'name':case.get('name',row['case_id']),'id':row['case_id']}], 'engine':'Anterior'}
    if test_type not in MAP:
        raise HTTPException(422,'Tipo de prueba no permitido')
    try:
        target=ciara_target()
        found_path, _ = _resolve_ciara_path(target)
        spec=SimpleRunInput(target=target,test_type=test_type, path=found_path, visible=True, email='')
        project=_build_project(spec,app)
    except (ValueError,httpx.HTTPError) as exc:
        raise HTTPException(422,str(exc)[:220]) from None
    return {'cases':[{'name':str(t.get('name','Caso')),'id':str(t.get('id',''))} for t in project.get('tests',[])], 'engine':'Selenium WebDriver'}


def _launch_retesting(app,spec,background_tasks):
    row,case=_latest_failed_ciara(app)
    if not row:
        raise HTTPException(422,'No hay un caso FAIL previo de CIARÁ. Primero ejecuta una suite y registra el fallo.')
    if spec.selected_names and spec.selected_names != [case.get('name',row['case_id'])]:
        raise HTTPException(422,'El caso fallido cambió. Actualiza la selección de casos.')
    with app.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        busy=con.execute("SELECT COUNT(*) FROM runs WHERE status IN ('PENDIENTE','EN CURSO')").fetchone()[0]
        if busy:
            raise HTTPException(409,'Ya hay otra ejecución en curso.')
        run_id=uuid.uuid4().hex[:12].upper()
        con.execute("INSERT INTO runs (id,target,kind,suite,email,status,created_at,selected_cases,side_project_id,view_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id,row['target'],row['kind'],'Retesting · CIARÁ',spec.email,'PENDIENTE',app.now(),
                     json.dumps([row['case_id']]),row['side_project_id'] or '',row['view_mode'] or 'integrated'))
    background_tasks.add_task(app.execute_run,run_id)
    return {'id':run_id,'status':'PENDIENTE','cases':1,'type':'retesting',
            'target':row['target'],'source_run':row['id']}

@router.post('/start', status_code=202)
def start(spec: SimpleRunInput, background_tasks: BackgroundTasks):
    app = core()
    if spec.target not in app.TARGETS:
        raise HTTPException(422, 'Selecciona una aplicación configurada')
    if spec.test_type not in MAP:
        raise HTTPException(422, 'Selecciona un tipo de prueba compatible')
    try:
        validate_path(spec.path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with app.connect() as con:
        running = con.execute("SELECT COUNT(*) FROM runs WHERE status IN ('PENDIENTE', 'EN CURSO')").fetchone()[0]
    if running:
        raise HTTPException(409, 'Ya hay una prueba en ejecución. Espera a que finalice.')
    # Generar tests verificados a partir de la web real, sin modificar CIARÁ.
    try:
        project = _build_project(spec, app)
    except (ValueError, httpx.HTTPError) as exc:
        message = str(exc)[:220]
        if 'HTML' in message or 'no se encontraron' in message.lower():
            message += ' Comprueba si esta URL corresponde al frontend web de CIARÁ, y no solo a la API.'
        raise HTTPException(422, message) from None
    if spec.selected_names is not None:
        expected=set(spec.selected_names)
        available={str(t.get('name','')) for t in project.get('tests',[])}
        if not expected or not expected.issubset(available):
            raise HTTPException(422, 'La selección de casos cambió. Actualiza la lista antes de ejecutar.')
        project['tests']=[t for t in project['tests'] if str(t.get('name','')) in expected]
    if not project.get('tests'):
        raise HTTPException(422, 'No se encontraron casos para ejecutar.')
    project_id = uuid.uuid4().hex[:12].upper()
    run_id = uuid.uuid4().hex[:12].upper()
    case_ids = ['SIDE_' + test['id'] for test in project['tests']]
    groups = {x.get('tqa', {}).get('kind', 'Funcionales') for x in project['tests']}
    kind = next(iter(groups))
    with app.connect() as con:
        # Se vuelve a comprobar bajo el bloqueo de escritura de SQLite para evitar
        # dobles pulsaciones en la interfaz al iniciar.
        con.execute('BEGIN IMMEDIATE')
        busy = con.execute("SELECT COUNT(*) FROM runs WHERE status IN ('PENDIENTE', 'EN CURSO')").fetchone()[0]
        if busy:
            raise HTTPException(409, 'Ya hay una ejecución en curso.')
        con.execute('INSERT INTO side_projects (id,name,content_json,created_at) VALUES (?,?,?,?)',
                    (project_id, project['name'], json.dumps(project, ensure_ascii=False), app.now()))
        con.execute('''INSERT INTO runs (id,target,kind,suite,email,status,created_at,selected_cases,side_project_id,view_mode)
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (run_id, spec.target, kind, 'Selenium · ' + MAP[spec.test_type]['name'], spec.email,
                     'PENDIENTE', app.now(), json.dumps(case_ids), project_id,
                     'visible' if spec.visible else 'integrated'))
    background_tasks.add_task(app.execute_run, run_id)
    return {'id': run_id, 'status': 'PENDIENTE', 'cases': len(case_ids),
            'type': spec.test_type, 'target': spec.target}


@router.post('/launch', status_code=202)
def launch_quick(spec: QuickRunInput, background_tasks: BackgroundTasks):
    # Pruebas API reales ya existentes en TQA. Se ejecutan mediante HTTP, no Selenium.
    # Esto evita afirmar incorrectamente que un navegador simula concurrencia.
    api_types = {
        'api_estado': ('Funcionales', 'Smoke', 'TC-CIA-SMK'),
        'integracion_api': ('Funcionales', 'Integration', 'TC-CIA-INT'),
        'carga_api': ('No funcionales', 'Carga', 'TC-LOAD-001'),
        'estres_api': ('No funcionales', 'Estres', 'TC-STR-001'),
        'resistencia_api': ('No funcionales', 'Resistencia', 'TC-SOAK-001'),
    }
    if spec.test_type=='retesting':
        return _launch_retesting(core(),spec,background_tasks)
    if spec.test_type in api_types:
        app = core()
        kind, suite, case_id = api_types[spec.test_type]
        from .catalog import CATALOG
        if spec.selected_names and spec.selected_names != [CATALOG[case_id].name]:
            raise HTTPException(422,'La selección no corresponde al caso de esta suite.')
        # La API configurada de CIARÁ puede ser distinta del frontend.
        if 'CIARÁ' not in app.TARGETS:
            raise HTTPException(422, 'Configura CIARA_API_URL en .env')
        return app.start_run(app.RunInput(target='CIARÁ', kind=kind, suite=suite,
                                          email=spec.email, case_ids=[case_id]), background_tasks)
    # La interfaz única no pregunta aplicación ni rutas técnicas.
    browser_target = ciara_target()
    try:
        browser_path, _ = _resolve_ciara_path(browser_target)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(422, str(exc)[:600]) from None
    return start(SimpleRunInput(target=browser_target, test_type=spec.test_type,
                                path=browser_path, visible=True, email=spec.email,
                                selected_names=spec.selected_names), background_tasks)


@router.get('/history')
def history():
    app = core()
    with app.connect() as con:
        rows = con.execute("SELECT id,target,kind,suite,status,global_status,created_at,finished_at "
                           "FROM runs WHERE suite LIKE 'Selenium · %' "
                           "ORDER BY created_at DESC LIMIT 12").fetchall()
    return [dict(row) for row in rows]


def _get_finished(run_id):
    app = core()
    run = app.get_run(run_id)
    if run['status'] not in ('FINALIZADA', 'FALLIDA'):
        raise HTTPException(409, 'La prueba todavía no ha terminado')
    return run


def _csv_bytes(run):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Ejecucion', 'Aplicacion', 'Suite', 'Caso', 'Estado', 'Duracion segundos', 'Observacion'])
    for row in run['cases']:
        writer.writerow([run['id'], run['target'], run['suite'], row.get('name', ''),
                         row.get('status', ''), row.get('duration_s', 0), row.get('observation', '')])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


@router.get('/runs/{run_id}/csv')
def csv_report(run_id: str):
    run = _get_finished(run_id)
    return Response(_csv_bytes(run), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="TQA_{run_id}_resultados.csv"'})


@router.get('/runs/{run_id}/json')
def json_report(run_id: str):
    run = _get_finished(run_id)
    return Response(json.dumps(run, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="TQA_{run_id}_resultados.json"'})


@router.get('/runs/{run_id}/zip')
def full_report(run_id: str):
    app = core()
    run = _get_finished(run_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('resultados.csv', _csv_bytes(run))
        zip_file.writestr('resultados.json', json.dumps(run, ensure_ascii=False, indent=2))
        for file in [app.REPORTS / f'TQA_{run_id}_detallado.pdf',
                     app.REPORTS / f'TQA_{run_id}_resumen.html']:
            if file.is_file():
                zip_file.write(file, arcname=file.name)
        folder = app.EVIDENCE / run_id
        if folder.is_dir():
            # Máximo 120 evidencias, 25 MB en total para no saturar la interfaz.
            total = 0
            for file in sorted(folder.iterdir())[:120]:
                if file.is_file() and not file.is_symlink() and total + file.stat().st_size <= 25_000_000:
                    total += file.stat().st_size
                    zip_file.write(file, arcname='evidencias/' + file.name)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='application/zip',
                             headers={'Content-Disposition': f'attachment; filename="TQA_{run_id}_completo.zip"'})

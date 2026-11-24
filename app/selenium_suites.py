"""Generación controlada de proyectos Selenium (.side) con verificaciones observables.

Los proyectos se pueden abrir en Selenium IDE. TQA los ejecuta mediante
Selenium WebDriver, porque una extensión del navegador no puede ser llamada
como API desde una web local. Las suites generales son de solo lectura.
"""
import json
import re
import uuid
from .robot_engine import validate_path
from .selenium_ide import parse_side

CUSTOM_CATEGORIES = {
    'Funcionales': ['Smoke','Sanity','Regresión','Integración','E2E','Personalizadas','Recorrido general'],
    'No funcionales': ['Rendimiento','Accesibilidad','Responsividad','Estabilidad','Personalizadas'],
}
SAFE_COMMANDS = {'open','assertElementPresent','assertElementNotPresent', 'waitForElementVisible',
                 'assertText','assertTitle','assertValue','click','type','select','check','uncheck','pause',
                 'setWindowSize'}
INTERACTIVE = {'click','type','select','check','uncheck'}
SELECTOR_ACTIONS = {'assertElementPresent','assertElementNotPresent','waitForElementVisible',
                    'assertText','assertValue','click','type','select','check','uncheck'}
ASSERTIONS = {'assertElementPresent','assertElementNotPresent','waitForElementVisible',
              'assertText','assertTitle','assertValue'}


def _new_id(): return uuid.uuid4().hex[:12]
def _command(action, target='', value=''):
    return {'id':_new_id(),'comment':'','command':action,'target':target,'targets':[],'value':value}


def _project(name: str, tests: list[dict], category: str):
    ids=[t['id'] for t in tests]
    project={'id':_new_id(),'version':'3.17.2', 'name':name[:120], 'url':'',
             'tests':tests,'suites':[{'id':_new_id(),'name':category,'persistSession':False,
                                    'parallel':False,'timeout':300,'tests':ids}], 'urls':[]}
    parse_side(json.dumps(project,ensure_ascii=False).encode('utf-8'))
    return project


def _safe_selector(s: str):
    s=s.strip()
    if len(s)>190 or not re.fullmatch(r'(?s)(?:id=|name=|css=|xpath=|//)[^\x00-\x1f]{1,185}', s):
        raise ValueError('Localizador no válido: usa id=..., name=..., css=..., xpath=... o //...')
    if re.search(r'(?i)(?:password|passwd|token|secret|api[_-]?key)',s):
        raise ValueError('No guardes selectores de contraseñas o secretos en las pruebas creadas')
    return s


def make_custom(*,target: str,kind: str,category: str,name: str,page_path: str,steps: list,allow_interactions=False):
    if kind not in CUSTOM_CATEGORIES or category not in CUSTOM_CATEGORIES[kind]:
        raise ValueError('Tipo o categoría no compatible')
    if not (1<=len(steps)<=24): raise ValueError('Define entre 1 y 24 pasos verificables')
    path=validate_path(page_path)
    title=name.strip()
    if len(title)<3 or len(title)>90 or any(c in title for c in '\r\n\t'):
        raise ValueError('Escribe un nombre de prueba entre 3 y 90 caracteres')
    commands=[_command('open',path)]
    asserted=False
    for index, step in enumerate(steps,1):
        if not isinstance(step,dict): raise ValueError(f'Paso {index}: formato inválido')
        action=str(step.get('command',''))
        selector=str(step.get('target','')).strip()
        value=str(step.get('value','')).strip()
        if action not in SAFE_COMMANDS or action=='open':
            raise ValueError(f'Paso {index}: comando no permitido')
        if len(value)>180 or any(c in value for c in '\r\n\x00'):
            raise ValueError(f'Paso {index}: dato demasiado largo o inválido')
        if action in INTERACTIVE and not allow_interactions:
            raise ValueError('Confirma expresamente que puedes interactuar con esta aplicación de pruebas')
        if action in SELECTOR_ACTIONS:
            selector=_safe_selector(selector)
        elif action=='setWindowSize':
            if not re.fullmatch(r'[3-9]\d{2,3}x[3-9]\d{2,3}',selector):
                raise ValueError('Tamaño de ventana: utiliza, por ejemplo, 375x812')
        elif action=='pause':
            if not selector.isdigit() or int(selector)>2000: raise ValueError('Pausa de 0 a 2000 ms')
        elif action=='assertTitle':
            if not selector or len(selector)>100: raise ValueError('Introduce el título esperado')
        if action in ('assertText','assertValue','type','select') and not value:
            raise ValueError(f'Paso {index}: debes introducir el valor esperado o de prueba')
        if action in ASSERTIONS: asserted=True
        commands.append(_command(action,selector,value))
    if not asserted:
        raise ValueError('Añade al menos una validación real (por ejemplo, assertElementPresent o assertText)')
    case={'id':'tqa_'+_new_id(),'name':title,'commands':commands,
          'tqa':{'target':target,'kind':kind,'category':category,'template':'personalizada',
                 'page_path':path,'checks':False}}
    return _project('TQA | '+title,[case],category)


def _page_checks(page: dict):
    """Selectores id/name observados, verificados después por Selenium real.

    No inventa texto esperado ni envía formularios. Las páginas SPA pueden necesitar
    pruebas particulares; el parser de HTML no ve todas las renderizaciones JS.
    """
    unique=[]
    for element in page.get('locators', []):
        selector=element.get('selector','')
        if selector in unique:continue
        try: _safe_selector(selector)
        except ValueError: continue
        unique.append(selector)
        if len(unique)>=4:break
    return unique


def make_general(*,target: str,scanned: dict):
    pages=scanned.get('pages',[])
    if not pages: raise ValueError('No se encontraron pantallas HTML. Selecciona una ruta de inicio accesible.')
    tests=[]
    for page in pages[:16]:
        path=validate_path(page['path'])
        cmds=[_command('open',path),_command('assertElementPresent','css=body')]
        for selector in _page_checks(page):
            cmds.append(_command('assertElementPresent',selector))
        tests.append({'id':'tqa_'+_new_id(),'name':f'Página accesible · {page["title"][:58]}',
                      'commands':cmds,'tqa':{'target':target,'kind':'Funcionales',
                          'category':'Recorrido general','template':'pagina','page_path':path,
                          'checks':False}})
    return _project('TQA | Recorrido general · '+target,tests,'Recorrido general')


def make_screen(*,target: str,kind: str,category: str,name: str,screen: dict):
    """Crea automáticamente UNA prueba de lectura con los elementos reales hallados.

    'kind' no puede atribuir una medición no funcional que no se está efectuando.
    Las pruebas de accesibilidad, rendimiento, etc. deben utilizar plantillas con
    medición explícita de TQA.
    """
    if kind!='Funcionales' or category not in CUSTOM_CATEGORIES['Funcionales']:
        raise ValueError('Para pruebas no funcionales usa las plantillas con métricas reales')
    path=validate_path(screen['path'])
    title=(name or 'Verificar '+screen.get('title',path)).strip()
    if not 3<=len(title)<=90:raise ValueError('Nombre entre 3 y 90 caracteres')
    cmds=[_command('open',path), _command('assertElementPresent','css=body')]
    for selector in _page_checks({'locators':screen.get('elements',[])}):
        cmds.append(_command('assertElementPresent',selector))
    case={'id':'tqa_'+_new_id(),'name':title,'commands':cmds,
          'tqa':{'target':target,'kind':'Funcionales','category':category,
                 'template':'pagina','page_path':path,'checks':False}}
    return _project('TQA | '+title,[case],category)

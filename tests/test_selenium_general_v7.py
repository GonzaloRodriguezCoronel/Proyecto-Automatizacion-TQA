"""Pruebas de v7: generar, almacenar, proteger y seguir todas las pantallas.

No se declara PASS de Selenium sin que se ejecute un navegador real.
"""
import json
import pytest
from fastapi.testclient import TestClient
from app import main
from app.selenium_discovery import PageParser, _safe_path
from app.selenium_suites import make_custom, make_general, make_screen
from app.selenium_ide import parse_side

client = TestClient(main.app)


def test_general_project_has_several_pages_and_verified_checks():
    scan={'pages':[
        {'path':'/demo/','title':'Inicio','locators':[{'selector':'id=titulo'}]},
        {'path':'/demo/reportes','title':'Reportes','locators':[{'selector':'id=reportes-titulo'}]},
        {'path':'/demo/perfil','title':'Perfil','locators':[]},
    ]}
    project=make_general(target='Demo local',scanned=scan)
    parse_side(json.dumps(project).encode())
    assert len(project['tests'])==3
    assert project['tests'][1]['commands'][-1]['target']=='id=reportes-titulo'
    assert all(t['tqa']['category']=='Recorrido general' for t in project['tests'])
    assert all(t['commands'][0]['target'].startswith('/demo/') for t in project['tests'])


def test_auto_screen_does_not_require_login_or_pretend_business_rules():
    project=make_screen(target='Demo local',kind='Funcionales',category='Regresión',name='Revisar reporte',
        screen={'path':'/demo/reportes','title':'Reporte','elements':[{'selector':'id=reportes-titulo'},
                        {'selector':'id=reportes-titulo'},{'selector':'id=password'}]})
    assert len(project['tests'])==1
    commands=project['tests'][0]['commands']
    assert commands[0]['target']=='/demo/reportes'
    assert [c['target'] for c in commands[1:]]==['css=body','id=reportes-titulo']
    assert all(c['command']!='click' for c in commands)
    assert project['tests'][0]['tqa']['kind']=='Funcionales'
    with pytest.raises(ValueError,match='no funcionales'):
        make_screen(target='Demo local',kind='No funcionales',category='Rendimiento',name='No valido',
                    screen={'path':'/demo/reportes','elements':[]})


def test_custom_builder_requires_assertions_and_authorized_interactions():
    base=dict(target='Demo local',kind='Funcionales',category='E2E',name='Comprobar formulario',page_path='/demo/formulario')
    with pytest.raises(ValueError,match='Confirma'):
        make_custom(**base,steps=[{'command':'click','target':'id=enviar','value':''}])
    with pytest.raises(ValueError,match='validación real'):
        make_custom(**base,steps=[{'command':'click','target':'id=enviar','value':''}],allow_interactions=True)
    project=make_custom(**base,steps=[{'command':'assertElementPresent','target':'id=nombre','value':''},
                                           {'command':'assertElementPresent','target':'id=enviar','value':''}])
    assert project['tests'][0]['commands'][0]['command']=='open'
    assert len(project['tests'][0]['commands'])==3


def test_discovery_only_same_origin_and_safe_paths():
    url='http://127.0.0.1:8022'
    assert _safe_path(url,'/demo/reportes','/demo/')=='/demo/reportes'
    assert _safe_path(url,'../perfil','/demo/reportes')=='/perfil'
    assert _safe_path(url,'http://malicioso.test/','/demo/') is None
    assert _safe_path(url,'/demo/logout','/demo/') is None
    assert _safe_path(url,'/demo/export','/demo/') is None
    assert _safe_path(url,'/demo/reportes?token=secreto','/demo/') is None
    parser=PageParser();parser.feed('<html><title>Panel</title><a href="/demo/perfil">Perfil</a><input id="nombre"><input type="password" id="password"><button id="enviar">Enviar</button></html>')
    assert parser.links==['/demo/perfil']
    assert 'id=password' not in [i['selector'] for i in parser.elements]
    assert 'id=enviar' in [i['selector'] for i in parser.elements]


def test_general_creation_saved_to_sqlite_and_all_cases_visible(monkeypatch):
    pages={'pages':[{'path':'/demo/','title':'Inicio','locators':[]},
                    {'path':'/demo/reportes','title':'Reportes','locators':[{'selector':'id=reportes-titulo'}]}],
           'errors':[], 'visited':2}
    monkeypatch.setattr(main,'crawl_site',lambda *a,**k:pages)
    res=client.post('/api/selenium/general',json={'target':'Demo local','start_path':'/demo/','max_pages':8})
    assert res.status_code==201,res.text
    project=res.json();assert project['count']==2
    detail=client.get('/api/selenium/projects/'+project['id'])
    assert detail.status_code==200
    assert len(detail.json()['tests'])==2
    export=client.get('/api/selenium/projects/'+project['id']+'/export')
    assert export.status_code==200 and export.content.startswith(b'{')
    ids=[t['id'] for t in detail.json()['tests']]
    run_req={'project_id':project['id'],'target':'Demo local','email':'qa@example.org','test_ids':ids,'view_mode':'integrated'}
    response=client.post('/api/selenium/start',json=run_req)
    assert response.status_code==202,response.text
    run_id=response.json()['id']
    run=client.get('/api/runs/'+run_id).json()
    assert run['selected_cases']==['SIDE_'+x for x in ids]
    assert len(run['cases'])==2
    states=client.get('/api/runs/'+run_id+'/live').json()['case_states']
    assert len(states)==2
    assert {s['status'] for s in states}.issubset({'PASS','FAIL','NOT RUN','SKIPPED'})


def test_auto_screen_endpoint_persists_custom_page(monkeypatch):
    monkeypatch.setattr(main,'inspect_page', lambda *a,**k:{'path':'/demo/reportes','title':'Reportes',
        'elements':[{'selector':'id=reportes-titulo','tag':'h1','label':'Título'}], 'links':[], 'forms':0})
    res=client.post('/api/selenium/auto-screen',json={'target':'Demo local','kind':'Funcionales',
                    'category':'Smoke','name':'Chequeo de reportes','page_path':'/demo/reportes'})
    assert res.status_code==201,res.text
    tid=res.json()['tests'][0]['id']
    assert res.json()['tests'][0]['commands'][-1]['target']=='id=reportes-titulo'
    assert client.get('/api/selenium/projects/'+res.json()['id']).json()['tests'][0]['id']==tid
    bad=client.post('/api/selenium/auto-screen',json={'target':'Demo local','kind':'Funcionales',
                    'category':'Smoke','name':'Peligro','page_path':'https://fuera.example'})
    assert bad.status_code==422
    nonfunc=client.post('/api/selenium/auto-screen',json={'target':'Demo local','kind':'No funcionales',
                    'category':'Rendimiento','name':'Carga inicial','page_path':'/demo/reportes'})
    assert nonfunc.status_code==201
    assert nonfunc.json()['tests'][0]['kind']=='No funcionales'


def test_unified_dashboard_contains_v7_controls():
    res=client.get('/avanzado')
    assert res.status_code==200
    html=res.text
    for key in ['selenium-general-panel','general-create','selenium-custom-panel','custom-auto',
                'custom-add','custom-create','live-case-list','side-live-shot']:
        assert f'id="{key}"' in html
    assert 'data-tab="selenium"' not in html
    js=client.get('/static/app.js').text
    for endpoint in ['/api/selenium/general','/api/selenium/auto-screen','/api/selenium/custom']:
        assert endpoint in js

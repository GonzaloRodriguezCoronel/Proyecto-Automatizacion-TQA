"""Verifica la pantalla original, tarjetas y conexión al motor TQA.
Las pruebas unitarias no equivalen a una ejecución Selenium contra CIARÁ.
"""
import json
import pytest
from fastapi.testclient import TestClient
from app import main, simple_mode

client=TestClient(main.app)

@pytest.fixture
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'DB',tmp_path/'historial.sqlite')
    monkeypatch.setattr(main,'REPORTS',tmp_path/'reportes')
    monkeypatch.setattr(main,'EVIDENCE',tmp_path/'evidencias')
    main.REPORTS.mkdir();main.EVIDENCE.mkdir();main.initialize()
    monkeypatch.setattr(main,'execute_run',lambda rid:None)
    monkeypatch.setattr(simple_mode,'inspect_page', lambda base,path:{'path':path,'title':'Prueba','elements':[],'links':[],'forms':0})
    monkeypatch.setattr(simple_mode,'crawl_site',lambda base,path,n:{'pages':[
         {'path':'/','title':'Inicio','locators':[]},
         {'path':'/productos','title':'Productos','locators':[]}]})


def test_main_view_is_single_original_with_advanced_preserved():
    home=client.get('/').text
    advanced=client.get('/avanzado').text
    assert home==advanced
    assert 'data-tab="robot"' in home
    assert 'data-tab="assistant"' in home
    assert 'id="side-live-shot"' in home
    assert 'id="side-live-log"' in home
    assert 'id="ciara-test-cards"' in home
    assert 'id="ciara-easy-email"' in home
    assert '<details id="advanced-config"' in home
    assert 'id="unified-run-form"' in home
    assert 'id="ciara-easy-form"' in home
    js=client.get('/static/ciara_original.js').text
    assert 'originalRender=renderResults' in js
    assert "showTab('robot')" in js


def test_functional_nonfunctional_card_catalog_and_status():
    resp=client.get('/api/simple/setup')
    assert resp.status_code==200
    data=resp.json()
    assert data['version']=='8.5'
    assert isinstance(data['smtp_configured'],bool)
    types={t['id']:t for t in data['types']}
    assert types['rapida']['group']=='Funcionales'
    assert types['carga_api']['group']=='No funcionales'
    assert types['integracion_api']['group']=='Funcionales'
    assert 'retesting' in types


def test_preview_api_and_selected_case(isolated):
    response=client.get('/api/simple/preview',params={'test_type':'integracion_api'})
    assert response.status_code==200,response.text
    selected=response.json()['cases'][0]['name']
    launch=client.post('/api/simple/launch',json={'test_type':'integracion_api','email':'alumno@example.com','selected_names':[selected]})
    assert launch.status_code==202,launch.text
    run=main.get_run(launch.json()['id'])
    assert run['selected_cases']==['TC-CIA-INT']
    assert run['kind']=='Funcionales'


def test_preview_and_select_specific_navigation(isolated):
    response=client.get('/api/simple/preview',params={'test_type':'navegacion'})
    assert response.status_code==200,response.text
    names=[c['name'] for c in response.json()['cases']]
    assert len(names)==2
    launch=client.post('/api/simple/launch',json={'test_type':'navegacion','email':'alumno@example.com','selected_names':[names[0]]})
    assert launch.status_code==202,launch.text
    run=main.get_run(launch.json()['id'])
    assert len(run['selected_cases'])==1


def test_invalid_email_no_execution(isolated):
    response=client.post('/api/simple/launch',json={'test_type':'rapida','email':'not-email'})
    assert response.status_code==422


def test_retesting_only_after_real_failure_in_ciara(isolated):
    missing=client.post('/api/simple/launch',json={'test_type':'retesting','email':'alumno@example.com'})
    assert missing.status_code==422
    with main.connect() as con:
        con.execute('INSERT INTO runs(id,target,kind,suite,email,status,global_status,email_status,created_at,selected_cases) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    ('FAIL2026','CIARÁ','Funcionales','Regression','alumno@example.com','FINALIZADA','FAIL','NO_ENVIADO',main.now(),json.dumps(['TC-CIA-REG'])))
        con.execute('INSERT INTO results(run_id,case_id,data_json) VALUES(?,?,?)',
                    ('FAIL2026','TC-CIA-REG',json.dumps({'id':'TC-CIA-REG','name':'Bloqueo de volumen superior al límite','status':'FAIL'})))
    preview=client.get('/api/simple/preview',params={'test_type':'retesting'})
    assert preview.status_code==200
    launch=client.post('/api/simple/launch',json={'test_type':'retesting','email':'alumno@example.com'})
    assert launch.status_code==202,launch.text
    run=main.get_run(launch.json()['id'])
    assert run['selected_cases']==['TC-CIA-REG']
    assert run['suite'].startswith('Retesting')

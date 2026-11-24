"""Pruebas del nuevo modo sencillo; el navegador se simula solo en la suite técnica.

Los reportes reales solo se muestran como PASS cuando Selenium ejecuta en Chrome.
"""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from app import main, simple_mode

client = TestClient(main.app)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'DB', tmp_path / 'historial.sqlite')
    monkeypatch.setattr(main, 'REPORTS', tmp_path / 'reportes')
    monkeypatch.setattr(main, 'EVIDENCE', tmp_path / 'evidencias')
    main.REPORTS.mkdir()
    main.EVIDENCE.mkdir()
    main.initialize()
    monkeypatch.setattr(simple_mode, 'inspect_page', lambda base,path:{
        'path':path, 'title':'CIARA', 'elements':[{'selector':'id=logo','tag':'h1','label':'Logo'}], 'links':[], 'forms':0})
    monkeypatch.setattr(simple_mode, 'crawl_site', lambda base,path,n:{'pages':[
        {'path':path,'title':'Inicio','locators':[{'selector':'id=logo'}]},
        {'path':'/reportes','title':'Reportes','locators':[{'selector':'id=tabla'}]}]})
    return tmp_path


def test_startpage_is_simple_but_advanced_ui_is_preserved():
    page=client.get('/')
    assert page.status_code==200
    assert 'Prueba tu sistema' in page.text
    assert 'test-types' in page.text
    assert client.get('/avanzado').status_code==200
    assert 'selenium-generator' in client.get('/avanzado').text
    assert client.get('/static/simple.js').status_code==200


def test_setup_has_simple_types_and_ciara_default():
    data=client.get('/api/simple/setup').json()
    assert any('CIAR' in t for t in data['targets'])
    assert len(data['types'])==8
    assert data['default_target'].upper().startswith('CIAR')


def test_security_reject_unknown_target_and_invalid_type(isolated):
    base={'target':'Demo local','test_type':'rapida','path':'/demo/'}
    assert client.post('/api/simple/start',json={**base,'target':'https://bad.test'}).status_code==422
    assert client.post('/api/simple/start',json={**base,'test_type':'delete'}).status_code==422
    assert client.post('/api/simple/start',json={**base,'path':'https://outside.test'}).status_code==422


@pytest.mark.parametrize('test_type', ['rapida','login','rendimiento','accesibilidad','responsive','estabilidad'])
def test_oneclick_generates_real_selenium_project_without_credentials(isolated,monkeypatch,test_type):
    monkeypatch.setattr(main,'execute_run',lambda rid:None)
    response=client.post('/api/simple/start',json={
        'target':'Demo local','test_type':test_type,'path':'/demo/login','visible':False})
    assert response.status_code==202,response.text
    result=response.json()
    run=client.get('/api/runs/'+result['id']).json()
    assert run['status']=='PENDIENTE'
    assert run['email']==''
    assert run['view_mode']=='integrated'
    assert len(run['selected_cases'])==1
    project=main.load_side_project(run['side_project_id'])
    assert project['tests'][0]['commands'][0]['command'] in ('open','setWindowSize')
    assert all(cmd['command'] not in ('click','type') for cmd in project['tests'][0]['commands'])


@pytest.mark.parametrize('test_type',['navegacion','regresion'])
def test_automatic_discovery_creates_multiple_browser_cases(isolated,monkeypatch,test_type):
    monkeypatch.setattr(main,'execute_run',lambda rid:None)
    res=client.post('/api/simple/start',json={'target':'Demo local','test_type':test_type,
                                                'path':'/demo/','visible':True})
    assert res.status_code==202,res.text
    run=main.get_run(res.json()['id'])
    assert len(run['selected_cases'])==2
    assert run['view_mode']=='visible'


def test_prevents_duplicate_runs(isolated,monkeypatch):
    monkeypatch.setattr(main,'execute_run',lambda rid:None)
    body={'target':'Demo local','test_type':'rapida','path':'/demo/'}
    assert client.post('/api/simple/start',json=body).status_code==202
    assert client.post('/api/simple/start',json=body).status_code==409


def test_export_real_archives_after_mocked_case_execution(isolated,monkeypatch):
    # El doble verifica el flujo de reportes, no constituye una ejecución Selenium real.
    def fake_case(project, case_id, target, base_url, evidence_dir, progress=None, view_mode=None):
        case=next(t for t in project['tests'] if t['id']==case_id)
        result={'id':'SIDE_'+case_id,'name':case['name'],'kind':'Funcionales','suite':'Smoke',
                'objective':'Comprobar página','preconditions':'Servidor disponible',
                'expected':'HTML correcto','status':'PASS','duration_s':0.1,
                'observation':'Doble de prueba, no ejecución de Chrome','evidence':[],
                'artifacts':[],'planned_steps':['Abrir la página'], 'steps':[{'action':'open','expected':'Se abre','observed':'Mocked','status':'PASS'}]}
        if progress:
            progress({'type':'case_start','case':'SIDE_'+case_id,'name':case['name'],'total':2})
            progress({'type':'case_done','case':'SIDE_'+case_id,'status':'PASS'})
        return result
    monkeypatch.setattr(main,'run_side_test',fake_case)
    res=client.post('/api/simple/start',json={'target':'Demo local','test_type':'rapida','path':'/demo/'})
    assert res.status_code==202,res.text
    run_id=res.json()['id']
    info=main.get_run(run_id)
    assert info['status']=='FINALIZADA' and info['global_status']=='PASS', info['error']
    assert info['email_status']=='NO_SOLICITADO'
    assert client.get(f'/api/runs/{run_id}/live').status_code==200
    for fmt in ('csv','json','zip'):
        report=client.get(f'/api/simple/runs/{run_id}/{fmt}')
        assert report.status_code==200,report.text[:100] if fmt!='zip' else ''
    assert client.get(f'/api/runs/{run_id}/download/pdf').status_code==200
    assert client.get(f'/api/runs/{run_id}/download/html').status_code==200
    zip_bytes=client.get(f'/api/simple/runs/{run_id}/zip').content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names=archive.namelist()
        assert 'resultados.csv' in names and 'resultados.json' in names
        assert any(name.endswith('.pdf') for name in names)
    assert client.get('/api/simple/history').json()[0]['id']==run_id


def test_check_only_defined_target(monkeypatch):
    assert client.get('/api/simple/check?target=https://example.com&path=/').status_code==422
    class Response:
        status_code=200
        headers={'content-type':'application/json'}
    class Client:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):return Response()
    monkeypatch.setattr(simple_mode.httpx,'Client',Client)
    data=client.get('/api/simple/check?target=Demo%20local&path=/').json()
    assert data['connected'] and not data['selenium_ready']
    assert 'API' in data['message']

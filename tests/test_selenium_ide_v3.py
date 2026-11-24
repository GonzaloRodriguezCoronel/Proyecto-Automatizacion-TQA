"""Pruebas reproducibles de la actualización v3 (no requieren Chrome)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.selenium_ide import parse_side, preview_project, resolve_url, SideValidationError, _make_video, gherkin_from_commands, robot_from_commands

ROOT=Path(__file__).resolve().parents[1]
client=TestClient(app)


def demo():
    return (ROOT/'ejemplos'/'Demo_TQA_Selenium_IDE.side').read_bytes()


def test_demo_side_parses_and_has_pass_fail():
    data=parse_side(demo())
    meta=preview_project(data)
    assert meta['count']==2
    assert {'demo_login_pass','demo_login_fail'}=={t['id'] for t in meta['tests']}
    assert all(not t['unsupported'] for t in meta['tests'])
    password=next(c for c in meta['tests'][0]['commands'] if c['target']=='id=password')
    assert password['value']=='••••••••'


def test_side_rejects_external_navigation_and_bad_files():
    assert resolve_url('http://127.0.0.1:8022','/demo/login')=='http://127.0.0.1:8022/demo/login'
    with pytest.raises(SideValidationError):
        resolve_url('http://127.0.0.1:8022','https://example.org/secret')
    with pytest.raises(SideValidationError):
        parse_side(b'{ mal }')
    with pytest.raises(SideValidationError):
        parse_side(b'A'*512_001)


def test_demo_registered_and_stats_available():
    r=client.get('/api/selenium/projects')
    assert r.status_code==200
    assert any(p['id']=='DEMO' for p in r.json())
    detail=client.get('/api/selenium/projects/DEMO')
    assert detail.status_code==200 and detail.json()['count']==2
    result=client.get('/api/estadisticas')
    assert result.status_code==200
    assert {'runs','cases','counts','success_rate','daily','suites'}<=set(result.json())


def test_import_side_and_request_validation():
    response=client.post('/api/selenium/import',files={'file':('mi_proyecto.side',demo(),'application/json')})
    assert response.status_code==201 and response.json()['count']==2
    pid=response.json()['id']
    request={'project_id':pid,'target':'Demo local','email':'tester@example.com','test_ids':['no_existe']}
    response=client.post('/api/selenium/start',json=request)
    assert response.status_code==422
    request['test_ids']=['demo_login_pass']
    request['target']='Sitio externo no autorizado'
    response=client.post('/api/selenium/start',json=request)
    assert response.status_code==422
    bad=client.post('/api/selenium/import',files={'file':('incorrecto.side',b'not json','application/json')})
    assert bad.status_code==422


def test_video_encoder_creates_valid_mp4(tmp_path):
    from PIL import Image
    imgs=[]
    for index in range(3):
        img=tmp_path/f'paso_{index}.png'
        Image.new('RGB',(300,200),(index*70,60,120)).save(img)
        imgs.append(img)
    clip=tmp_path/'evidencia.mp4'
    assert _make_video(imgs,clip)
    assert clip.read_bytes()[4:8]==b'ftyp'
    assert clip.stat().st_size>1000


def test_natural_gherkin_and_robot_export_do_not_expose_password():
    case=parse_side(demo())['tests'][0]
    feature=gherkin_from_commands(case)
    assert 'Given que' in feature
    assert 'When abro la página' in feature
    assert '\n    And ingreso' in feature
    assert '\n    Then el elemento' in feature
    assert 'Demo123!' not in feature
    robot=robot_from_commands(case,'http://127.0.0.1:8022',[])
    assert 'Open Browser' in robot
    assert 'Input Password' in robot
    assert 'TQA_TEST_PASSWORD' in robot
    assert 'Demo123!' not in robot


def test_full_platform_report_even_when_selenium_missing():
    response=client.post('/api/selenium/start',json={
        'project_id':'DEMO','target':'Demo local','email':'test@example.com',
        'test_ids':['demo_login_pass']})
    assert response.status_code==202
    run_id=response.json()['id']
    finished=client.get('/api/runs/'+run_id).json()
    assert finished['status'] in ('FINALIZADA','FALLIDA')
    assert len(finished['cases'])==1
    assert finished['cases'][0]['status'] in ('PASS','FAIL','NOT RUN')
    for kind in ('pdf','html'):
        assert client.get(f'/api/runs/{run_id}/download/{kind}').status_code==200

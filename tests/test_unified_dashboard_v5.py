"""Regresión de v5: un solo ejecutor con Selenium integrado y pruebas reales."""
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import selenium_ide
from app.main import app

client = TestClient(app)


def test_unified_dark_dashboard_and_no_separate_selenium_page():
    res = client.get('/avanzado')
    assert res.status_code == 200
    html = res.text
    assert 'Ejecución inteligente de pruebas' in html
    assert 'unified-run-form' in html
    assert 'data-engine="selenium"' in html
    assert 'data-engine="standard"' in html
    assert 'data-engine="robot"' in html
    assert 'side-live-shot' in html
    assert 'side-live-log' in html
    assert 'side-live-bar-fill' in html
    assert 'data-tab="selenium"' not in html
    assert '<details class="advanced"><summary>＋ Importar un proyecto .side propio' in html
    css = client.get('/static/style.css')
    assert css.status_code == 200
    assert 'background:radial-gradient' in css.text


def test_live_endpoint_for_non_selenium_cases():
    result = client.post('/api/runs', json={
        'target':'Demo local','kind':'Funcionales','suite':'Smoke',
        'email':'alumno@example.com','case_ids':['TC-SMK-001']
    })
    assert result.status_code == 202
    run_id = result.json()['id']
    progress = client.get(f'/api/runs/{run_id}/live')
    assert progress.status_code == 200
    data = progress.json()
    types_seen = [e['type'] for e in data['events']]
    assert 'case_start' in types_seen
    assert 'case_done' in types_seen
    assert data['total_cases'] == 1
    assert data['completed_cases'] == 1
    assert data['id'] == run_id


def test_selenium_integrated_mode_default_and_invalid_mode():
    request = {'project_id':'DEMO','target':'Demo local',
               'email':'alumno@example.com','test_ids':['demo_login_pass']}
    ok = client.post('/api/selenium/start', json=request)
    assert ok.status_code == 202
    run = client.get('/api/runs/'+ok.json()['id']).json()
    assert run['view_mode'] == 'integrated'
    assert run['suite'] == 'Selenium IDE'
    progress = client.get('/api/runs/'+run['id']+'/live').json()
    assert progress['completed_cases'] == 1
    assert progress['total_cases'] == 1
    bad = client.post('/api/selenium/start',json={**request,'view_mode':'iframe-inseguro'})
    assert bad.status_code == 422


def test_selenium_headless_is_per_run_not_global(monkeypatch, tmp_path):
    choices=[]
    class Options:
        def __init__(self): self.args=[];choices.append(self.args)
        def add_argument(self, arg): self.args.append(arg)
    class Browser:
        def set_page_load_timeout(self, seconds): pass
        def save_screenshot(self, path): Image.new('RGB',(80,50),'#103040').save(path)
        def quit(self): pass
    fake_selenium=types.ModuleType('selenium')
    fake_webdriver=types.ModuleType('selenium.webdriver')
    fake_webdriver.Chrome=lambda options:Browser()
    fake_selenium.webdriver=fake_webdriver
    for name,module in [
        ('selenium',fake_selenium),('selenium.webdriver',fake_webdriver),
        ('selenium.webdriver.chrome',types.ModuleType('selenium.webdriver.chrome')),
        ('selenium.webdriver.chrome.options',types.ModuleType('selenium.webdriver.chrome.options')),
    ]:monkeypatch.setitem(sys.modules,name,module)
    sys.modules['selenium.webdriver.chrome.options'].Options=Options
    monkeypatch.setattr(selenium_ide,'_execute_command',lambda *a:('OK','',''))
    monkeypatch.setattr(selenium_ide,'_make_video',lambda *a:False)
    monkeypatch.setenv('SELENIUM_HEADLESS','true')
    monkeypatch.setenv('SELENIUM_STEP_DELAY_MS','0')
    project={'tests':[{'id':'flow','name':'Demo','commands':[{'command':'open','target':'/demo/login','value':''}]}]}
    integrated=selenium_ide.run_side_test(project,'flow','Demo local','http://127.0.0.1:8022',tmp_path,view_mode='integrated')
    assert integrated['status']=='PASS'
    assert '--headless=new' in choices[-1]
    visible=selenium_ide.run_side_test(project,'flow','Demo local','http://127.0.0.1:8022',tmp_path,view_mode='visible')
    assert visible['status']=='PASS'
    assert '--headless=new' not in choices[-1]

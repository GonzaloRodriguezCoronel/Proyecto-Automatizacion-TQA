"""Pruebas del generador v6; sin inventar resultados ni necesitar Chrome en CI."""
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.selenium_generator import TEMPLATES, make_test, measure_check
from app.selenium_ide import parse_side

client=TestClient(app)

@pytest.mark.parametrize('kind,category,template', [
 ('Funcionales','Smoke','pagina'),
 ('Funcionales','Regresión','elemento'),
 ('Funcionales','E2E','login_ok'),
 ('No funcionales','Rendimiento','tiempo'),
 ('No funcionales','Accesibilidad','accesibilidad'),
 ('No funcionales','Responsividad','responsive'),
 ('No funcionales','Estabilidad','repetir'),
])
def test_templates_create_valid_side(kind,category,template):
    project=make_test(target='Demo local',kind=kind,category=category,template=template)
    assert parse_side(json.dumps(project).encode('utf8'))==project
    assert project['tests'][0]['tqa']['kind']==kind
    assert project['tests'][0]['commands'][0]['command'] in ('open','setWindowSize')


def test_reject_remote_paths_wrong_templates_and_unknown_login_target():
    with pytest.raises(ValueError):make_test(target='Demo local',kind='Funcionales',category='Smoke',template='pagina',page_path='https://evil.example')
    with pytest.raises(ValueError):make_test(target='Demo local',kind='No funcionales',category='Smoke',template='pagina')
    with pytest.raises(ValueError):make_test(target='CIARÁ',kind='Funcionales',category='E2E',template='login_ok')


def test_real_measurement_thresholds_with_driver_stub():
    class Browser:
        def __init__(self,value):self.value=value
        def execute_script(self,js):return self.value
    assert measure_check(Browser(125),{'template':'tiempo','max_ms':300})['status']=='PASS'
    assert measure_check(Browser(390),{'template':'tiempo','max_ms':300})['status']=='FAIL'
    assert measure_check(Browser(None),{'template':'tiempo','max_ms':300})['status']=='NOT RUN'
    assert measure_check(Browser({'missingAlt':0,'unlabeledInputs':0,'unnamedButtons':0}),{'template':'accesibilidad'})['status']=='PASS'
    assert measure_check(Browser({'missingAlt':1,'unlabeledInputs':0,'unnamedButtons':0}),{'template':'accesibilidad'})['status']=='FAIL'
    assert measure_check(Browser({'viewport':375,'content':385}),{'template':'responsive'})['status']=='FAIL'


def test_api_create_auto_select_export_and_nonfunctional_result():
    categories=client.get('/api/selenium/templates')
    assert categories.status_code==200
    assert 'Funcionales' in categories.json()['kinds']
    res=client.post('/api/selenium/generate',json={'target':'Demo local','kind':'No funcionales',
        'category':'Rendimiento','template':'tiempo','name':'Tiempo de carga QA','page_path':'/demo/login','max_ms':4000})
    assert res.status_code==201, res.text
    project_id=res.json()['id']
    detail=client.get('/api/selenium/projects/'+project_id)
    assert detail.status_code==200
    assert detail.json()['tests'][0]['kind']=='No funcionales'
    script=client.get('/api/selenium/projects/'+project_id+'/export')
    assert script.status_code==200
    assert script.headers['content-disposition'].endswith('.side"')
    test_id=detail.json()['tests'][0]['id']
    response=client.post('/api/selenium/start',json={'project_id':project_id,'target':'Demo local',
        'email':'qa@example.org','test_ids':[test_id],'view_mode':'integrated'})
    assert response.status_code==202, response.text
    run=client.get('/api/runs/'+response.json()['id']).json()
    assert run['kind']=='No funcionales'
    assert run['suite']=='Selenium · Rendimiento'
    assert run['cases'][0]['kind']=='No funcionales'
    assert run['cases'][0]['status'] in ('NOT RUN', 'PASS', 'FAIL')  # Depende del navegador disponible


def test_generated_target_pinned_and_no_untrusted_urls():
    res=client.post('/api/selenium/generate',json={'target':'CIARÁ','kind':'Funcionales','category':'Smoke','template':'pagina','page_path':'/'})
    assert res.status_code==201, res.text
    project_id=res.json()['id'];tid=res.json()['tests'][0]['id']
    other=client.post('/api/selenium/start',json={'project_id':project_id,'target':'Demo local','email':'qa@example.org','test_ids':[tid]})
    assert other.status_code==422


def test_dashboard_contains_creator_and_single_execution_screen():
    html=client.get('/avanzado').text
    assert 'selenium-generator' in html and 'selenium-kind' in html and 'selenium-category' in html
    assert 'selenium-create' in html and 'selenium-template' in html
    assert 'data-tab="selenium"' not in html
    js=client.get('/static/app.js').text
    assert '/api/selenium/generate' in js


def test_nonfunctional_browser_metric_is_always_evaluated(monkeypatch, tmp_path):
    import types,sys
    from PIL import Image
    from app import selenium_ide
    class Options:
        def add_argument(self,value):pass
    class Browser:
        def set_page_load_timeout(self,value):pass
        def execute_script(self,code):return 210
        def save_screenshot(self,path):Image.new('RGB',(70,40),'#113344').save(path)
        def quit(self):pass
    fake_selenium=types.ModuleType('selenium')
    webdriver=types.ModuleType('selenium.webdriver')
    webdriver.Chrome=lambda options:Browser()
    fake_selenium.webdriver=webdriver
    for name, module in [('selenium',fake_selenium),('selenium.webdriver',webdriver),
                        ('selenium.webdriver.chrome',types.ModuleType('selenium.webdriver.chrome')),
                        ('selenium.webdriver.chrome.options',types.ModuleType('selenium.webdriver.chrome.options'))]:
        monkeypatch.setitem(sys.modules,name,module)
    sys.modules['selenium.webdriver.chrome.options'].Options=Options
    monkeypatch.setattr(selenium_ide,'_execute_command',lambda *args:('Elemento encontrado','',''))
    monkeypatch.setattr(selenium_ide,'_make_video',lambda *args:False)
    monkeypatch.setenv('SELENIUM_STEP_DELAY_MS','0')
    project=make_test(target='Demo local',kind='No funcionales',category='Rendimiento',template='tiempo',max_ms=250)
    test_id=project['tests'][0]['id']
    events=[]
    report=selenium_ide.run_side_test(project,test_id,'Demo local','http://127.0.0.1:8022',tmp_path,progress=events.append,view_mode='integrated')
    assert report['status']=='PASS'
    assert len(report['steps'])==3
    assert report['steps'][-1]['status']=='PASS'
    assert '210 ms' in report['steps'][-1]['observed']
    assert any(e['type']=='step_done' and e['step']==3 for e in events)
    project['tests'][0]['tqa']['max_ms']=100
    report_fail=selenium_ide.run_side_test(project,test_id,'Demo local','http://127.0.0.1:8022',tmp_path,view_mode='integrated')
    assert report_fail['status']=='FAIL'
    assert '210 ms' in report_fail['observation']

"""Comprobaciones de la actualización v8.5 (sin tocar el CIARÁ real)."""
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app import main, simple_mode, selenium_ide

client = TestClient(main.app)


@pytest.fixture
def auth(monkeypatch, tmp_path):
    monkeypatch.setenv('CIARA_TEST_USERNAME', 'demo_ciara')
    monkeypatch.setenv('CIARA_TEST_PASSWORD', 'solo_dato_de_prueba_123')
    monkeypatch.setattr(main, 'DB', tmp_path / 'historial.sqlite')
    monkeypatch.setattr(main, 'REPORTS', tmp_path / 'reportes')
    monkeypatch.setattr(main, 'EVIDENCE', tmp_path / 'evidencias')
    main.REPORTS.mkdir()
    main.EVIDENCE.mkdir()
    main.initialize()
    monkeypatch.setattr(main, 'execute_run', lambda _id: None)
    monkeypatch.setattr(simple_mode, '_resolve_ciara_path', lambda *args: ('/login', {'path':'/login', 'title':'CIARÁ', 'forms':1}))
    return tmp_path


def test_suite_generates_real_sign_in_without_storing_credentials(auth):
    for typ in ('rapida','login','navegacion','regresion','rendimiento','accesibilidad','responsive','estabilidad'):
        spec = simple_mode.SimpleRunInput(target=simple_mode.ciara_target(), test_type=typ, path='/login')
        project = simple_mode._build_project(spec, main)
        stored = json.dumps(project, ensure_ascii=False)
        assert 'solo_dato_de_prueba_123' not in stored
        assert 'demo_ciara' not in stored
        case = project['tests'][0]
        assert case['tqa']['ciara_login'] is True
        actions = [c['command'] for c in case['commands']]
        assert actions[:2] == ['open', 'ciaraSignIn']
        assert actions[2] == 'assertElementPresent'
        if typ in ('navegacion', 'regresion'):
            assert 'ciaraBrowse' in actions
        if typ == 'estabilidad':
            assert 'ciaraRepeat' in actions


def test_simple_launch_saves_only_secretless_actions(auth):
    response = client.post('/api/simple/launch',json={
        'test_type':'login','email':'estudiante@example.com'})
    assert response.status_code == 202, response.text
    run = main.get_run(response.json()['id'])
    with main.connect() as connection:
        row = connection.execute('SELECT content_json FROM side_projects WHERE id=?',
                                 (run['side_project_id'],)).fetchone()
    assert row and 'ciaraSignIn' in row['content_json']
    assert 'solo_dato_de_prueba_123' not in row['content_json']
    assert 'demo_ciara' not in row['content_json']


def test_setup_reports_login_ready_without_revealing_credentials(auth):
    r = client.get('/api/simple/setup')
    assert r.status_code == 200
    assert r.json()['ciara_login_configured'] is True
    assert r.json()['version']=='8.5'
    assert 'demo_ciara' not in r.text
    assert 'solo_dato_de_prueba_123' not in r.text


def test_ui_still_uses_same_three_panels_with_better_cards():
    document = client.get('/').text
    assert 'id="ciara-test-cards"' in document
    assert 'id="side-live-shot"' in document
    assert 'id="live-case-list"' in document
    assert 'id="advanced-config"' in document
    assert 'id="ciara-login-status"' in document
    js=client.get('/static/ciara_original.js').text
    assert 'aria-pressed' in js
    css=client.get('/static/style.css').text
    assert '.qa-suite-card:focus-visible' in css


def test_simulated_browser_authentication_keeps_secret_out_of_events(monkeypatch, auth):
    # Sustituto pequeño de las interfaces que Selenium necesita; no finge una
    # ejecución real de Chrome en CIARÁ.
    selenium = types.ModuleType('selenium')
    webdriver = types.ModuleType('selenium.webdriver')
    common = types.ModuleType('selenium.webdriver.common')
    by = types.ModuleType('selenium.webdriver.common.by')
    support = types.ModuleType('selenium.webdriver.support')
    ui = types.ModuleType('selenium.webdriver.support.ui')
    exceptions = types.ModuleType('selenium.common.exceptions')
    by.By = types.SimpleNamespace(CSS_SELECTOR='css', XPATH='xpath', TAG_NAME='tag')
    class TimeoutException(Exception):
        pass
    exceptions.TimeoutException = TimeoutException
    class WebDriverWait:
        def __init__(self, _driver, _seconds): self.driver = _driver
        def until(self, fn):
            for _ in range(6):
                result = fn(self.driver)
                if result: return result
            raise TimeoutException()
    ui.WebDriverWait = WebDriverWait
    for key, value in {
        'selenium':selenium, 'selenium.webdriver':webdriver,
        'selenium.webdriver.common':common, 'selenium.webdriver.common.by':by,
        'selenium.webdriver.support':support, 'selenium.webdriver.support.ui':ui,
        'selenium.common.exceptions':exceptions}.items():
        monkeypatch.setitem(sys.modules,key,value)

    class FakeInput:
        def __init__(self, driver, name): self.driver=driver;self.name=name;self.written=[]
        def is_displayed(self): return not self.driver.logged_in
        def is_enabled(self): return True
        def clear(self): pass
        def send_keys(self, value): self.written.append(value)
        def find_element(self, by, value): return self.driver.form
    class FakeSubmit:
        def __init__(self, driver): self.driver=driver
        def is_displayed(self): return True
        def is_enabled(self): return True
        def click(self): self.driver.logged_in=True;self.driver.current_url='http://127.0.0.1:8000/panel'
    class FakeBody:
        text = 'Panel de inventarios y control de operaciones mineras'
        def is_displayed(self): return True
    class FakeForm:
        def __init__(self, driver): self.driver=driver
        def find_elements(self, by, selector):
            if 'button' in selector:return [self.driver.submit]
            if selector.startswith('input[name='):return [self.driver.username]
            return []
    class Driver:
        def __init__(self):
            self.logged_in=False;self.current_url='http://127.0.0.1:8000/login'
            self.username=FakeInput(self,'username')
            self.password=FakeInput(self,'password')
            self.form=FakeForm(self)
            self.submit=FakeSubmit(self)
        def find_elements(self, by, selector):
            if selector=='input[type="password"]':return [] if self.logged_in else [self.password]
            return []
        def find_element(self, by, selector): return FakeBody()
    driver=Driver()
    result=selenium_ide._ciara_sign_in(driver, 'http://127.0.0.1:8000')
    assert driver.logged_in is True
    assert driver.username.written==['demo_ciara']
    assert driver.password.written==['solo_dato_de_prueba_123']
    assert 'solo_dato_de_prueba_123' not in result
    assert 'demo_ciara' not in result
    assert '/panel' in result


def test_safe_setup_file_only_updates_ciara_env(tmp_path):
    from configurar_acceso_ciara import set_secret
    before='SMTP_PASSWORD="keep_private"\nCIARA_TEST_USERNAME=old\n'
    after=set_secret(set_secret(before,'CIARA_TEST_USERNAME','user123'),
                     'CIARA_TEST_PASSWORD','different_private_value')
    assert 'SMTP_PASSWORD="keep_private"' in after
    assert 'CIARA_TEST_USERNAME="user123"' in after
    assert 'CIARA_TEST_PASSWORD="different_private_value"' in after

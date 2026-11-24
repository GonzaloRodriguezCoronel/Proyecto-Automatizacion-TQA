"""Pruebas del seguimiento en vivo, aisladas de Chrome real."""
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app import selenium_ide


def test_live_endpoint_returns_events_for_demo():
    client = TestClient(app)
    response = client.post('/api/selenium/start', json={
        'project_id': 'DEMO', 'target': 'Demo local',
        'email': 'control@example.com', 'test_ids': ['demo_login_pass']})
    assert response.status_code == 202
    run_id = response.json()['id']
    result = client.get(f'/api/runs/{run_id}/live')
    assert result.status_code == 200
    data = result.json()
    assert data['id'] == run_id
    assert data['events'][0]['type'] == 'case_start'
    assert data['events'][-1]['type'] == 'case_done'
    assert 'password' not in str(data['events']).lower()
    assert client.get('/api/runs/not-real/live').status_code == 404


def test_live_events_are_emitted_after_each_browser_action(monkeypatch, tmp_path):
    class FakeOptions:
        def add_argument(self, arg):
            pass

    class FakeBrowser:
        def set_page_load_timeout(self, timeout):
            pass
        def save_screenshot(self, path):
            Image.new('RGB', (100, 70), (30, 60, 90)).save(path)
        def quit(self):
            self.closed = True

    fake_selenium = types.ModuleType('selenium')
    fake_selenium.webdriver = types.ModuleType('selenium.webdriver')
    fake_selenium.webdriver.Chrome = lambda options: FakeBrowser()
    for name, mod in [('selenium', fake_selenium),
                      ('selenium.webdriver', fake_selenium.webdriver),
                      ('selenium.webdriver.chrome', types.ModuleType('selenium.webdriver.chrome')),
                      ('selenium.webdriver.chrome.options', types.ModuleType('selenium.webdriver.chrome.options'))]:
        monkeypatch.setitem(sys.modules, name, mod)
    sys.modules['selenium.webdriver.chrome.options'].Options = FakeOptions
    monkeypatch.setattr(selenium_ide, '_execute_command', lambda *a: ('Ejecutado', 'id=btn', '//*[@id="btn"]'))
    monkeypatch.setattr(selenium_ide, '_make_video', lambda *a: False)
    monkeypatch.setenv('SELENIUM_STEP_DELAY_MS', '0')
    events = []
    project = {'tests': [{'id':'demo1','name':'Un botón', 'commands': [
        {'command':'open', 'target':'/demo/login', 'value':''},
        {'command':'click', 'target':'id=btn', 'value':''}]}]}
    report = selenium_ide.run_side_test(project,'demo1','Demo local','http://127.0.0.1:8022', tmp_path, progress=events.append)
    assert report['status'] == 'PASS'
    assert [evt['type'] for evt in events] == [
        'case_start', 'browser_open', 'step_start', 'step_done',
        'step_start', 'step_done', 'case_done']
    assert events[3]['screenshot'] and (tmp_path / events[3]['screenshot']).is_file()
    assert events[5]['xpath'] == '//*[@id="btn"]'
    assert not any('value' in evt for evt in events)


def test_ui_contains_live_preview():
    response = TestClient(app).get('/avanzado')
    assert response.status_code == 200
    assert 'side-live-shot' in response.text
    assert 'side-live-log' in response.text
    assert 'side-live-bar-fill' in response.text

"""Pruebas de las nuevas funciones sin afirmar haber ejecutado Selenium externo."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.catalog import CASES
from app.gherkin import gherkin_for
from app.main import app
from app.robot_engine import execute_auto, generate_suite, safe_cell, validate_path

client = TestClient(app)


def example_scan():
    return {
        'url':'http://127.0.0.1:8022/demo/login','path':'/demo/login',
        'title':'Demo acceso','http_status':200,'inspection_mode':'Prueba',
        'elements':[
            {'id':value, 'label':value, 'tag':'input' if value in ('usuario','password') else 'button',
             'xpath':f"//*[@id='{value}']", 'verified':True}
            for value in ('usuario','password','entrar','resultado')
        ]
    }


def test_gherkin_natural_con_and_en_todos_los_casos():
    for case in CASES:
        scenario = gherkin_for(case.id)
        assert '\n    Given ' in scenario
        assert '\n    When ' in scenario
        assert '\n    And ' in scenario
        assert '\n    Then ' in scenario
        assert scenario.index('    When ') < scenario.index('    And ') < scenario.index('    Then ')
        assert 'se ejecuta el caso' not in scenario.lower()


def test_example_correos_usa_acciones_concretas():
    x = gherkin_for('TC-SAN-001')
    assert 'prueba@example.com' in x
    assert '/demo/validate-email' in x
    assert 'HTTP 200' in x


def test_rutas_no_permiten_urls_externas():
    for bad in ['https://google.com','//external.com','/../../etc/passwd','/demo?token=ABC', '/demo\\login', '/api#hash']:
        with pytest.raises(ValueError):
            validate_path(bad)
    assert validate_path('/demo/login') == '/demo/login'


def test_robot_script_contiene_xpath_y_asercion_real():
    code = generate_suite(example_scan(), demo_login=True)
    assert 'Library    SeleniumLibrary' in code
    assert 'xpath=//*[@id=' in code
    assert 'Input Text    ${USUARIO}    demo' in code
    assert 'Click Element    ${ENTRAR}' in code
    assert 'Wait Until Element Contains    ${RESULTADO}    Acceso correcto' in code
    assert 'Capture Page Screenshot' in code


def test_codigo_no_admite_variables_robot_inyectadas_en_xpath():
    with pytest.raises(ValueError):
        safe_cell("//input[@id='${PASSWORD}']")


def test_robot_endpoint_rechaza_ruta_arbitraria():
    response = client.post('/api/robot/start', json={
        'target':'Demo local','page_path':'https://untrusted.example','email':'qa@example.com'
    })
    assert response.status_code == 422


def test_robot_resultado_pass_se_deriva_de_xml(monkeypatch, tmp_path):
    from app import robot_engine
    monkeypatch.setattr(robot_engine, 'discover', lambda *_:example_scan())
    original_find = robot_engine.importlib.util.find_spec
    monkeypatch.setattr(robot_engine.importlib.util, 'find_spec', lambda name: object() if name in ('robot','SeleniumLibrary') else original_find(name))

    def fake_run(cmd, **kwargs):
        Path(tmp_path / 'robot_output.xml').write_text(
            '<robot><suite><test name="Demo"><status status="PASS"/></test></suite></robot>', encoding='utf-8'
        )
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(robot_engine.subprocess,'run',fake_run)
    result = execute_auto(target='Demo local',base_url='http://127.0.0.1:8022',page_path='/demo/login',evidence_dir=tmp_path)
    assert result['status']=='PASS'
    assert 'prueba_automatizada.robot' in result['artifacts']
    assert 'locators_validados.json' in result['artifacts']
    assert json.loads((tmp_path/'locators_validados.json').read_text(encoding='utf-8'))['elements']


def test_robot_resultado_fail_se_deriva_de_xml(monkeypatch,tmp_path):
    from app import robot_engine
    monkeypatch.setattr(robot_engine, 'discover', lambda *_:example_scan())
    monkeypatch.setattr(robot_engine.importlib.util,'find_spec',lambda *_:object())

    def fake_run(cmd, **kwargs):
        (tmp_path/'robot_output.xml').write_text(
            '<robot><suite><test name="Demo"><status status="FAIL">Acceso incorrecto</status></test></suite></robot>', encoding='utf-8'
        )
        return SimpleNamespace(returncode=1, stdout='', stderr='')

    monkeypatch.setattr(robot_engine.subprocess,'run',fake_run)
    result=execute_auto(target='Demo local',base_url='http://127.0.0.1:8022',page_path='/demo/login',evidence_dir=tmp_path)
    assert result['status']=='FAIL'
    assert 'Acceso incorrecto' in result['observation']

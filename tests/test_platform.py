"""Pruebas automáticas del propio orquestador (independientes del dashboard)."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['ok'] is True


def test_catalog():
    response = client.get('/api/catalog')
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['cases']}
    assert {'TC-SMK-001', 'TC-REG-FAIL', 'TC-CIA-INT', 'TC-PERF-001'}.issubset(ids)


def test_demo_email():
    assert client.post('/demo/validate-email', json={'email': 'a@example.com'}).status_code == 200
    assert client.post('/demo/validate-email', json={'email': 'invalido'}).status_code == 422


def test_demo_login():
    page = client.get('/demo/login')
    assert page.status_code == 200
    assert 'id="usuario"' in page.text


def test_reject_invalid_run():
    response = client.post('/api/runs', json={'target':'Demo local','kind':'Funcionales','suite':'NoExiste','email':'qa@example.com'})
    assert response.status_code == 422


def test_reject_invalid_email():
    response = client.post('/api/runs', json={'target':'Demo local','kind':'Funcionales','suite':'Smoke','email':'sin-arroba'})
    assert response.status_code == 422

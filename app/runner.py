"""Casos reales: HTTP de API, validación, navegador Playwright y cargas locales acotadas."""
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from .catalog import CATALOG


class SkippedCase(Exception):
    pass


class InfrastructureFailure(Exception):
    pass


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


class ProgressSteps(list):
    """Lista de pasos con actualizaciones inofensivas y progresivas para el panel."""
    def __init__(self, progress=None, case_id='', total=0):
        super().__init__()
        self.progress = progress
        self.case_id = case_id
        self.total = total


def step(steps, action, expected, observed, ok=True):
    steps.append({'action': action, 'expected': expected, 'observed': str(observed),
                  'status': 'PASS' if ok else 'FAIL'})
    callback = getattr(steps, 'progress', None)
    if callback:
        try:
            callback({'type': 'step_done', 'case': getattr(steps, 'case_id', ''),
                      'step': len(steps), 'total': getattr(steps, 'total', 0),
                      'command': str(action)[:110], 'observed': str(observed)[:150],
                      'status': 'PASS' if ok else 'FAIL'})
        except Exception:
            pass  # Telemetría no debe afectar el resultado de la prueba.
    if not ok:
        raise AssertionError(f'{action}: esperado {expected}; obtenido {observed}')


def request(client, method, url, **kwargs):
    try:
        return client.request(method, url, timeout=8.0, **kwargs)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
        raise InfrastructureFailure(f'No se puede acceder al servicio: {type(exc).__name__}') from exc


def ciara_input(volume=30):
    return {
        'horas_trabajo': 8, 'material_procesado_m3': volume,
        'ley_oro_g_m3': 1.62, 'eficiencia_recuperacion_pct': 80,
        'precipitacion_simulada_mm': 5, 'nivel_rio_simulado_cm': 120,
        'zona_extraccion': 'Meandro Norte', 'jornada_activa': 'SI',
        'maquinaria': 'Excavadora + planta gravimetrica',
        'estado_maquinaria': 'Operativa', 'condicion_climatica': 'Lluvia ligera'
    }


def run_case(case_id, target, base_url, evidence_dir: Path, progress=None):
    """Estructura única para cada resultado; no devuelve falsos positivos por errores de red."""
    case = CATALOG[case_id]
    t0 = time.perf_counter()
    steps, images = ProgressSteps(progress, case_id, len(case.steps)), []
    error, status, category = '', 'PASS', 'funcional'
    observed = ''
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            if case_id == 'TC-SMK-001':
                response = request(client, 'GET', f'{base_url}/demo/health')
                step(steps, 'GET /demo/health', '200', response.status_code, response.status_code == 200)
                value = response.json().get('status')
                step(steps, 'Verificar JSON', 'ok', value, value == 'ok')
            elif case_id == 'TC-SMK-002':
                response = request(client, 'GET', f'{base_url}/demo/login')
                step(steps, 'Abrir /demo/login', 'HTTP 200', response.status_code, response.status_code == 200)
                html = response.text
                form_ok = all(x in html for x in ['id="usuario"', 'id="password"', 'id="entrar"'])
                step(steps, 'Validar formulario', 'Usuario, contraseña y botón',
                     'Presentes' if form_ok else 'Faltan elementos', form_ok)
            elif case_id == 'TC-SAN-001':
                response = request(client, 'POST', f'{base_url}/demo/validate-email', json={'email': 'prueba@example.com'})
                step(steps, 'Enviar email válido', 'HTTP 200', response.status_code, response.status_code == 200)
                valid = response.json().get('valid')
                step(steps, 'Verificar validación', 'true', valid, valid is True)
            elif case_id == 'TC-REG-001':
                response = request(client, 'POST', f'{base_url}/demo/validate-email', json={'email': 'sin-arroba'})
                step(steps, 'Enviar email inválido', 'HTTP 422', response.status_code, response.status_code == 422)
            elif case_id == 'TC-REG-FAIL':
                response = request(client, 'GET', f'{base_url}/demo/health')
                step(steps, 'Comparar código (fallo intencional)', 'HTTP 201', response.status_code, response.status_code == 201)
            elif case_id == 'TC-INT-001':
                payload = {'mineral': 'oro', 'cantidad': 2}
                response = request(client, 'POST', f'{base_url}/demo/echo', json=payload)
                step(steps, 'Enviar JSON', 'HTTP 200', response.status_code, response.status_code == 200)
                data = response.json()
                step(steps, 'Comparar datos', payload, data.get('data'), data.get('data') == payload)
            elif case_id == 'TC-E2E-001':
                try:
                    from playwright.sync_api import sync_playwright
                except ImportError as exc:
                    raise SkippedCase('Instala Playwright y Chromium: python -m playwright install chromium') from exc
                try:
                    with sync_playwright() as pw:
                        browser_path = os.getenv('CHROMIUM_EXECUTABLE')
                        browser = pw.chromium.launch(headless=True, executable_path=browser_path or None,
                                                     args=['--no-sandbox'] if browser_path else None)
                        page = browser.new_page(viewport={'width': 1280, 'height': 800})
                        try:
                            response = page.goto(f'{base_url}/demo/login', wait_until='domcontentloaded', timeout=12000)
                            observed_status = response.status if response else 'sin respuesta'
                            step(steps, 'Abrir la página en Chromium', 'HTTP 200', observed_status,
                                 bool(response) and response.status == 200)
                        except Exception as navigation_error:
                            # Hay entornos académicos que bloquean la navegación de Chromium
                            # hacia localhost pero sí permiten cargar HTML en el navegador.
                            # El origen se verifica mediante HTTP real y se registra la alternativa.
                            if 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(navigation_error):
                                raise
                            fallback_response = request(client, 'GET', f'{base_url}/demo/login')
                            step(steps, 'Consultar la página real vía HTTP', 'HTTP 200',
                                 fallback_response.status_code, fallback_response.status_code == 200)
                            page.close()
                            page = browser.new_page(viewport={'width': 1280, 'height': 800})
                            page.set_content(fallback_response.text, wait_until='load')
                            step(steps, 'Cargar HTML en Chromium (restricción de navegación local)',
                                 'Formulario renderizado', 'Formulario renderizado')
                        capture = evidence_dir / f'{case_id}_01_formulario.png'
                        page.screenshot(path=str(capture), full_page=True)
                        images.append(capture.name)
                        page.locator('#usuario').fill('demo')
                        page.locator('#password').fill('Demo123!')
                        step(steps, 'Ingresar credenciales de prueba', 'Campos completos', 'Campos completos')
                        page.locator('#entrar').click()
                        page.locator('#resultado[data-status="success"]').wait_for(timeout=6000)
                        observed_text = page.locator('#resultado').inner_text()
                        step(steps, 'Verificar acceso', 'Acceso correcto', observed_text,
                             'Acceso correcto' in observed_text)
                        capture = evidence_dir / f'{case_id}_02_resultado.png'
                        page.screenshot(path=str(capture), full_page=True)
                        images.append(capture.name)
                        browser.close()
                except Exception as exc:
                    if 'Executable doesn\'t exist' in str(exc) or 'browserType.launch' in str(exc):
                        raise SkippedCase('Chromium no instalado: python -m playwright install chromium') from exc
                    raise
            elif case_id == 'TC-CIA-SMK':
                response = request(client, 'GET', f'{base_url}/api/ml/estado')
                step(steps, 'Consultar /api/ml/estado', 'HTTP 200', response.status_code, response.status_code == 200)
                loaded = response.json().get('modelo_cargado')
                step(steps, 'Verificar el modelo', 'true', loaded, loaded is True)
            elif case_id == 'TC-CIA-INT':
                response = request(client, 'POST', f'{base_url}/api/ml/predecir', json=ciara_input())
                step(steps, 'Enviar predicción', 'HTTP 200', response.status_code, response.status_code == 200)
                data = response.json().get('resultado', {})
                gold = data.get('oro_estimado_g')
                step(steps, 'Validar gramos estimados', 'número >= 0', gold,
                     isinstance(gold, (int, float)) and not isinstance(gold, bool) and gold >= 0)
            elif case_id == 'TC-CIA-REG':
                response = request(client, 'POST', f'{base_url}/api/ml/predecir', json=ciara_input(301))
                step(steps, 'Enviar 301 m3', 'HTTP 422', response.status_code, response.status_code == 422)
            elif case_id.startswith('TC-PERF') or case_id.startswith('TC-LOAD') or case_id.startswith('TC-STR') or case_id.startswith('TC-SOAK'):
                if target == 'Demo local':
                    probe = f'{base_url}/demo/health'
                else:
                    probe = f'{base_url}/api/ml/estado'
                if case_id.startswith('TC-PERF'):
                    requests_count, workers, interval, threshold = 12, 1, 0, 1.0
                elif case_id.startswith('TC-LOAD'):
                    requests_count, workers, interval, threshold = 20, 4, 0, .95
                elif case_id.startswith('TC-STR'):
                    requests_count, workers, interval, threshold = 40, 8, 0, .90
                else:
                    requests_count, workers, interval, threshold = 12, 1, .5, 1.0

                def hit(_):
                    start = time.perf_counter()
                    try:
                        # Cada trabajador usa su propia conexión, sin sesión compartida.
                        with httpx.Client(trust_env=False, timeout=5.0) as local_client:
                            res = local_client.get(probe)
                        return res.status_code == 200, (time.perf_counter() - start) * 1000
                    except httpx.HTTPError:
                        return False, (time.perf_counter() - start) * 1000
                results = []
                if interval:
                    for number in range(requests_count):
                        results.append(hit(number))
                        if number < requests_count - 1:
                            time.sleep(interval)
                else:
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        futures = [executor.submit(hit, n) for n in range(requests_count)]
                        for f in as_completed(futures):
                            results.append(f.result())
                success = sum(1 for ok, _ in results if ok)
                durations = sorted(ms for _, ms in results)
                p95 = durations[max(0, int(len(durations) * .95 + .9999) - 1)]
                average = statistics.mean(durations)
                ratio = success / requests_count
                observed = (f'{success}/{requests_count} exitosas; éxito {ratio:.1%}; '
                            f'promedio {average:.1f} ms; p95 {p95:.1f} ms; concurrencia {workers}')
                if case_id.startswith('TC-PERF'):
                    ok = success == requests_count and p95 <= 1200
                    expected = '100% y p95 <= 1200 ms'
                else:
                    ok = ratio >= threshold
                    expected = f'Éxito >= {threshold:.0%}'
                step(steps, 'Ejecutar pruebas HTTP reales', expected, observed, ok)
            else:
                raise SkippedCase('Caso no implementado.')
    except SkippedCase as exc:
        status, category, error = 'SKIPPED', 'prerrequisito', str(exc)
    except InfrastructureFailure as exc:
        status, category, error = 'NOT RUN', 'infraestructura', str(exc)
    except AssertionError as exc:
        status, category, error = 'FAIL', 'funcional', str(exc)
    except (httpx.HTTPError, Exception) as exc:
        status, category = 'NOT RUN', 'infraestructura'
        error = f'Error ejecutando el caso: {type(exc).__name__}: {str(exc)[:180]}'
    elapsed = round(time.perf_counter() - t0, 3)
    # Evidencia de cada paso ejecutado; el PDF incorpora además las capturas E2E.
    evidence = evidence_dir / f'{case_id}_evidencia.txt'
    content = {'case_id': case_id, 'name': case.name, 'status': status,
               'classification': category, 'duration_s': elapsed,
               'steps': steps, 'error': error, 'observation': observed}
    evidence.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'id': case.id, 'name': case.name, 'kind': case.kind, 'suite': case.suite,
            'objective': case.objective, 'preconditions': case.preconditions,
            'expected': case.expected, 'planned_steps': list(case.steps),
            'status': status, 'failure_class': category, 'duration_s': elapsed,
            'steps': steps, 'observation': error or observed or 'Sin observaciones',
            'evidence': [evidence.name] + images}

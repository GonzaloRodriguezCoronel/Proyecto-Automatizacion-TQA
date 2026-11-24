"""Escenarios legibles en español: formato Given / When / And / Then."""
from .catalog import CATALOG

# Cada paso se basa en el catálogo REAL; son propuestas para revisar, no ejecución.
SCENARIOS = {
    'TC-SMK-001': ('Disponibilidad del servicio de pruebas',
        'el servidor de demostración está encendido',
        'consulto la dirección /demo/health mediante GET',
        'compruebo que la respuesta contiene información del estado del servicio',
        'recibo HTTP 200 y el estado del servicio es "ok"'),
    'TC-SMK-002': ('Acceso al formulario de inicio de sesión',
        'el servidor de demostración está disponible',
        'abro la pantalla /demo/login desde el navegador',
        'busco los campos de usuario y contraseña y el botón Entrar',
        'los tres elementos aparecen en la página'),
    'TC-SAN-001': ('Validar que un correo correcto sea aceptado',
        'el servicio de validación de correo está funcionando',
        'envío "prueba@example.com" mediante POST a /demo/validate-email',
        'verifico que el correo contiene un nombre, una arroba y un dominio',
        'la API responde HTTP 200 e indica que el correo es válido'),
    'TC-REG-001': ('Rechazar correos con un formato inválido',
        'el servicio de validación de correo está funcionando',
        'envío "sin-arroba" mediante POST a /demo/validate-email',
        'compruebo que el dato no tiene la estructura de un correo electrónico',
        'la API rechaza el dato con HTTP 422'),
    'TC-REG-FAIL': ('Demostrar un resultado fallido controlado',
        'el recurso de demostración responde HTTP 200',
        'solicito /demo/health mediante GET',
        'comparo deliberadamente la respuesta con la expectativa de HTTP 201',
        'la verificación falla y queda registrada con su resultado real'),
    'TC-INT-001': ('Verificar que la API conserva los datos enviados',
        'el servicio de demostración está disponible',
        'envío un objeto JSON con mineral y cantidad a /demo/echo',
        'consulto los valores devueltos por el servicio',
        'recibo HTTP 200 y los campos devueltos coinciden con los enviados'),
    'TC-E2E-001': ('Ingresar correctamente al formulario de demostración',
        'la página /demo/login está abierta y existe un usuario de prueba',
        'escribo el usuario "demo" y su contraseña de demostración',
        'presiono el botón Entrar para iniciar la sesión',
        'aparece el mensaje "Acceso correcto" y se registran evidencias'),
    'TC-CIA-SMK': ('Comprobar disponibilidad del modelo de predicción',
        'la API de CIARÁ está ejecutándose en el entorno de pruebas',
        'consulto /api/ml/estado',
        'reviso el campo "modelo_cargado" de la respuesta JSON',
        'la respuesta es HTTP 200 y el modelo indica true'),
    'TC-CIA-INT': ('Obtener una predicción válida mediante CIARÁ',
        'Laravel y el servicio de predicción están en funcionamiento',
        'envío un volumen válido y los demás datos de prueba a /api/ml/predecir',
        'verifico el resultado recibido desde el modelo de Machine Learning',
        'la respuesta es HTTP 200 y los gramos estimados son un número no negativo'),
    'TC-CIA-REG': ('Rechazar un volumen superior al límite permitido',
        'la API de CIARÁ está disponible para realizar pruebas',
        'envío una solicitud de predicción con 301 m³',
        'comparo el volumen enviado con el límite de 300 m³',
        'el sistema rechaza la solicitud con HTTP 422'),
    'TC-PERF-001': ('Medir la latencia de respuesta de la API',
        'el servicio bajo prueba está disponible',
        'realizo 12 solicitudes de consulta',
        'calculo las duraciones y el percentil 95 de las respuestas',
        'todas las solicitudes responden correctamente y el p95 no supera 1200 ms'),
    'TC-LOAD-001': ('Comprobar estabilidad con carga controlada',
        'el entorno de pruebas está autorizado para recibir carga',
        'envío 20 solicitudes con un máximo de cuatro trabajadores concurrentes',
        'registro cuántas solicitudes se completan correctamente',
        'al menos el 95 % de las solicitudes resulta exitoso'),
    'TC-STR-001': ('Evaluar una carga de estrés limitada',
        'el entorno de pruebas está disponible y autorizado',
        'envío 40 solicitudes con hasta ocho trabajadores concurrentes',
        'registro los errores y las respuestas exitosas',
        'al menos el 90 % de las solicitudes es exitoso'),
    'TC-SOAK-001': ('Comprobar la continuidad del servicio',
        'el sistema bajo prueba se encuentra disponible',
        'envío 12 solicitudes espaciadas durante aproximadamente seis segundos',
        'verifico la respuesta de cada solicitud a lo largo del período',
        'no se detectan errores durante la observación'),
}


def gherkin_for(case_id: str) -> str:
    case = CATALOG[case_id]
    if case_id in SCENARIOS:
        scenario, given, when, and_step, then = SCENARIOS[case_id]
    else:
        scenario = case.name
        given = case.preconditions.rstrip('.')
        when = case.steps[0].rstrip('.') if case.steps else f'preparo el caso {case.id}'
        and_step = case.steps[1].rstrip('.') if len(case.steps) > 1 else 'reviso la respuesta del sistema'
        then = case.expected.rstrip('.')
    return (f'Feature: {case.name}\n'
            f'  Scenario: {scenario}\n'
            f'    Given que {given.removeprefix("que ")}\n'
            f'    When {when}\n'
            f'    And {and_step}\n'
            f'    Then {then}')


def gherkin_for_page(title: str, page_path: str, login: bool, count: int) -> str:
    if login:
        return ('Feature: Acceso a la aplicación de demostración\n'
                '  Scenario: Un usuario de prueba inicia sesión correctamente\n'
                '    Given que tengo abierto el formulario de inicio de sesión\n'
                '    When escribo las credenciales del usuario de demostración\n'
                '    And presiono el botón Entrar\n'
                '    Then el sistema muestra el mensaje "Acceso correcto"')
    label = (title or page_path).replace('\n', ' ').strip()[:70]
    return (f'Feature: Accesibilidad básica de la página {label}\n'
            '  Scenario: Los elementos de la página se pueden localizar\n'
            '    Given que la aplicación autorizada está disponible\n'
            f'    When abro la página {page_path}\n'
            f'    And verifico los {count} elementos interactivos detectados\n'
            '    Then cada elemento analizado debe existir en el DOM de la página')

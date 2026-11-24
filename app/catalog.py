from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    kind: str
    suite: str
    targets: tuple[str, ...]
    objective: str
    preconditions: str
    expected: str
    steps: tuple[str, ...]

    def public(self):
        data = asdict(self)
        data['targets'] = list(self.targets)
        data['steps'] = list(self.steps)
        return data


CASES = [
    Case('TC-SMK-001', 'API disponible', 'Funcionales', 'Smoke', ('Demo local',),
         'Confirmar disponibilidad de la aplicación de demostración.', 'Servidor TQA funcionando.',
         'GET /demo/health devuelve HTTP 200 y estado ok.',
         ('Enviar GET /demo/health', 'Validar código HTTP y respuesta JSON')),
    Case('TC-SMK-002', 'Página de acceso visible', 'Funcionales', 'Smoke', ('Demo local',),
         'Verificar que el formulario web de demostración carga.', 'Servidor TQA funcionando.',
         'Página con campos usuario, contraseña y botón Entrar.',
         ('Abrir /demo/login', 'Validar presencia del formulario')),
    Case('TC-SAN-001', 'Correo válido aceptado', 'Funcionales', 'Sanity', ('Demo local',),
         'Verificar validación de datos de entrada.', 'Servidor TQA funcionando.',
         'Correo válido produce HTTP 200.',
         ('Enviar un correo de prueba', 'Verificar resultado positivo')),
    Case('TC-REG-001', 'Correo inválido rechazado', 'Funcionales', 'Regression', ('Demo local',),
         'Comprobar rechazo de datos inválidos.', 'Servidor TQA funcionando.',
         'Correo incorrecto produce HTTP 422.',
         ('Enviar un correo sin @', 'Verificar HTTP 422')),
    Case('TC-REG-FAIL', 'Fallo controlado de demostración', 'Funcionales', 'Regression', ('Demo local',),
         'Demostrar una falla real registrada y documentada.', 'Servidor TQA funcionando.',
         'Se espera HTTP 201 a propósito para que falle contra HTTP 200.',
         ('Solicitar recurso que devuelve HTTP 200', 'Comparar con expectativa HTTP 201')),
    Case('TC-INT-001', 'Eco de API conserva datos', 'Funcionales', 'Integration', ('Demo local',),
         'Validar envío y recepción de datos JSON.', 'Servidor TQA funcionando.',
         'POST /demo/echo devuelve los mismos valores.',
         ('Enviar JSON de prueba', 'Verificar campos devueltos')),
    Case('TC-E2E-001', 'Inicio de sesión por navegador', 'Funcionales', 'E2E', ('Demo local',),
         'Automatizar un flujo completo de inicio de sesión de prueba.',
         'Playwright y Chromium instalados; usuario demo / Demo123!.',
         'La página muestra Acceso correcto y se guardan capturas.',
         ('Abrir pantalla en Chromium', 'Ingresar credenciales de prueba',
          'Pulsar Entrar', 'Verificar éxito y capturar evidencia')),
    Case('TC-CIA-SMK', 'Estado del modelo CIARÁ', 'Funcionales', 'Smoke', ('CIARÁ',),
         'Verificar que el servicio Random Forest está cargado.', 'CIARÁ y FastAPI levantados.',
         'GET /api/ml/estado devuelve modelo_cargado=true.',
         ('Consultar Laravel GET /api/ml/estado', 'Verificar estado cargado')),
    Case('TC-CIA-INT', 'Predicción de oro por Laravel', 'Funcionales', 'Integration', ('CIARÁ',),
         'Verificar flujo Laravel a servicio de Machine Learning.', 'CIARÁ en ejecución.',
         'POST /api/ml/predecir devuelve valor numérico no negativo.',
         ('Enviar entrada válida al endpoint de CIARÁ', 'Validar estructura de respuesta y gramos')),
    Case('TC-CIA-REG', 'Bloqueo de volumen superior al límite', 'Funcionales', 'Regression', ('CIARÁ',),
         'Verificar validación de límites de entrada.', 'CIARÁ en ejecución.',
         'POST con material_procesado_m3=301 devuelve HTTP 422.',
         ('Enviar volumen 301 m3', 'Comprobar respuesta de validación')),
    Case('TC-PERF-001', 'Latencia de API', 'No funcionales', 'Performance', ('Demo local', 'CIARÁ'),
         'Medir tiempo de respuesta HTTP.', 'Servicio destino iniciado.',
         'p95 de 12 solicitudes menor o igual a 1200 ms y ninguna falla.',
         ('Ejecutar 12 solicitudes GET', 'Calcular promedio y percentil 95')),
    Case('TC-LOAD-001', 'Carga concurrente controlada', 'No funcionales', 'Carga', ('Demo local', 'CIARÁ'),
         'Probar varias peticiones simultáneas.', 'Ejecutar solo en entorno de pruebas local.',
         '20 peticiones con máximo 4 trabajadores, éxito al menos 95%.',
         ('Enviar peticiones concurrentes', 'Contar éxitos y medir tiempos')),
    Case('TC-STR-001', 'Estrés limitado de demostración', 'No funcionales', 'Estres', ('Demo local', 'CIARÁ'),
         'Observar estabilidad con carga acotada.', 'Entorno local de pruebas autorizado.',
         '40 peticiones, máximo 8 trabajadores, éxito al menos 90%.',
         ('Enviar 40 solicitudes con concurrencia 8', 'Comprobar errores y disponibilidad')),
    Case('TC-SOAK-001', 'Resistencia corta', 'No funcionales', 'Resistencia', ('Demo local', 'CIARÁ'),
         'Comprobar respuestas sostenidas en una ventana corta.', 'Entorno de pruebas local.',
         '12 solicitudes espaciadas durante aproximadamente 6 segundos, sin errores.',
         ('Ejecutar solicitudes periódicas', 'Verificar continuidad de respuestas')),
]

CATALOG = {c.id: c for c in CASES}
SUITES = ['Smoke', 'Sanity', 'Regression', 'Integration', 'E2E', 'Performance', 'Carga', 'Estres', 'Resistencia']

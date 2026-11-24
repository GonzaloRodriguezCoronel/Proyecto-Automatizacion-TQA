Feature: Acceso a la aplicación de demostración
  Scenario: Un usuario de prueba inicia sesión correctamente
    Given que tengo abierto el formulario de inicio de sesión
    When escribo las credenciales del usuario de demostración
    And presiono el botón Entrar
    Then el sistema muestra el mensaje "Acceso correcto"

  # XPath localizados y verificados en el DOM de esta página:
  # input (usuario): //*[@id='usuario']
  # input (password): //*[@id='password']
  # button (Entrar): //*[@id='entrar']
  # p (resultado): //*[@id='resultado']

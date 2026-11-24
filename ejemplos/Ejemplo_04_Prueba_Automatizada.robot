*** Settings ***
Library    SeleniumLibrary    run_on_failure=NONE
Suite Teardown    Close All Browsers

*** Variables ***
${URL}    http://127.0.0.1:8022/demo/login
${USUARIO}    xpath=//*[@id='usuario']
${PASSWORD}    xpath=//*[@id='password']
${ENTRAR}    xpath=//*[@id='entrar']
${RESULTADO}    xpath=//*[@id='resultado']

*** Test Cases ***
Inicio de sesion correcto - Demo TQA
    [Documentation]    Flujo real con cuenta de demostracion. La asercion valida el mensaje visible.
    Open Browser    ${URL}    chrome    options=add_argument("--headless=new")
    Wait Until Element Is Visible    ${USUARIO}    10s
    Input Text    ${USUARIO}    demo
    Input Password    ${PASSWORD}    Demo123!
    Click Element    ${ENTRAR}
    Wait Until Element Contains    ${RESULTADO}    Acceso correcto    timeout=10s
    Capture Page Screenshot    evidencia_robot_login.png


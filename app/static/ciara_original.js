/* TQA Center 8.3: conserva el DOM, Selenium IDE, Robot+XPath y monitor v6/v7.
   Solamente mejora la selección del panel izquierdo sobre la MISMA ruta y plantilla. */
'use strict';
(()=>{
  const el=id=>document.getElementById(id);
  let running=false,types={},current='rapida',selectedGroup='Funcionales',webReady=false;
  let previewLoadedFor='',previewCases=[],previewVersion=0;
  const icons={rapida:'⚡',login:'🔐',regresion:'↻',navegacion:'🧭',api_estado:'⛓',integracion_api:'🔗',retesting:'🔁',
               rendimiento:'◷',accesibilidad:'◎',responsive:'▣',estabilidad:'◇',carga_api:'▥',estres_api:'↗',resistencia_api:'⏱'};
  const descriptions={
    rapida:'Smoke inicia sesión en CIARÁ y verifica que se muestra una pantalla interna en Chrome.',
    login:'Sanity inicia sesión con la cuenta de prueba guardada localmente y comprueba el acceso al panel interno.',
    navegacion:'Navegación accede con la cuenta de prueba y revisa hasta cuatro enlaces internos.',
    regresion:'Regresión accede con la cuenta de prueba y visita hasta ocho enlaces internos accesibles.',
    api_estado:'Smoke de API verifica el estado del servicio de CIARÁ. No usa navegador.',
    integracion_api:'Integración comprueba la respuesta del servicio de predicción de CIARÁ con datos de prueba.',
    retesting:'Retesting repite un caso anterior que haya fallado, con su mismo motor y datos de prueba.',
    rendimiento:'Rendimiento mide la navegación de una página con Chrome. No equivale a carga concurrente.',
    accesibilidad:'Accesibilidad básica revisa controles, etiquetas e imágenes. No es una auditoría completa WCAG.',
    responsive:'Diseño móvil verifica desbordamiento horizontal a 375 px mediante Chrome.',
    estabilidad:'Estabilidad repite la navegación tres veces para comprobar disponibilidad básica.',
    carga_api:'Carga envía 20 peticiones HTTP, máximo 4 simultáneas, solo al CIARÁ local autorizado.',
    estres_api:'Estrés envía 40 peticiones HTTP, máximo 8 simultáneas, solo al CIARÁ local autorizado.',
    resistencia_api:'Resistencia realiza 12 peticiones espaciadas durante unos segundos. No es un soak prolongado.'
  };
  const typeOrder=['rapida','login','regresion','navegacion','api_estado','integracion_api','retesting',
                   'rendimiento','accesibilidad','responsive','estabilidad','carga_api','estres_api','resistencia_api'];
  function apiLabel(type){return ['api_estado','integracion_api','carga_api','estres_api','resistencia_api'].includes(type)?'HTTP / API':'Selenium';}
  function renderCards(){
    const holder=el('ciara-test-cards');holder.replaceChildren();
    for(const id of typeOrder){
      const item=types[id];if(!item||item.group!==selectedGroup)continue;
      const card=document.createElement('button');card.type='button';card.dataset.type=id;
      card.className='qa-suite-card'+(id===current?' selected':'');
      card.setAttribute('aria-pressed',String(id===current));
      card.setAttribute('aria-label',item.name+' · '+apiLabel(id));
      const icon=document.createElement('span');icon.className='qa-suite-icon';icon.textContent=icons[id]||'◈';
      const title=document.createElement('strong');title.textContent=item.name;
      const motor=document.createElement('small');motor.textContent=apiLabel(id);
      card.append(icon,title,motor);
      card.addEventListener('click',()=>selectType(id));
      holder.append(card);
    }
  }
  function selectType(id){
    if(!types[id])return;
    current=id;selectedGroup=types[id].group;el('ciara-easy-type').value=id;
    document.querySelectorAll('.test-group-btn').forEach(button=>button.classList.toggle('active',button.dataset.group===selectedGroup));
    renderCards();el('ciara-easy-explanation').textContent=descriptions[id]||types[id].detail;updateReady();
    previewLoadedFor='';previewCases=[];el('ciara-case-checks').replaceChildren();
    el('ciara-preview-status').textContent='Por defecto se ejecuta toda la suite.';
    if(el('ciara-select-cases').open)void loadPreview();
  }
  async function loadPreview(){
    if(!types[current]||previewLoadedFor===current)return;
    const version=++previewVersion,forType=current;
    el('ciara-preview-status').textContent='Buscando casos reales de '+types[forType].name+'…';
    el('ciara-case-checks').replaceChildren();
    try{
      const response=await api('/api/simple/preview?'+new URLSearchParams({test_type:forType}));
      if(version!==previewVersion||current!==forType)return;
      previewCases=response.cases||[];previewLoadedFor=forType;
      const container=el('ciara-case-checks');container.replaceChildren();
      for(const item of previewCases){
        const label=document.createElement('label');label.className='ciara-case-option';
        const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.className='ciara-case-box';checkbox.value=item.name;checkbox.checked=true;
        const text=document.createElement('span');text.textContent=item.name;
        label.append(checkbox,text);container.append(label);
      }
      el('ciara-preview-status').textContent=previewCases.length+' caso(s) encontrados. Desmarca los que no quieras ejecutar.';
    }catch(error){
      if(version!==previewVersion)return;
      el('ciara-preview-status').textContent='No se pueden listar los casos: '+error.message;
    }
  }
  const usesBrowser=id=>!['api_estado','integracion_api','carga_api','estres_api','resistencia_api','retesting'].includes(id);
  function updateReady(){
    const button=el('ciara-easy-run');
    if(!button||running)return;
    button.disabled=usesBrowser(current)&&!webReady;
    button.textContent=button.disabled?'Configura CIARÁ para ejecutar':'▶ Ejecutar prueba';
  }
  function connectionMessage(ready,message,url){
    webReady=!!ready;
    el('ciara-easy-connection').textContent=(ready?'● CIARÁ listo · ':'● Revisar conexión · ')+message;
    el('ciara-easy-connection').className='ciara-link-state '+(ready?'ok':'failed');
    if(!ready) el('ciara-connection-editor').classList.remove('hidden');
    if(url&&el('ciara-web-url'))el('ciara-web-url').value=url;
    updateReady();
  }
  async function setup(){
    try{
      const config=await api('/api/simple/setup');types=Object.fromEntries(config.types.map(t=>[t.id,t]));
      const loginStatus=el('ciara-login-status');
      if(loginStatus){
        loginStatus.textContent=config.ciara_login_configured
          ? '✓ Acceso de prueba configurado · Selenium entrará a CIARÁ antes de comprobar sus pantallas.'
          : '◷ Acceso interno pendiente · Ejecuta CONFIGURAR_ACCESO_CIARA.bat una vez para activar el login automático.';
        loginStatus.classList.toggle('enabled',!!config.ciara_login_configured);
      }
      if(config.smtp_configured===false)el('ciara-mail-status').textContent='SMTP no configurado: podrás descargar PDF y HTML, pero el correo necesita configuración.';
      selectType(current in types?current:'rapida');
      const checked=await api('/api/simple/check?'+new URLSearchParams({target:config.default_target}));
      connectionMessage(checked.selenium_ready,checked.message,checked.url||config.ciara_url);
    }catch(error){
      connectionMessage(false,'CIARÁ no responde: '+error.message,'');
      el('ciara-easy-error').textContent='Comprueba la dirección real de la interfaz de CIARÁ.';
    }
  }
  async function configureUrl(){
    const button=el('ciara-save-url');button.disabled=true;
    el('ciara-url-feedback').textContent='Comprobando dirección…';
    try{
      const response=await api('/api/simple/configure-web',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url:el('ciara-web-url').value.trim()})});
      el('ciara-url-feedback').textContent=response.message;
      connectionMessage(response.selenium_ready,response.message,response.url);
      if(response.selenium_ready){el('ciara-connection-editor').classList.add('hidden');el('ciara-easy-error').textContent='';}
    }catch(error){el('ciara-url-feedback').textContent=error.message;connectionMessage(false,error.message,'');}
    finally{button.disabled=false;}
  }
  async function launch(event){
    event.preventDefault();if(running)return;
    if(usesBrowser(current)&&!webReady){el('ciara-connection-editor').classList.remove('hidden');el('ciara-easy-error').textContent='Primero conecta una pantalla real de CIARÁ. La portada Laravel no cuenta como prueba.';return;}
    const btn=el('ciara-easy-run');el('ciara-easy-error').textContent='';
    const filter=el('ciara-select-cases').open&&previewLoadedFor===current;
    const selectedNames=filter?[...el('ciara-case-checks').querySelectorAll('input:checked')].map(x=>x.value):null;
    if(filter&&!selectedNames.length){el('ciara-easy-error').textContent='Selecciona al menos un caso o cierra «Elegir casos específicos».';return;}
    running=true;btn.disabled=true;btn.textContent='Preparando la prueba…';
    try{
      const res=await api('/api/simple/launch',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({test_type:current,email:el('ciara-easy-email').value.trim(),selected_names:selectedNames})});
      activeId=res.id;resetMonitor();showTab('runner');
      el('ciara-zip').classList.add('disabled');el('ciara-zip').removeAttribute('href');
      el('monitor-title').textContent='Iniciando '+(types[current]?.name||'prueba');
      el('monitor-description').textContent='CIARÁ · '+apiLabel(current)+' · Esperando pasos verificables';
      el('monitor-status').textContent='EN CURSO';el('monitor-status').className='status-chip running';
      btn.textContent='Ejecución en curso…';startPolling(activeId);
    }catch(err){
      el('ciara-easy-error').textContent=err.message;running=false;updateReady();
    }
  }
  // Conserva la función renderResults de la versión 6/7: monitor, capturas, tiempos y reportes.
  const originalRender=renderResults;
  renderResults=function(run){
    originalRender(run);
    const done=['FINALIZADA','FALLIDA'].includes(run.status)&&run.email_status!=='PENDIENTE';
    if(done){
      el('ciara-zip').href='/api/simple/runs/'+encodeURIComponent(run.id)+'/zip';
      el('ciara-zip').classList.remove('disabled');
      if(running){running=false;el('ciara-easy-run').disabled=false;el('ciara-easy-run').textContent='▶ Ejecutar otra prueba';updateReady();}
    }
  };
  document.querySelectorAll('.test-group-btn').forEach(b=>b.addEventListener('click',()=>{
    selectedGroup=b.dataset.group;const first=typeOrder.find(id=>types[id]?.group===selectedGroup);
    if(first)selectType(first);
  }));
  el('ciara-toggle-url').addEventListener('click',()=>el('ciara-connection-editor').classList.toggle('hidden'));
  el('ciara-save-url').addEventListener('click',configureUrl);
  el('close-selenium-tools').addEventListener('click',()=>{el('advanced-config').open=false;});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')el('advanced-config').open=false;});
  el('ciara-all-cases').addEventListener('click',()=>el('ciara-case-checks').querySelectorAll('input[type="checkbox"]').forEach(b=>b.checked=true));
  el('ciara-select-cases').addEventListener('toggle',()=>{if(el('ciara-select-cases').open)void loadPreview();});
  el('ciara-easy-form').addEventListener('submit',launch);
  el('open-robot-tools').addEventListener('click',()=>showTab('robot'));
  el('open-ai-tools').addEventListener('click',()=>showTab('assistant'));
  el('open-selenium-tools').addEventListener('click',()=>{
    const panel=el('advanced-config');panel.open=true;updateEngine('selenium');
    panel.scrollTop=0;
  });
  void setup();
})();

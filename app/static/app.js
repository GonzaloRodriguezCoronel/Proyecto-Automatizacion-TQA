/* TQA Automation Center v5 · Una sola consola para Estándar, Selenium y Robot. */
'use strict';
const $=id=>document.getElementById(id);
const E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const jsonHeaders={'Content-Type':'application/json'};
let catalog=[], history=[], sideProjects=[], sideSelected=null, activeId=null, selectedEngine='standard';
let timer=null, lastShot='', latestRun=null, lastFailure=null, lastMiniMode=null, seleniumTemplates=null;
let robotArtifactTimer=null, robotRunId=null, robotPolling=false;
async function api(path,options={}){const response=await fetch(path,options);const data=await response.json().catch(()=>({}));if(!response.ok){let detail=data.detail;if(Array.isArray(detail))detail=detail.map(v=>v.msg).join('; ');throw new Error(detail||`Error HTTP ${response.status}`);}return data;}
function showTab(tab){document.querySelectorAll('.section').forEach(s=>s.classList.toggle('hidden',s.id!=='section-'+tab));document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));if(tab==='stats')loadStats();if(tab==='history')refreshHistory();if(tab==='runner'&&!activeId)loadStats();if(tab==='robot'&&robotRunId)void refreshRobotArtifacts(robotRunId);}
function statusPill(status){return `<span class="status-pill ${E(status).replaceAll(' ','-')}">${E(status)}</span>`;}
function allowed(){return catalog.filter(c=>c.targets.includes($('target').value)&&c.kind===$('kind').value);}
function renderSuites(){const suites=[...new Set(allowed().map(c=>c.suite))];const prior=$('suite').value;const choice=suites.includes(prior)?prior:(suites[0]||'');$('suite').innerHTML=suites.map(s=>`<option value="${E(s)}">${E(s)}</option>`).join('');$('suite').value=choice;$('suite-grid').innerHTML=suites.map(s=>{const count=allowed().filter(c=>c.suite===s).length;return `<button type="button" class="suite-card ${s===choice?'selected':''}" data-suite="${E(s)}"><span>${E(s)}</span><small>${count} caso${count!==1?'s':''}</small></button>`;}).join('')||'<p class="run-muted">Sin categorías para esta aplicación.</p>';$('suite-grid').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('suite').value=b.dataset.suite;renderSuites();});renderCases();}
function renderCases(){const cases=allowed().filter(c=>c.suite===$('suite').value);const specific=document.querySelector('input[name="selection"]:checked').value==='specific';$('case-picker').classList.toggle('disabled',!specific);$('case-picker').innerHTML=cases.map(c=>`<div class="case"><input type="checkbox" class="case-check" value="${E(c.id)}" id="pick-${E(c.id)}" ${specific?'':'disabled'}><label for="pick-${E(c.id)}">${E(c.name)}<small>${E(c.id)} · ${E(c.expected)}</small></label></div>`).join('');$('suite-count').textContent=cases.length+' casos';}
function updateEngine(engine){selectedEngine=engine;document.querySelectorAll('.engine').forEach(b=>b.classList.toggle('active',b.dataset.engine===engine));$('standard-config').classList.toggle('hidden',engine!=='standard');$('selenium-config').classList.toggle('hidden',engine!=='selenium');$('robot-config').classList.toggle('hidden',engine!=='robot');$('selenium-visual-config').classList.toggle('hidden',engine!=='selenium');if(engine==='selenium'){void loadSideProjects();void loadSeleniumTemplates();}if(engine==='robot'&&$('target').value==='CIARÁ'&&$('robot-path').value==='/demo/login')$('robot-path').value='/';}
function showError(message){$('form-error').textContent=message||'';}
async function loadSeleniumTemplates(){
  if(!seleniumTemplates){try{seleniumTemplates=(await api('/api/selenium/templates')).kinds;}catch(err){showError(err.message);return;}}
  renderSeleniumCategories();
}
function renderSeleniumCategories(){
  if(!seleniumTemplates)return;
  const kind=$('selenium-kind').value;
  const categories=Object.keys(seleniumTemplates[kind]||{});
  const previous=$('selenium-category').value;
  $('selenium-category').innerHTML=categories.map(cat=>`<option value="${E(cat)}">${E(cat)}</option>`).join('');
  if(categories.includes(previous))$('selenium-category').value=previous;
  renderSeleniumTemplates();
}
function renderSeleniumTemplates(){
  if(!seleniumTemplates)return;
  const kind=$('selenium-kind').value,cat=$('selenium-category').value;
  const entries=Object.entries(seleniumTemplates[kind]?.[cat]||{});
  const previous=$('selenium-template').value;
  $('selenium-template').innerHTML=entries.map(([key,value])=>`<option value="${E(key)}">${E(value)}</option>`).join('');
  if(entries.some(([key])=>key===previous))$('selenium-template').value=previous;
  renderSeleniumForm();
}
function renderSeleniumForm(){
  const t=$('selenium-template').value;
  $('selenium-selector-row').classList.toggle('hidden',t!=='elemento');
  $('selenium-limit-row').classList.toggle('hidden',t!=='tiempo');
  $('selenium-creation-hint').textContent=({
    pagina:'Comprobará la apertura de la pantalla y la presencia del documento HTML.',
    elemento:'Comprobará si Selenium encuentra y muestra el elemento usando tu selector.',
    login_ok:'Completará el login de demostración con datos de prueba y validará el resultado.',
    login_fail:'Introducirá credenciales de prueba incorrectas y validará el rechazo.',
    tiempo:'Medirá Navigation Timing en un solo navegador y lo comparará con tu límite. No es una prueba de carga.',
    accesibilidad:'Revisará imágenes sin alt, controles sin etiqueta y botones sin nombre. No es auditoría WCAG completa.',
    responsive:'Abrirá la página a 375px y comprobará si existe desbordamiento horizontal.',
    repetir:'Abrirá la misma pantalla 3 veces y comprobará la disponibilidad de su contenido.'
  })[t]||'Se guardarán los pasos y se ejecutarán con Selenium WebDriver.';
}
async function createSeleniumTest(){
  const button=$('selenium-create');button.disabled=true;
  $('selenium-create-status').textContent='Creando prueba automatizada…';showError('');
  try{
    const payload={target:$('target').value,kind:$('selenium-kind').value,
      category:$('selenium-category').value,template:$('selenium-template').value,
      name:$('selenium-name').value,page_path:$('selenium-path').value,
      selector:$('selenium-selector').value,max_ms:Number($('selenium-limit').value)};
    const project=await api('/api/selenium/generate',{method:'POST',headers:jsonHeaders,body:JSON.stringify(payload)});
    await loadSideProjects();$('side-project').value=project.id;await loadSidePreview();
    $('selenium-create-status').textContent='✓ Nueva prueba guardada. Quedó seleccionada para ejecutarla con el botón «Ejecutar pruebas».';
  }catch(err){$('selenium-create-status').textContent='ERROR: '+err.message;}
  finally{button.disabled=false;}
}
// v7: Creador de pasos independientes del login y recorrido general de HTML.
const customSteps=[];
const customCategories={
  'Funcionales':['Smoke','Sanity','Regresión','Integración','E2E','Personalizadas','Recorrido general'],
  'No funcionales':['Rendimiento','Accesibilidad','Responsividad','Estabilidad','Personalizadas']
};
const stepsRequireValue=new Set(['assertText','assertValue','type','select']);
function renderCustomCategories(){
  const kind=$('custom-kind').value,previous=$('custom-category').value;
  const cats=customCategories[kind];
  $('custom-category').innerHTML=cats.map(x=>`<option value="${E(x)}">${E(x)}</option>`).join('');
  $('custom-category').value=cats.includes(previous)?previous:(kind==='No funcionales'?'Rendimiento':'Personalizadas');
}
function renderCustomSteps(){
  $('custom-step-list').innerHTML=customSteps.length?customSteps.map((step,i)=>`<div class="custom-step-row"><div><b>${i+1}. ${E(step.command)}</b><small>${E(step.target)}${step.value?' · '+E(step.command==='type'?'Dato de prueba':step.value):''}</small></div><button type="button" class="custom-remove" data-idx="${i}" aria-label="Eliminar paso ${i+1}">✕</button></div>`).join(''):'<p class="run-muted" style="padding:11px">Añade al menos un paso. Es obligatorio incluir una validación.</p>';
  $('custom-step-list').querySelectorAll('.custom-remove').forEach(button=>button.onclick=()=>{customSteps.splice(Number(button.dataset.idx),1);renderCustomSteps();});
}
function customElementSelected(){const selector=$('custom-select-element').value;if(selector)$('custom-step-target').value=selector;}
async function inspectCustom(){
  $('custom-inspect').disabled=true;$('custom-inspect-status').textContent='Explorando el HTML de la página…';
  try{
    const path='/api/selenium/inspect?'+new URLSearchParams({target:$('target').value,page_path:$('custom-path').value});
    const d=await api(path);
    const locators=[{selector:'css=body',label:'Documento completo (body)'},...d.elements];
    const unique=[...new Map(locators.map(x=>[x.selector,x])).values()];
    $('custom-select-element').innerHTML=unique.map(x=>`<option value="${E(x.selector)}">${E(x.tag||'html')} · ${E(x.label)} — ${E(x.selector)}</option>`).join('');
    $('custom-select-element').value=(d.elements.find(e=>e.tag==='h1')||d.elements[0]||{selector:'css=body'}).selector;
    customElementSelected();
    $('custom-inspect-status').textContent=`✓ ${d.elements.length} elementos, ${d.links.length} enlaces internos detectados. ${d.title||''}. Los XPath se comprobarán durante Selenium.`;
  }catch(err){$('custom-inspect-status').textContent='No se pudo inspeccionar: '+err.message;}
  finally{$('custom-inspect').disabled=false;}
}
function addCustomStep(){
  const command=$('custom-action').value,target=$('custom-step-target').value.trim(),value=$('custom-step-value').value.trim();
  const status=$('custom-create-status');
  if(customSteps.length>=24){status.textContent='Máximo 24 pasos por caso.';return;}
  if(!target){status.textContent='Selecciona o escribe un localizador, título o tamaño de ventana.';return;}
  if(stepsRequireValue.has(command)&&!value){status.textContent='Escribe el texto esperado o dato de prueba para este paso.';return;}
  customSteps.push({command,target,value});renderCustomSteps();
  status.textContent=`✓ ${customSteps.length} pasos preparados. Añade una validación para que la prueba tenga un resultado comprobable.`;
}
async function saveGeneratedProject(endpoint,payload,statusId,buttonId){
  const btn=$(buttonId);btn.disabled=true;$(statusId).textContent='Analizando y creando la prueba…';
  try{
    const data=await api(endpoint,{method:'POST',headers:jsonHeaders,body:JSON.stringify(payload)});
    await loadSideProjects();$('side-project').value=data.id;await loadSidePreview();
    $(statusId).textContent=`✓ ${data.count} caso(s) creados. Seleccionados debajo: introduce tu correo y pulsa «Ejecutar pruebas».`+
      (data.scan?.pages?` Páginas descubiertas: ${data.scan.pages.map(x=>x.path).join(', ')}. ${(data.scan.errors||[]).length} rutas no inspeccionadas.`:(data.scan?.path?` Pantalla revisada: ${data.scan.path}.`:''));
    $('side-project').scrollIntoView({block:'nearest',behavior:'smooth'});
    return data;
  }catch(err){$(statusId).textContent='ERROR: '+err.message;return null;}
  finally{btn.disabled=false;}
}
async function autoScreen(){
  const payload={target:$('target').value,kind:$('custom-kind').value,
    category:$('custom-category').value,name:$('custom-name').value,
    page_path:$('custom-path').value};
  await saveGeneratedProject('/api/selenium/auto-screen',payload,'custom-create-status','custom-auto');
}
async function saveCustom(){
  if(!customSteps.length){$('custom-create-status').textContent='Añade primero los pasos de tu prueba.';return;}
  const payload={target:$('target').value,kind:$('custom-kind').value,category:$('custom-category').value,
    name:$('custom-name').value,page_path:$('custom-path').value,steps:customSteps,
    allow_interactions:$('custom-allow').checked};
  await saveGeneratedProject('/api/selenium/custom',payload,'custom-create-status','custom-create');
}
async function saveGeneral(){
  const payload={target:$('target').value,start_path:$('general-start').value,max_pages:Number($('general-pages').value)};
  await saveGeneratedProject('/api/selenium/general',payload,'general-status','general-create');
}
function setupAdvancedSelenium(){
  $('custom-kind').onchange=renderCustomCategories;
  $('custom-select-element').onchange=customElementSelected;
  $('custom-inspect').onclick=inspectCustom;
  $('custom-add').onclick=addCustomStep;
  $('custom-create').onclick=saveCustom;
  $('custom-auto').onclick=autoScreen;
  $('general-create').onclick=saveGeneral;
  $('custom-action').onchange=()=>{
    const action=$('custom-action').value;
    $('custom-step-value').placeholder=stepsRequireValue.has(action)?'Valor requerido para esta acción':'No aplica para este comando';
    if(action==='setWindowSize')$('custom-step-target').value='375x812';
    if(action==='pause')$('custom-step-target').value='700';
  };
  renderCustomCategories();renderCustomSteps();
}
function renderCaseTracker(run,live){
  const entries=live?.case_states;
  if(!Array.isArray(entries)||!entries.length)return;
  const completed=new Map((run.cases||[]).map(c=>[c.id,c]));
  const done=entries.filter(e=>!['PENDIENTE','EN CURSO'].includes(e.status)).length;
  $('summary-caption').textContent=`${done} de ${entries.length} casos finalizados · progreso individual en tiempo real`;
  $('live-case-list').innerHTML=entries.map((entry,i)=>{
    const c=completed.get(entry.id),running=entry.status==='EN CURSO';
    const status=entry.status;
    const state=running?'active':status==='PASS'?'finished-pass':status==='FAIL'?'finished-fail':'';
    const steps=c?.steps?.map((st,j)=>`${j+1}. ${st.action}\nEsperado: ${st.expected}\nObservado: ${st.observed}`).join('\n\n')||'';
    const filenames=c?[...(c.evidence||[]),...(c.artifacts||[]),...(c.video?[c.video]:[])]:[];
    const fileLinks=filenames.map(f=>`<a class="case-link" target="_blank" href="/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(f)}">${E(f)}</a>`).join(' · ');
    return `<article class="test-result case-tracker ${state}"><div class="row"><div><strong>${i+1}. ${E(entry.name)}</strong><small>${E(entry.id)}${entry.duration_s?' · '+E(entry.duration_s)+' s':''}</small></div>${statusPill(status)}</div>`+
    (c?`<details class="result-detail"><summary>Pasos, XPath y evidencias</summary><p class="run-muted">${E(c.observation||'')}</p><pre>${E(steps||'Sin pasos detallados')}</pre>${c.video?`<video controls preload="metadata" src="/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(c.video)}"></video>`:''}<div>${fileLinks}</div></details>`:
    `<small>${running?'Selenium está ejecutando esta prueba…':status==='PENDIENTE'?'En cola, esperando turno':E(entry.observation||'')}</small>`)+`</article>`;
  }).join('');
}
async function loadSideProjects(){try{const projects=await api('/api/selenium/projects');sideProjects=projects;const previous=$('side-project').value;$('side-project').innerHTML=projects.map(p=>`<option value="${E(p.id)}">${E(p.name)}</option>`).join('');if(projects.some(p=>p.id===previous))$('side-project').value=previous;else if(projects.some(p=>p.id==='DEMO'))$('side-project').value='DEMO';await loadSidePreview();}catch(err){showError(err.message);}}
async function loadSidePreview(){if(!$('side-project').value){$('side-test-picker').textContent='No hay proyectos disponibles';return;}try{sideSelected=await api('/api/selenium/projects/'+encodeURIComponent($('side-project').value));$('side-test-picker').innerHTML=sideSelected.tests.map(t=>`<div class="case"><input type="checkbox" class="side-checkbox" id="side-${E(t.id)}" value="${E(t.id)}" checked><label for="side-${E(t.id)}">${E(t.name)}<small>${t.count} comandos${t.unsupported.length?' · Incompatibles: '+E(t.unsupported.join(', ')):''}</small></label></div>`).join('');const pinned=sideSelected.tests.find(t=>t.target)?.target;
  if(pinned&&$('target').value!==pinned){$('target').value=pinned;renderSuites();}
  const download=$('selenium-export');download.href='/api/selenium/projects/'+encodeURIComponent($('side-project').value)+'/export';download.classList.remove('hidden');
  $('side-preview').innerHTML=sideSelected.tests.map(t=>`<div class="side-block"><h3>${E(t.name)}</h3><table class="side-step-table"><thead><tr><th>Paso</th><th>Comando</th><th>Selector</th><th>Valor (protegido)</th></tr></thead><tbody>${t.commands.map((c,i)=>`<tr><td>${i+1}</td><td>${E(c.command)}</td><td><code>${E(c.target)}</code></td><td>${E(c.value)}</td></tr>`).join('')}</tbody></table></div>`).join('');if(sideSelected.id==='DEMO'&&$('target').value!=='Demo local'){$('target').value='Demo local';renderSuites();}}catch(err){showError(err.message);}}
async function importSide(evt){evt.preventDefault();const file=$('side-file').files[0];if(!file){$('side-import-status').textContent='Selecciona un archivo .side válido';return;}$('side-import-btn').disabled=true;$('side-import-status').textContent='Importando…';try{const data=new FormData();data.append('file',file,file.name);const created=await api('/api/selenium/import',{method:'POST',body:data});$('side-import-status').textContent=`Proyecto importado: ${created.name}. ${created.count} casos.`;await loadSideProjects();$('side-project').value=created.id;await loadSidePreview();}catch(err){$('side-import-status').textContent='ERROR: '+err.message;}finally{$('side-import-btn').disabled=false;}}
function resetMonitor(){lastShot='';$('side-live-shot').classList.add('hidden');$('browser-empty').classList.remove('hidden');$('side-live-bar-fill').style.width='0%';$('progress-percent').textContent='0%';$('side-live-log').innerHTML='<div class="log-row">Preparando ejecución…</div>';$('live-case-list').innerHTML='<div class="case-placeholder">El motor se está preparando.</div>';$('monitor-evidence').classList.add('hidden');$('monitor-evidence').innerHTML='';for(let n=1;n<=4;n++)$('stage-'+n).classList.remove('on');$('download-pdf').removeAttribute('href');$('download-html').removeAttribute('href');$('download-pdf').classList.add('disabled');$('download-html').classList.add('disabled');$('open-evidence').disabled=true;$('sum-pass').textContent='0';$('sum-fail').textContent='0';$('sum-other').textContent='0';$('email-outcome').textContent='Se enviarán los dos informes al finalizar.';}
async function startUnified(evt){evt.preventDefault();showError('');$('run-btn').disabled=true;try{const target=$('target').value,email=$('email').value;let url,body;if(selectedEngine==='standard'){const specific=document.querySelector('input[name="selection"]:checked').value==='specific';const case_ids=specific?[...document.querySelectorAll('.case-check:checked')].map(c=>c.value):[];if(specific&&!case_ids.length)throw new Error('Selecciona al menos un caso de prueba.');url='/api/runs';body={target,kind:$('kind').value,suite:$('suite').value,email,case_ids};}else if(selectedEngine==='selenium'){const test_ids=[...document.querySelectorAll('.side-checkbox:checked')].map(c=>c.value);if(!test_ids.length)throw new Error('Selecciona al menos un caso Selenium IDE.');url='/api/selenium/start';body={project_id:$('side-project').value,target,email,test_ids,view_mode:document.querySelector('input[name="viewmode"]:checked').value};}else{url='/api/robot/start';body={target,page_path:$('robot-path').value,email};}const response=await api(url,{method:'POST',headers:jsonHeaders,body:JSON.stringify(body)});activeId=response.id;resetMonitor();showTab('runner');$('monitor-status').textContent='INICIANDO';$('monitor-status').className='status-chip running';$('monitor-title').textContent='Iniciando automatización';$('monitor-description').textContent=selectedEngine==='selenium'?'Selenium WebDriver · Capturas dentro del panel':(selectedEngine==='robot'?'Robot Framework · Inspección de XPath':'Motor estándar · Pruebas reales');startPolling(activeId);if(selectedEngine==='robot')startRobotArtifactTracking(activeId);await loadStats();}catch(err){showError(err.message);$('run-btn').disabled=false;}}
function setStages(run){const status=run.status,complete=['FINALIZADA','FALLIDA'].includes(status);const inProgress=status==='EN CURSO';$('stage-1').classList.toggle('on',status!=='PENDIENTE');$('stage-2').classList.toggle('on',inProgress||complete);$('stage-3').classList.toggle('on',complete);$('stage-4').classList.toggle('on',complete&&run.email_status!=='PENDIENTE');}
function liveEventLog(events){const filtered=(events||[]).filter(e=>['browser_open','step_start','step_done','case_start','case_done'].includes(e.type));const display=filtered.slice(-28);if(!display.length)return '<div class="log-row">Esperando el inicio del motor…</div>';return display.map(e=>{const time=e.step?`Paso ${e.step}${e.total?'/'+e.total:''}`:(e.type==='browser_open'?'Chrome':'Caso');let text='';let cls='';if(e.type==='browser_open')text='Navegador controlado por Selenium iniciado';if(e.type==='case_start')text=`Iniciando ${E(e.name||e.case)}`;if(e.type==='case_done'){text=`${E(e.name||e.case)} — ${E(e.status||'')} ${E(e.observed||'').slice(0,180)}`;cls=e.status==='PASS'?'pass':(e.status==='FAIL'?'fail':'');}if(e.type==='step_start')text=`Ejecutando: ${E(e.command||'')}`;if(e.type==='step_done'){text=`${E(e.command||'')} — ${E(e.status)}. ${E(e.observed||'')}${e.xpath?' · XPath: '+E(e.xpath):''}`;cls=e.status==='PASS'?'pass':'fail';}return `<div class="log-row ${cls}"><span class="log-time">${E(time)}</span>${text}</div>`;}).join('');}
function renderLive(run,live){if(run.id!==activeId)return;const shot=live?.latest_screenshot||'';if(shot&&shot!==lastShot){lastShot=shot;const image=$('side-live-shot');image.src=`/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(shot)}`;image.classList.remove('hidden');$('browser-empty').classList.add('hidden');$('capture-caption').textContent='Evidencia real: '+shot;}const completed=live?.completed_cases??run.cases.length,total=live?.total_cases||run.selected_cases.length||1;const progress=Math.min(100,Math.round(100*completed/total));$('side-live-bar-fill').style.width=progress+'%';$('progress-percent').textContent=progress+'%';$('case-progress-label').textContent=`Progreso: ${completed} de ${total} casos`;$('side-live-counter').textContent=(live?.total?`${live.current} / ${live.total} pasos · `:'')+`${completed} / ${total} casos`;$('side-live-log').innerHTML=liveEventLog(live?.events);$('side-live-log').scrollTop=$('side-live-log').scrollHeight;}
function renderResults(run){latestRun=run;const finished=['FINALIZADA','FALLIDA'].includes(run.status),s=run.summary;$('monitor-title').textContent=run.suite+' · '+(finished?'Ejecución terminada':'Automatización en curso');$('monitor-description').textContent=`${run.target} · ${run.id} · ${run.duration_s||0} s`;$('browser-target').textContent=run.target+' / '+run.suite;$('monitor-status').textContent=run.status;$('monitor-status').className='status-chip '+(finished?(run.global_status==='PASS'?'finished':'failed'):'running');setStages(run);$('sum-pass').textContent=s.PASS;$('sum-fail').textContent=s.FAIL;$('sum-other').textContent=s.SKIPPED+s['NOT RUN'];$('stat-pass').textContent=s.PASS;$('stat-fail').textContent=s.FAIL;$('summary-caption').textContent=`${run.cases.length} de ${run.selected_cases.length} casos registrados`;
 const records=[...run.cases];const pending=run.selected_cases.filter(id=>!run.cases.some(c=>c.id===id));$('live-case-list').innerHTML=records.map(c=>{const links=[...(c.evidence||[]),...(c.artifacts||[])].map(name=>`<a class="case-link" target="_blank" href="/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(name)}">${E(name)}</a>`).join(' &nbsp; ');const steps=(c.steps||[]).map((t,i)=>`${i+1}. ${t.action}\nEsperado: ${t.expected}\nObservado: ${t.observed}`).join('\n\n');return `<div class="test-result"><div class="row"><div><strong>${E(c.name||c.id)}</strong><small>${E(c.id)} · ${E(c.duration_s)} s</small></div>${statusPill(c.status)}</div><details class="result-detail"><summary>Detalle y evidencias</summary><p class="run-muted">${E(c.observation)}</p><pre>${E(steps||'Sin pasos registrados')}</pre>${c.video?`<video controls preload="metadata" src="/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(c.video)}"></video><p class="run-muted">MP4 construido con capturas por paso.</p>`:''}<div>${links}</div></details></div>`;}).join('')+pending.map(id=>`<div class="test-result"><div class="row"><div><strong>${E(id)}</strong><small>Esperando ejecución…</small></div>${statusPill('PENDIENTE')}</div></div>`).join('');if(!records.length&&!pending.length)$('live-case-list').innerHTML='<div class="case-placeholder">Preparando casos…</div>';
 $('email-outcome').textContent=finished?`Correo: ${run.email_status} ${run.email_error||''}`:'Los reportes se enviarán cuando finalice.';$('assistant-summary').textContent=finished?`Resultado global: ${run.global_status}. ${s.PASS} PASS, ${s.FAIL} FAIL, ${s.SKIPPED+s['NOT RUN']} sin ejecutar u omitidos. Tiempo: ${run.duration_s} segundos.`:`En ejecución: ${records.length} casos registrados. Los resultados proceden de pruebas reales.`;
 const failure=records.find(c=>c.status==='FAIL');lastFailure=failure?.id||null;$('analyze-last').disabled=!failure;let links=[];for(const c of records){for(const f of [...(c.evidence||[]),...(c.artifacts||[]),...(c.video?[c.video]:[])]){if(!links.some(x=>x.name===f))links.push({name:f,url:`/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(f)}`});}}$('monitor-evidence').innerHTML=links.map(x=>`<a href="${x.url}" target="_blank">↗ ${E(x.name)}</a>`).join('')||'<span class="run-muted">No se capturaron archivos para esta ejecución.</span>';$('open-evidence').disabled=links.length===0;
 if(finished){$('download-pdf').classList.remove('disabled');$('download-html').classList.remove('disabled');$('download-pdf').href=`/api/runs/${encodeURIComponent(run.id)}/download/pdf`;$('download-html').href=`/api/runs/${encodeURIComponent(run.id)}/download/html`;}else{$('download-pdf').classList.add('disabled');$('download-html').classList.add('disabled');}}
async function pollRun(id){if(id!==activeId)return;try{const run=await api('/api/runs/'+encodeURIComponent(id));const live=await api('/api/runs/'+encodeURIComponent(id)+'/live').catch(()=>null);renderResults(run);renderLive(run,live);renderCaseTracker(run,live);if(['FINALIZADA','FALLIDA'].includes(run.status)&&run.email_status!=='PENDIENTE'){clearInterval(timer);timer=null;$('run-btn').disabled=false;await refreshHistory();await loadStats();}}catch(err){showError(err.message);}}
function startPolling(id){if(timer){clearInterval(timer);timer=null;}void pollRun(id);timer=setInterval(()=>void pollRun(id),900);}
async function inspectRun(id){activeId=id;resetMonitor();showTab('runner');startPolling(id);}window.inspectRun=inspectRun;
async function refreshHistory(){try{history=await api('/api/runs');$('stat-runs').textContent=history.length;$('history-body').innerHTML=history.length?`<table class="history-table"><thead><tr><th>Ejecución</th><th>Aplicación / motor</th><th>Estado</th><th>Resultado</th><th>Correo</th><th></th></tr></thead><tbody>${history.map(r=>`<tr><td>${E(r.id)}<br><small>${E(r.created_at)}</small></td><td>${E(r.target)}<br><small>${E(r.suite)}</small></td><td>${E(r.status)}</td><td>${statusPill(r.global_status)}</td><td>${E(r.email_status)}</td><td><button onclick="inspectRun('${E(r.id)}')">Ver</button></td></tr>`).join('')}</tbody></table>`:'<div class="case-placeholder">Todavía no se han ejecutado pruebas.</div>';}catch(err){$('history-body').textContent=err.message;}}
async function loadStats(){try{const data=await api('/api/estadisticas');$('stat-rate').textContent=data.success_rate+'%';$('stat-runs').textContent=data.runs;const metrics=[['Ejecuciones',data.runs,'Registradas'],['Casos',data.cases,'Total con resultado'],['Tasa PASS',data.success_rate+'%','Sobre todos los estados'],['Tiempo promedio',data.average_duration_s+' s','Ejecuciones terminadas']];$('stats-cards').innerHTML=metrics.map(([name,val,desc])=>`<article class="metric"><div class="metric-icon">▥</div><div><span>${E(name)}</span><strong>${E(val)}</strong><small>${E(desc)}</small></div></article>`).join('');const max=Math.max(1,...Object.values(data.counts));$('stats-status').innerHTML=Object.entries(data.counts).map(([k,v])=>`<div class="stat-bar-row"><b>${E(k)}</b><div class="stat-track"><div class="stat-fill ${E(k).replaceAll(' ','-')}" style="width:${v/max*100}%"></div></div><b>${v}</b></div>`).join('');const high=Math.max(1,...data.daily.map(d=>d.runs));$('stats-daily').innerHTML=data.daily.length?`<div class="stat-daily">${data.daily.map(d=>`<div class="stat-day"><strong>${d.runs}</strong><div class="bar" style="height:${Math.max(6,d.runs/high*125)}px"></div><small>${E(d.date.slice(5))}</small></div>`).join('')}</div>`:'<p class="run-muted">Sin actividad reciente.</p>';$('stats-suites').innerHTML=data.suites.length?`<table class="history-table"><thead><tr><th>Suite</th><th>Total</th><th>PASS</th><th>FAIL</th><th>Otros</th></tr></thead><tbody>${data.suites.map(x=>`<tr><td>${E(x.name)}</td><td>${x.total}</td><td>${x.PASS}</td><td>${x.FAIL}</td><td>${x.other}</td></tr>`).join('')}</tbody></table>`:'<p class="run-muted">Sin suites ejecutadas.</p>';}catch(err){$('stats-status').textContent=err.message;}}
async function requestAI(caseId, mode, runId){return await api('/api/assistant',{method:'POST',headers:jsonHeaders,body:JSON.stringify({case_id:caseId,mode,run_id:runId||null})});}
async function getAssistance(){const button=$('ai-btn');button.disabled=true;$('ai-output').textContent='Generando propuesta…';try{const data=await requestAI($('ai-case').value,$('ai-mode').value,activeId);$('ai-provider').textContent=data.provider+' · '+data.notice;$('ai-output').textContent=data.text;}catch(err){$('ai-output').textContent=err.message;}finally{button.disabled=false;}}
async function analyzeLast(){if(!lastFailure)return;$('mini-ai-output').classList.remove('hidden');$('mini-ai-output').textContent='Analizando…';try{if(!catalog.some(c=>c.id===lastFailure)){const found=latestRun.cases.find(c=>c.id===lastFailure);$('mini-ai-output').textContent=`Caso Selenium: ${found.name}\n${found.observation}\n\nRevisa los pasos y el XPath registrados. El asistente de API solo analiza casos del catálogo interno.`;return;}const answer=await requestAI(lastFailure,'analysis',activeId);$('mini-ai-output').textContent=`${answer.provider}\n\n${answer.text}`;}catch(err){$('mini-ai-output').textContent=err.message;}}
// TQA v6.1: seguimiento real de la generacion de Gherkin, Robot y XPath.
function renderRobotArtifacts(run, files){
  const finished=['FINALIZADA','FALLIDA'].includes(run.status);
  const caseResult=run.cases?.[0];
  const summary=caseResult?.observation||run.error||'Inspeccionando el DOM y preparando los archivos...';
  const assets=files.artifacts||[];
  const links=assets.map(name=>`<a class="export-link" href="/api/runs/${encodeURIComponent(run.id)}/evidence/${encodeURIComponent(name)}" target="_blank" rel="noopener">↓ ${E(name)}</a>`).join(' ');
  const reports=finished&&run.email_status!=='PENDIENTE'
    ?`<div class="robot-downloads"><a class="export-link" href="/api/runs/${encodeURIComponent(run.id)}/download/pdf" target="_blank" rel="noopener">↓ Informe PDF</a><a class="export-link" href="/api/runs/${encodeURIComponent(run.id)}/download/html" target="_blank" rel="noopener">↓ Reporte HTML</a></div>`:'';
  $('robot-result').innerHTML=`<div class="robot-run-summary"><strong>Ejecucion ${E(run.id)}</strong>${statusPill(run.status)}<p class="run-muted">Resultado: ${E(run.global_status||'PENDIENTE')} · ${E(run.duration_s||0)} s</p><p>${E(summary)}</p><p class="run-muted">Correo: ${E(run.email_status||'PENDIENTE')} ${E(run.email_error||'')}</p></div><div class="robot-downloads">${links}</div>${reports}<button type="button" class="secondary-btn" id="robot-show-monitor">Ver monitor de ejecucion</button>`;
  $('robot-show-monitor').onclick=()=>void inspectRun(run.id);
  $('robot-gherkin').textContent=files.gherkin|| (finished?'No se genero Gherkin. Revisa el resultado de inspeccion y sus dependencias.':'Generando escenario desde la pagina real...');
  $('robot-code').textContent=files.robot_code|| (finished?'No se genero un script Robot. Revisa el estado anterior.':'Preparando el script .robot...');
  const elements=files.scan?.elements||[];
  $('robot-locators').innerHTML=elements.length
    ?`<div class="robot-locator-table"><table class="side-step-table"><thead><tr><th>Elemento</th><th>Etiqueta</th><th>XPath verificado</th></tr></thead><tbody>${elements.map(el=>`<tr><td>${E(el.tag)}</td><td>${E(el.label)}</td><td><code>${E(el.xpath)}</code></td></tr>`).join('')}</tbody></table></div>`
    :`<p class="run-muted">${finished?'No hay XPath disponibles. El navegador puede no haber conseguido inspeccionar la pagina.':'Buscando XPath unicos y verificables en el DOM...'}</p>`;
  $('robot-btn').disabled=!finished;
  return finished;
}
async function refreshRobotArtifacts(id){
  if(!id||robotPolling)return;
  robotPolling=true;
  try{
    const [run,files]=await Promise.all([
      api('/api/runs/'+encodeURIComponent(id)),
      api('/api/robot/runs/'+encodeURIComponent(id))
    ]);
    if(id!==robotRunId)return;
    const finished=renderRobotArtifacts(run,files);
    if(finished){
      if(robotArtifactTimer){clearInterval(robotArtifactTimer);robotArtifactTimer=null;}
      if(run.email_status!=='PENDIENTE')await refreshHistory();
    }
  }catch(err){
    if(id===robotRunId){$('robot-error').textContent='Error al consultar Robot: '+err.message;$('robot-btn').disabled=false;}
  }finally{robotPolling=false;}
}
function startRobotArtifactTracking(id){
  robotRunId=id;
  if(robotArtifactTimer){clearInterval(robotArtifactTimer);robotArtifactTimer=null;}
  $('robot-result').textContent='Iniciando inspeccion del DOM...';
  $('robot-gherkin').textContent='Esperando inspeccion de la pagina...';
  $('robot-code').textContent='Preparando instrucciones Robot Framework...';
  $('robot-locators').textContent='Buscando y comprobando XPath...';
  void refreshRobotArtifacts(id);
  robotArtifactTimer=setInterval(()=>void refreshRobotArtifacts(id),1300);
}
async function startRobotStandalone(evt){
  evt.preventDefault();$('robot-btn').disabled=true;$('robot-error').textContent='';
  $('robot-result').textContent='Solicitando la ejecucion Robot...';
  try{
    const response=await api('/api/robot/start',{method:'POST',headers:jsonHeaders,
      body:JSON.stringify({target:$('robot-target').value,page_path:$('robot-path-panel').value,email:$('robot-email').value})});
    activeId=response.id;
    resetMonitor();
    startPolling(activeId);
    // Permanecemos en Robot + XPath: el usuario ve aqui los archivos generados.
    startRobotArtifactTracking(activeId);
  }catch(err){$('robot-error').textContent=err.message;$('robot-result').textContent='No se pudo iniciar la inspeccion.';$('robot-btn').disabled=false;}
}
function setup(){setupAdvancedSelenium();document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));document.querySelectorAll('.engine').forEach(b=>b.addEventListener('click',()=>updateEngine(b.dataset.engine)));$('target').onchange=()=>{renderSuites();$('selenium-path').value=$('target').value==='Demo local'?'/demo/login':'/';$('general-start').value=$('target').value==='Demo local'?'/demo/':'/';$('custom-path').value=$('target').value==='Demo local'?'/demo/reportes':'/';if(selectedEngine==='robot')$('robot-path').value=$('target').value==='Demo local'?'/demo/login':'/';};$('kind').onchange=renderSuites;document.querySelectorAll('input[name="selection"]').forEach(x=>x.onchange=renderCases);$('unified-run-form').onsubmit=startUnified;$('side-project').onchange=loadSidePreview;$('side-import-btn').onclick=importSide;$('selenium-kind').onchange=renderSeleniumCategories;$('selenium-category').onchange=renderSeleniumTemplates;$('selenium-template').onchange=renderSeleniumForm;$('selenium-create').onclick=createSeleniumTest;$('stats-refresh').onclick=loadStats;$('refresh-history').onclick=refreshHistory;$('ai-btn').onclick=getAssistance;$('analyze-last').onclick=analyzeLast;$('open-evidence').onclick=()=>$('monitor-evidence').classList.toggle('hidden');$('refresh-monitor').onclick=()=>{if(activeId)void pollRun(activeId);else{void loadStats();void refreshHistory();}};$('robot-form').onsubmit=startRobotStandalone;$('robot-target').onchange=()=>{$('robot-path-panel').value=$('robot-target').value==='Demo local'?'/demo/login':'/';};}
async function initialize(){setup();try{const data=await api('/api/catalog');catalog=data.cases;$('target').innerHTML=data.targets.map(x=>`<option value="${E(x)}">${E(x)}</option>`).join('');$('ai-case').innerHTML=catalog.map(c=>`<option value="${E(c.id)}">${E(c.id)} — ${E(c.name)}</option>`).join('');$('smtp-tip').textContent=data.smtp_configured?'✓ SMTP configurado: se enviarán PDF y HTML.':'⚠ Sin SMTP: los reportes se guardarán para descargar.';$('smtp-tip').classList.toggle('good',data.smtp_configured);$('connection').innerHTML='<span class="status-dot"></span> Servicio en línea';$('ai-status-mini').textContent=data.ai_configured?'IA configurada':'Plantillas locales';renderSuites();updateEngine('standard');await Promise.all([refreshHistory(),loadStats()]);const previousRobot=history.find(r=>r.suite==='Robot Framework');if(previousRobot){startRobotArtifactTracking(previousRobot.id);}}catch(err){$('connection').textContent='Error de conexión';showError(err.message);}}initialize();

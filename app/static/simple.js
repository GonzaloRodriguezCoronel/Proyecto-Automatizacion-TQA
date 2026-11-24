'use strict';
const $ = (id) => document.getElementById(id);
let activeRun = null;
let pollId = null;
let lastShot = '';
let completed = false;
let checks = null;

async function api(url, opts = {}) {
  const resp = await fetch(url, {cache:'no-store', ...opts});
  let data;
  try { data = await resp.json(); } catch { data = {}; }
  if (!resp.ok) {
    let msg = data.detail || 'No se pudo completar la solicitud (HTTP ' + resp.status + ').';
    if (Array.isArray(msg)) msg = msg.map(x => x.msg).join(' · ');
    throw new Error(msg);
  }
  return data;
}
function text(id, str){ $(id).textContent = String(str ?? ''); }
function element(tag, attrs={}, content='') {
  const el = document.createElement(tag);
  Object.entries(attrs).forEach(([name,val]) => el.setAttribute(name,val));
  if (content) el.textContent = content;
  return el;
}
function showError(err){$('error').hidden=false; text('error', err?.message || String(err));}
function clearError(){$('error').hidden=true;}
function setBusy(busy){$('start').disabled=busy; $('check').disabled=busy;}
function pathForType(){
  let path = $('page-path').value.trim() || '/';
  const type = document.querySelector('input[name=test_type]:checked')?.value;
  if (type === 'login' && (path === '/' || path === '/demo/')) return $('target').value === 'Demo local' ? '/demo/login' : '/login';
  return path;
}
async function load() {
  try {
    const setup = await api('/api/simple/setup');
    const target = $('target'); target.replaceChildren();
    setup.targets.forEach(value => target.append(element('option',{value},value)));
    target.value = setup.default_target; $('page-path').value = target.value === 'Demo local' ? '/demo/' : '/';
    const grid = $('test-types'); grid.replaceChildren();
    setup.types.forEach((type,i) => {
      const label = element('label',{class:'test-item'});
      const input = element('input',{type:'radio',name:'test_type',value:type.id});
      if (i === 0) input.checked = true;
      label.append(input, element('strong',{},type.name), element('small',{},type.detail));
      grid.append(label);
    });
    target.addEventListener('change',() => { $('page-path').value = target.value === 'Demo local' ? '/demo/' : '/'; setConnection('neutral','Seleccionaste otra aplicación. Comprueba su conexión antes de ejecutar.'); });
  } catch(e){showError(e);}
  await history();
}
function setConnection(level,message){
  const field=$('connection'); field.className='connection '+level; field.textContent=message;
}
async function checkConnection(){
  clearError();
  setConnection('neutral','Comprobando conexión con el servidor…');
  try {
    const data = await api('/api/simple/check?target='+encodeURIComponent($('target').value)+'&path='+encodeURIComponent(pathForType()));
    checks=data; setConnection(data.selenium_ready ? 'good' : data.connected ? 'warn' : 'bad',data.message);
  } catch(e){setConnection('bad',e.message);}
}
function bindRun(run){
  activeRun=run.id; completed=false; lastShot=''; clearError();
  $('progress-panel').hidden=false; $('result-summary').hidden=true;
  text('run-subtitle','Selenium está preparando '+run.cases+' caso(s) para '+run.target);
  text('run-status','Preparando'); $('run-status').className='status-chip active';
  text('progress-counter','0 de '+run.cases+' casos');text('progress-percent','0%');
  $('progress-fill').style.width='0%';
  $('browser-frame').replaceChildren(element('div',{class:'empty-screenshot'},'Preparando Chrome y capturas…'));
  $('events').replaceChildren(element('li',{},'Abriendo Selenium WebDriver…'));
  $('progress-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
async function start(){
  if (activeRun && !completed) return;
  clearError(); setBusy(true);
  try {
    const type=document.querySelector('input[name=test_type]:checked')?.value;
    if (!type) throw new Error('Selecciona un tipo de prueba.');
    text('action-help','Preparando casos con Selenium…');
    const data=await api('/api/simple/start',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({target:$('target').value,test_type:type,path:pathForType(),visible:$('visible').checked})
    });
    bindRun(data);
    if(pollId) clearInterval(pollId);
    await poll();
    pollId=setInterval(poll,1400);
  }catch(e){showError(e);setBusy(false);}
  finally{text('action-help','Resultados y reportes se guardan automáticamente.');}
}
async function poll(){
  if(!activeRun||completed)return;
  try {
    const result=await api('/api/runs/'+encodeURIComponent(activeRun)+'/live');
    const percent=result.total_cases?Math.min(100,Math.round(result.completed_cases/result.total_cases*100)):0;
    text('progress-counter',result.completed_cases+' de '+result.total_cases+' casos');
    text('progress-percent',percent+'%');$('progress-fill').style.width=percent+'%';
    const started=(result.events||[]).filter(x=>x.type==='step_start'||x.type==='step_done'||x.type==='browser_open'||x.type==='case_done');
    const list=$('events');list.replaceChildren();
    started.slice(-32).reverse().forEach(item=>{
      const li=element('li');
      const line=element('div',{class:'label'});
      const dot=element('span',{class:'dot '+(item.status==='PASS'?'pass':item.status==='FAIL'?'fail':'')});
      const label=item.type==='browser_open'?'Chrome iniciado':item.type==='step_start'?'Ejecutando paso '+item.step+'/'+item.total:
            item.type==='step_done'?'Paso '+item.step+': '+(item.status||''):'Caso terminado: '+(item.status||'');
      line.append(dot,document.createTextNode(label)); li.append(line);
      if(item.observed||item.command)li.append(element('span',{class:'detail'},item.observed||item.command));
      list.append(li);
    });
    if(!started.length)list.append(element('li',{},'Preparando pruebas…'));
    if (result.latest_screenshot && lastShot!==result.latest_screenshot){
      lastShot=result.latest_screenshot;
      const img=element('img',{src:'/api/runs/'+encodeURIComponent(activeRun)+'/evidence/'+encodeURIComponent(lastShot)+'?v='+Date.now(),alt:'Captura real del navegador Selenium'});
      $('browser-frame').replaceChildren(img);
    }
    const finished=result.status==='FINALIZADA'||result.status==='FALLIDA';
    text('run-status',finished?result.global_status||'FINALIZADA':'EN CURSO');
    $('run-status').className='status-chip '+(finished?(result.global_status==='PASS'?'ok':'fail'):'active');
    if(finished){completed=true; clearInterval(pollId);pollId=null;setBusy(false); await finishedReport();await history();}
  }catch(e){
    clearInterval(pollId);pollId=null;setBusy(false);showError(e);
  }
}
async function finishedReport(){
  const run=await api('/api/runs/'+encodeURIComponent(activeRun));
  text('run-subtitle','Ejecución finalizada · ID '+run.id+' · '+run.target);
  text('finished-at',run.finished_at||'');
  const counts={PASS:0,FAIL:0};
  (run.cases||[]).forEach(r=> {if(r.status==='PASS')counts.PASS++;if(r.status==='FAIL')counts.FAIL++;});
  text('n-pass',counts.PASS);text('n-fail',counts.FAIL);text('n-other',(run.cases||[]).length-counts.PASS-counts.FAIL);
  const cases=$('case-list');cases.replaceChildren();
  (run.cases||[]).forEach(row=>{const item=element('div',{class:'case-row'});item.append(element('span',{},row.name||row.id));item.append(element('b',{class:row.status==='PASS'?'pass':'fail'},row.status));cases.append(item);});
  if(run.error)cases.append(element('div',{class:'error'},'Error de ejecución: '+run.error));
  const id=encodeURIComponent(activeRun);
  $('dl-pdf').href='/api/runs/'+id+'/download/pdf';
  $('dl-html').href='/api/runs/'+id+'/download/html';
  $('dl-csv').href='/api/simple/runs/'+id+'/csv';
  $('dl-json').href='/api/simple/runs/'+id+'/json';
  $('dl-zip').href='/api/simple/runs/'+id+'/zip';
  $('result-summary').hidden=false;
}
async function history(){
  try {
    const runs=await api('/api/simple/history');
    const list=$('history-list');list.replaceChildren();
    if(!runs.length){list.append(element('p',{class:'muted'},'Aún no hay ejecuciones. Selecciona una prueba para comenzar.'));return;}
    runs.slice(0,8).forEach(run=>{
      const item=element('div',{class:'history-item'});
      const info=element('div');info.append(element('strong',{},run.suite),element('small',{},run.target+' · '+(run.created_at||'').replace('T',' ').slice(0,19)+' UTC'));
      const state=element('span',{class:'history-state'},run.global_status||run.status);
      item.append(info,state);
      if(run.status==='FINALIZADA'||run.status==='FALLIDA'){
        const link=element('a',{class:'history-action',href:'/api/simple/runs/'+encodeURIComponent(run.id)+'/zip'},'↓ Reportes');
        item.append(link);
      }
      list.append(item);
    });
  }catch(e){$('history-list').replaceChildren(element('p',{class:'muted'},'No se pudo leer el historial.'));}
}
$('check').addEventListener('click',checkConnection);
$('start').addEventListener('click',start);
$('refresh-history').addEventListener('click',history);
load();

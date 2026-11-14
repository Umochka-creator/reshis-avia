'use strict';
const $ = id => document.getElementById(id);
const rub = value => Math.round(Number(value)).toLocaleString('ru-RU');
const num = value => Math.round(Number(value)).toLocaleString('ru-RU');
let user = null;
let options = null;
let authMode = 'login';
let lastResponse = null;

async function api(endpoint, opts={}) {
  const res = await fetch(endpoint, { credentials: 'same-origin', ...opts,
    headers: {...(opts.body ? {'Content-Type':'application/json'} : {}), ...(opts.headers || {})}});
  let data;
  try { data = await res.json(); } catch { data = {detail: 'Некорректный ответ сервера'}; }
  if (!res.ok) {
    let detail = data.detail || 'Ошибка';
    if (Array.isArray(detail)) detail = detail.map(x=>x.msg || x).join('; ');
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return data;
}

function notice(message, bad=true) {
  const div=$('notification'); div.textContent=message; div.classList.remove('hidden');
  if(!bad) div.style.borderColor='#3d6d57'; else div.style.borderColor='#72553c';
}
function hideNotice(){ $('notification').classList.add('hidden'); }
function refreshAccount(){
  $('accountName').textContent = user ? user.username : 'Гостевой режим';
  $('authBtn').classList.toggle('hidden',!!user);
  $('logoutBtn').classList.toggle('hidden',!user);
}
function openAuth(mode='login'){
  authMode=mode; $('authTitle').textContent= mode==='login'?'Войти в систему':'Создать учётную запись';
  $('authSubmit').firstChild.textContent= mode==='login'?'Войти ':'Зарегистрироваться ';
  $('switchAuth').textContent=mode==='login'?'Нет аккаунта? Зарегистрироваться':'Есть аккаунт? Войти';
  $('authError').classList.add('hidden'); $('authModal').classList.remove('hidden');
  $('password').autocomplete=mode==='login'?'current-password':'new-password';
  $('username').focus();
}
function closeAuth(){ $('authModal').classList.add('hidden'); }

async function initialize(){
  try {
    options=await api('/api/options');
    const select=$('route'); select.replaceChildren();
    for (const route of options.routes) {
      const o=document.createElement('option'); o.value=route.code; o.textContent=`Москва — ${route.destination} (${route.code})`; select.append(o);
    }
    select.value='MOW-AER';
    $('date').min=options.date_min; $('date').max=options.date_max;
    setRouteBasePrice();
    $('dataDisclaimer').textContent='Базовые цены, чувствительность к цене и допустимые границы тарифов взяты из официального routes.csv; прогноз спроса — из my_forecast.csv. Расчёт выполняется на сервере.';
    try {user=await api('/api/auth/me')} catch(e) { if(e.status!==401) throw e; }
    refreshAccount();
    if (user) await calculate(); else openAuth('register');
  } catch(error) {notice('Не удалось загрузить данные приложения: '+error.message);}
}
function setRouteBasePrice(){
  if(!options)return;
  const route=options.routes.find(r=>r.code===$('route').value);
  if(route){
    const input=$('price');
    input.value=route.base_price;
    input.min=route.price_min;
    input.max=route.price_max;
    $('priceRange').textContent=`Диапазон: ${rub(route.price_min)}–${rub(route.price_max)} ₽`;
  }
}
async function calculate(){
  if(!user){openAuth('login');return;}
  const price=Number($('price').value);
  if(!Number.isFinite(price)||price<=0){notice('Введите положительную цену');return;}
  hideNotice();
  $('calculateBtn').disabled=true;
  try{
    const data=await api('/api/calculate',{method:'POST',body:JSON.stringify({
      route:$('route').value,date:$('date').value,price,quantile:Number($('quantile').value)})});
    lastResponse=data; renderResults(data);
  } catch(error){
    if(error.status===401) {user=null;refreshAccount();openAuth('login');}
    notice(error.message);
  } finally{$('calculateBtn').disabled=false;}
}
function renderResults(result){
  $('sales').textContent=num(result.median_sales); $('free').textContent=num(result.median_free);
  $('recommended').textContent=rub(result.recommended_price);
  $('loadPct').textContent=result.occupancy_pct.toLocaleString('ru-RU')+'%';
  $('progressFill').style.width=Math.max(0,Math.min(100,result.occupancy_pct))+'%';
  $('seatsText').textContent=`Вместимость: ${num(result.seats)} мест`;
  $('routeText').textContent=`Москва → ${result.destination}`;
  $('resultDate').textContent=result.date.split('-').reverse().join('.');
  const body=$('scenarioRows'); body.replaceChildren();
  for(const row of result.quantiles){
    const tr=document.createElement('tr'); if(row.quantile===0.5) tr.classList.add('median');
    const cells=[`${Math.round(row.quantile*100)}%`,
      row.quantile===0.5?'Медиана':row.quantile<0.5?'Низкий спрос':'Высокий спрос',
      num(row.demand), num(row.sales), num(row.unsold_seats), `${rub(row.recommended_price)} ₽`];
    for(const val of cells){const td=document.createElement('td');td.textContent=val;tr.append(td)}
    body.append(tr);
  }
  drawChart(result);
}
function drawChart(result){
  const svg=$('chart'), NS='http://www.w3.org/2000/svg'; svg.replaceChildren();
  const width=680,height=250; const margins={left:45,right:30,top:19,bottom:36};
  const w=width-margins.left-margins.right,h=height-margins.top-margins.bottom;
  const demandVals=result.quantiles.map(v=>v.demand);
  const maxD=Math.max(60,result.seats*1.12,demandVals[8]*1.12);
  const x=value=>margins.left+value/maxD*w;
  const y=q=>margins.top+h-q*h;
  function add(type,attrs={},text){const el=document.createElementNS(NS,type);
    for (const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));
    if(text!==undefined)el.textContent=text; svg.append(el);return el;}
  for(let t=0;t<=4;t++){
    const prob=t/4, py=y(prob);
    add('line',{x1:margins.left,y1:py,x2:width-margins.right,y2:py,stroke:'#2c3b4e','stroke-width':1});
    add('text',{x:35,y:py+4,fill:'#8ca0b7','text-anchor':'end','font-size':11},Math.round(prob*100)+'%');
  }
  for(let t=0;t<=5;t++){
    const value=maxD*t/5,px=x(value);
    add('text',{x:px,y:height-9,fill:'#8ca0b7','text-anchor':'middle','font-size':11},num(value));
  }
  const capX=x(result.seats);
  add('line',{x1:capX,y1:margins.top,x2:capX,y2:y(0),stroke:'#7e94af','stroke-width':1.7,'stroke-dasharray':'6 5'});
  const labelX=Math.min(capX+5,width-130);
  add('text',{x:labelX,y:margins.top+10,fill:'#a9bdd1','font-size':10},'лимит '+num(result.seats));
  const d=result.quantiles.map(row=>`${x(row.demand)},${y(row.quantile)}`).join(' ');
  add('polyline',{points:d,fill:'none',stroke:'#ffad77','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'});
  for(const row of result.quantiles){
    add('circle',{cx:x(row.demand),cy:y(row.quantile),r:row.quantile===0.5?5.2:3.2,
      fill:row.quantile===0.5?'#ffe1bc':'#ffae75',stroke:'#142033','stroke-width':1.5});
  }
  const median=result.quantiles[4]; const mx=x(median.demand),my=y(.5);
  add('line',{x1:mx,y1:my,x2:mx,y2:y(0),stroke:'#ffb684','stroke-dasharray':'3 5',opacity:.55});
  add('text',{x:Math.min(mx+9,width-120),y:my-11,fill:'#ffe0ba','font-size':12,'font-weight':700},'медиана '+num(median.demand));
}
$('authBtn').addEventListener('click',()=>openAuth());
$('closeAuth').addEventListener('click',closeAuth);
$('authModal').addEventListener('click',event=>{if(event.target===$('authModal'))closeAuth()});
$('switchAuth').addEventListener('click',()=>openAuth(authMode==='login'?'register':'login'));
$('route').addEventListener('change',()=>{setRouteBasePrice();if(user)calculate()});
$('date').addEventListener('change',()=>{if(user)calculate()});
$('quantile').addEventListener('change',()=>{if(user)calculate()});
$('forecastForm').addEventListener('submit',event=>{event.preventDefault();calculate()});
$('authForm').addEventListener('submit',async event=>{
  event.preventDefault();$('authError').classList.add('hidden'); $('authSubmit').disabled=true;
  try{
    const endpoint=authMode==='login'?'/api/auth/login':'/api/auth/register';
    user=await api(endpoint,{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});
    $('password').value='';closeAuth();refreshAccount();await calculate();
  } catch(error){$('authError').textContent=error.message;$('authError').classList.remove('hidden');}
  finally{$('authSubmit').disabled=false;}
});
$('logoutBtn').addEventListener('click',async()=>{
  try{await api('/api/auth/logout',{method:'POST'});}catch{}user=null;refreshAccount();
  $('sales').textContent='—';$('free').textContent='—';$('recommended').textContent='—';
  $('scenarioRows').replaceChildren();$('chart').replaceChildren();openAuth('login');
});
initialize();

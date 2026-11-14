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
  div.style.borderColor = bad ? '#efced4' : '#b5e7d8';
  div.style.background = bad ? '#fff5f5' : '#ecfbf6';
  div.style.color = bad ? '#a4384d' : '#17745a';
}
function hideNotice(){ $('notification').classList.add('hidden'); }
function refreshAccount(){
  $('accountName').textContent = user ? user.username : 'Гостевой режим';
  $('authBtn').classList.toggle('hidden',!!user);
  $('logoutBtn').classList.toggle('hidden',!user);
}
function openAuth(mode='login'){
  authMode=mode; $('authTitle').textContent= mode==='login'?'Войти в систему':'Создать учётную запись';
  $('authSubmit').querySelector('span').textContent= mode==='login'?'Войти':'Зарегистрироваться';
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
      const o=document.createElement('option'); o.value=route.code; o.textContent=`${route.destination} · ${route.code.split('-')[1]}`; select.append(o);
    }
    select.value='MOW-AER';
    $('date').min=options.date_min; $('date').max=options.date_max;
    setRouteBasePrice();
    $('dataDisclaimer').textContent='Базовые цены, чувствительность к цене и допустимые границы тарифов взяты из официального routes.csv; прогноз спроса — из my_forecast.csv. Расчёт выполняется на сервере.';
    try {user=await api('/api/auth/me')} catch(e) { if(e.status!==401) throw e; }
    refreshAccount();
    await calculate();
    await loadNetworkCase('peak');
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
  const price=Number($('price').value);
  if(!Number.isFinite(price)||price<=0){notice('Введите положительную цену');return;}
  hideNotice();
  $('calculateBtn').disabled=true;
  try{
    const data=await api('/api/calculate',{method:'POST',body:JSON.stringify({
      route:$('route').value,date:$('date').value,price,quantile:Number($('quantile').value)})});
    lastResponse=data; renderResults(data);
  } catch(error){
    notice(error.message);
  } finally{$('calculateBtn').disabled=false;}
}
function renderResults(result){
  $('sales').textContent=num(result.median_sales); $('free').textContent=num(result.median_free);
  $('recommended').textContent=rub(result.recommended_price);
  $('loadPct').textContent=result.occupancy_pct.toLocaleString('ru-RU')+'%';
  $('progressFill').parentElement.setAttribute('aria-valuenow',String(result.occupancy_pct));
  $('progressFill').style.width=Math.max(0,Math.min(100,result.occupancy_pct))+'%';
  $('seatsText').textContent=`Вместимость: ${num(result.seats)} мест`;
  $('routeText').textContent=`Москва → ${result.destination}`;
  $('resultDate').textContent=result.date.split('-').reverse().join('.');
  $('destinationCode').textContent=result.route.split('-')[1];
  $('destinationName').textContent=result.destination;
  document.querySelectorAll('.route-pick').forEach(button => {
    const active = button.dataset.route === result.route;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  const body=$('scenarioRows'); body.replaceChildren();
  for(const row of result.quantiles){
    const tr=document.createElement('tr'); if(row.quantile===0.5) tr.classList.add('median');
    const qCell=document.createElement('td'),badge=document.createElement('span');
    badge.className='quantile-pill'; badge.textContent=`${Math.round(row.quantile*100)}%`;
    qCell.append(badge); tr.append(qCell);
    const label=document.createElement('td'),group=document.createElement('span');
    group.className='scenario-label';
    const labelText=document.createElement('span');
    labelText.textContent=row.quantile===0.5?'Медиана':row.quantile<0.5?'Низкий спрос':'Высокий спрос';
    const bar=document.createElement('i'); bar.className='mini-track';
    bar.style.setProperty('--fill',`${Math.round(row.quantile*100)}%`);
    group.append(bar,labelText);label.append(group);tr.append(label);
    for(const text of [num(row.demand),num(row.sales),num(row.unsold_seats),`${rub(row.recommended_price)} ₽`]){
      const td=document.createElement('td'); td.textContent=text;tr.append(td);
    }
    body.append(tr);
  }
  drawChart(result);
  renderEconomics(result.economics);
}
function drawChart(result){
  const svg=$('chart'), NS='http://www.w3.org/2000/svg';svg.replaceChildren();
  const W=680,H=270,m={left:48,right:28,top:22,bottom:38};
  const w=W-m.left-m.right,h=H-m.top-m.bottom;
  const demands=result.quantiles.map(p=>p.demand);
  const maxD=Math.max(60,result.seats*1.12,demands[8]*1.12);
  const x=v=>m.left+v/maxD*w, y=v=>m.top+(1-v)*h;
  function el(tag,attrs={},content){
    const item=document.createElementNS(NS,tag);
    for(const [k,v] of Object.entries(attrs))item.setAttribute(k,String(v));
    if(content!==undefined)item.textContent=content;
    svg.append(item);return item;
  }
  const defs=el('defs'),gradient=document.createElementNS(NS,'linearGradient');
  gradient.id='demandFill';gradient.setAttribute('x1','0');gradient.setAttribute('y1','0');gradient.setAttribute('x2','0');gradient.setAttribute('y2','1');
  for(const [offset,opacity] of [['0%','.20'],['100%','0']]){
    const stop=document.createElementNS(NS,'stop');stop.setAttribute('offset',offset);
    stop.setAttribute('stop-color','#4e7ee8');stop.setAttribute('stop-opacity',opacity);gradient.append(stop);
  }
  defs.append(gradient);
  for(let t=0;t<=4;t++){
    const val=t/4,py=y(val);
    el('line',{x1:m.left,y1:py,x2:W-m.right,y2:py,stroke:'#eaf0f7','stroke-width':1});
    el('text',{x:m.left-12,y:py+4,fill:'#93a4ba','text-anchor':'end','font-size':10,'font-family':'Inter,system-ui,sans-serif'},`${Math.round(val*100)}%`);
  }
  for(let t=0;t<=5;t++){
    const value=maxD*t/5,px=x(value);
    el('text',{x:px,y:H-12,fill:'#93a4ba','text-anchor':'middle','font-size':10,'font-family':'Inter,system-ui,sans-serif'},num(value));
  }
  const capacity=x(result.seats);
  el('line',{x1:capacity,x2:capacity,y1:m.top,y2:y(0),stroke:'#a4b1c4','stroke-width':1.6,'stroke-dasharray':'5 5'});
  el('text',{x:Math.max(m.left+8,Math.min(capacity+7,W-120)),y:m.top+11,fill:'#7b90ae','font-size':10,'font-family':'Inter,system-ui,sans-serif'},`лимит ${num(result.seats)}`);
  const vertices=result.quantiles.map(pt=>[x(pt.demand),y(pt.quantile)]);
  const first=vertices[0],last=vertices[vertices.length-1];
  const path=vertices.map((v,i)=>`${i?'L':'M'} ${v[0].toFixed(2)} ${v[1].toFixed(2)}`).join(' ');
  el('path',{d:`${path} L ${last[0]} ${y(0)} L ${first[0]} ${y(0)} Z`,fill:'url(#demandFill)'});
  el('path',{d:path,fill:'none',stroke:'#356bdd','stroke-width':3.1,'stroke-linejoin':'round','stroke-linecap':'round'});
  for(const pt of result.quantiles){
    el('circle',{cx:x(pt.demand),cy:y(pt.quantile),r:pt.quantile===.5?5.9:3.8,fill:pt.quantile===.5?'#2355c7':'#fff',stroke:'#356bdd','stroke-width':pt.quantile===.5?2:1.8});
  }
  const median=result.quantiles[4];
  const mx=x(median.demand),my=y(.5);
  el('line',{x1:mx,x2:mx,y1:my,y2:y(0),stroke:'#6797eb','stroke-width':1.5,'stroke-dasharray':'3 5'});
  const lblX=Math.min(mx+12,W-135);
  const lbl=el('g');
  const rect=document.createElementNS(NS,'rect');
  rect.setAttribute('x',lblX-5);rect.setAttribute('y',my-29);rect.setAttribute('width','120');rect.setAttribute('height','24');rect.setAttribute('rx','6');rect.setAttribute('fill','#e7efff');lbl.append(rect);
  const txt=document.createElementNS(NS,'text');txt.setAttribute('x',lblX+2);txt.setAttribute('y',my-13);txt.setAttribute('fill','#255bc7');txt.setAttribute('font-size','10');txt.setAttribute('font-weight','700');txt.setAttribute('font-family','Inter,system-ui,sans-serif');txt.textContent=`медиана ${num(median.demand)}`;lbl.append(txt);
}
$('authBtn').addEventListener('click',()=>openAuth());
$('applyPriceBtn').addEventListener('click',()=>{
  if(!lastResponse)return;
  $('price').value=lastResponse.recommended_price;
  $('price').focus();
  calculate();
});
for(const nav of document.querySelectorAll('.menu-item')){
  nav.addEventListener('click',()=>{
    document.querySelectorAll('.menu-item').forEach(el=>el.classList.remove('active'));
    nav.classList.add('active');
  });
}
$('closeAuth').addEventListener('click',closeAuth);
$('authModal').addEventListener('click',event=>{if(event.target===$('authModal'))closeAuth()});
$('switchAuth').addEventListener('click',()=>openAuth(authMode==='login'?'register':'login'));
$('route').addEventListener('change',()=>{setRouteBasePrice();calculate()});
document.querySelectorAll('.route-pick').forEach(button => {
  button.addEventListener('click', () => {
    $('route').value=button.dataset.route; setRouteBasePrice(); calculate();
    document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'});
  });
});
$('date').addEventListener('change',calculate);
$('quantile').addEventListener('change',calculate);
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
  // Гостевой режим доступен и после выхода — прогноз остаётся на экране.
  await calculate();
});
initialize();


// Economics: all financial and optimization figures are computed by the server.
const fmtMoney = v => `${rub(v)} ₽`;
const signedMoney = v => `${v > 0.005 ? '+' : v < -0.005 ? '−' : ''}${fmtMoney(Math.abs(v))}`;
function renderEconomics(e){
  if(!e)return;
  $('upliftValue').textContent=signedMoney(e.uplift_vs_baseline);
  $('upliftText').textContent=`${e.uplift_pct_vs_baseline > 0 ? '+' : ''}${(e.uplift_pct_vs_baseline ?? 0).toLocaleString('ru-RU')}% к маржинальному вкладу базового тарифа при выборе цены максимальной ожидаемой прибыли`;
  $('baseFare').textContent=fmtMoney(e.baseline.price);
  $('optimalFare').textContent=fmtMoney(e.expected_optimal.price);
  $('financialRevenue').textContent=fmtMoney(e.current.expected_revenue);
  $('financialMargin').textContent=fmtMoney(e.current.expected_contribution);
  $('financialOptimal').textContent=fmtMoney(e.expected_optimal.expected_contribution);
  $('financialDifference').textContent=signedMoney(e.uplift_vs_current);
  $('financialUnitCost').textContent=fmtMoney(e.variable_cost_per_passenger);
  $('riskExpectedPrice').textContent=fmtMoney(e.expected_optimal.price);
  $('riskExpectedLow').textContent=fmtMoney(e.expected_optimal.low_contribution);
  $('riskSafePrice').textContent=fmtMoney(e.conservative_optimal.price);
  $('riskSafeLow').textContent=fmtMoney(e.conservative_optimal.low_contribution);
  $('riskTradeoff').textContent=`Осторожная цена повышает результат в сценарии низкого спроса на ${fmtMoney(Math.max(0,e.conservative_downside_gain))} по сравнению с максимумом среднего результата. Компромисс: ожидаемый вклад может снизиться на ${fmtMoney(Math.max(0,e.conservative_expected_tradeoff))}.`;
  $('profitChartHint').textContent=`Максимум ожидания при ${fmtMoney(e.expected_optimal.price)}; ваша цена — ${fmtMoney(e.current.price)}. Линии представляют модельный маржинальный вклад до фиксированных расходов.`;
  drawProfitChart(e);
}
$('applyExpectedPrice').addEventListener('click',()=>{
  if(!lastResponse)return;
  $('price').value=lastResponse.economics.expected_optimal.price;
  calculate();
  document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'});
});
$('applySafePrice').addEventListener('click',()=>{
  if(!lastResponse)return;
  $('price').value=lastResponse.economics.conservative_optimal.price;
  calculate();
  document.getElementById('results').scrollIntoView({behavior:'smooth',block:'start'});
});
function drawProfitChart(e){
  const svg=$('profitChart'),NS='http://www.w3.org/2000/svg';svg.replaceChildren();
  const W=680,H=275,m={left:74,right:24,top:26,bottom:45};
  const w=W-m.left-m.right,h=H-m.top-m.bottom;
  const curve=e.curve;
  const xs=curve.map(d=>d.price);
  const values=curve.flatMap(d=>[d.expected,d.low]);
  const minPrice=Math.min(...xs),maxPrice=Math.max(...xs);
  const minVal=Math.min(0,...values),maxVal=Math.max(0,...values);
  const spread=Math.max(1,maxVal-minVal);
  const bottom=minVal-spread*.08,top=maxVal+spread*.14;
  const X=v=>m.left+(v-minPrice)/Math.max(1,maxPrice-minPrice)*w;
  const Y=v=>m.top+(top-v)/Math.max(1,top-bottom)*h;
  const el=(tag,attrs={},val)=>{
    const node=document.createElementNS(NS,tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
    if(val!==undefined)node.textContent=val;svg.append(node);return node;
  };
  function compact(n){return Math.abs(n)>=1e6?(n/1e6).toFixed(1)+' млн':Math.round(n/1000)+' тыс';}
  for(let i=0;i<=4;i++){
    const value=bottom+i*(top-bottom)/4,y=Y(value);
    el('line',{x1:m.left,x2:W-m.right,y1:y,y2:y,stroke:'#e7ebf0','stroke-width':1});
    el('text',{x:m.left-12,y:y+4,'text-anchor':'end',fill:'#94a0ad','font-size':10},compact(value));
  }
  for(let i=0;i<=4;i++){
    const value=minPrice+(maxPrice-minPrice)*i/4;
    el('text',{x:X(value),y:H-16,'text-anchor':'middle',fill:'#91a0af','font-size':10},rub(value));
  }
  const path=key=>curve.map((p,i)=>`${i?'L':'M'}${X(p.price).toFixed(1)} ${Y(p[key]).toFixed(1)}`).join(' ');
  el('path',{d:path('low'),fill:'none',stroke:'#ed994c','stroke-width':2.2,'stroke-dasharray':'6 5','stroke-linecap':'round'});
  el('path',{d:path('expected'),fill:'none',stroke:'#1874ef','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'});
  const current=X(e.current.price);
  el('line',{x1:current,x2:current,y1:m.top,y2:H-m.bottom,stroke:'#68798d','stroke-width':1.6,'stroke-dasharray':'3 5'});
  for(const [price,value,color,label] of [[e.current.price,e.current.expected_contribution,'#6c7889','вы'],[e.expected_optimal.price,e.expected_optimal.expected_contribution,'#1476f6','оптимум']]){
    const cx=X(price),cy=Y(value);
    el('circle',{cx,cy,r:5.8,fill:color,stroke:'#fff','stroke-width':2});
    const px=Math.max(m.left+10,Math.min(W-m.right-45,cx+9));
    el('text',{x:px,y:Math.max(m.top+11,cy-12),fill:color,'font-size':11,'font-weight':'700'},label);
  }
  el('text',{x:W-m.right,y:H-1,fill:'#9ba5b0','font-size':10,'text-anchor':'end'},'Цена билета, ₽');
}

let selectedNetworkCase='peak';
async function loadNetworkCase(scenario){
  selectedNetworkCase=scenario;
  document.querySelectorAll('.network-tab').forEach(btn=>{
    const active=btn.dataset.case===scenario;
    btn.classList.toggle('selected',active);
    btn.setAttribute('aria-pressed',String(active));
  });
  try{
    const data=await api(`/api/network-case?scenario=${encodeURIComponent(scenario)}`);
    renderNetworkCase(data);
  }catch(err){notice('Не удалось загрузить математическую модель: '+err.message);}
}
function renderNetworkCase(d){
  $('networkNormal').textContent=fmtMoney(d.normal_profit);
  $('networkPeak').textContent=fmtMoney(d.peak_profit);
  $('networkAlternate').textContent=fmtMoney(d.alternative_route_profit);
  $('networkSeat').textContent=fmtMoney(d.shadow_price_one_seat_discrete);
  const descriptions={
    normal:{title:'Прибыль обычного дня',value:d.operating_profit,
      message:'При оптимальных ценах все участки имеют свободные кресла. Вместимость не ограничивает продажи.'},
    peak:{title:'Максимальная прибыль в пиковый день',value:d.operating_profit,
      message:`Замена маршрута на четыре перелёта между Петербургом и Москвой уменьшила бы прибыль на ${fmtMoney(-d.alternative_route_delta)}.`},
    snow:{title:'Ожидаемая прибыль с учётом снегопада',value:d.snow_expected_new,
      message:`Повышение тарифов с учётом вероятности полной отмены приносит ${signedMoney(d.snow_uplift)} к ожидаемой прибыли против обычных цен.`},
  };
  const desc=descriptions[d.scenario];
  $('networkKicker').textContent=desc.title;
  $('networkProfit').textContent=fmtMoney(desc.value);
  $('networkSummary').textContent=desc.message;
  $('networkWeatherNote').textContent=d.scenario==='snow'
    ?`Риск полной отмены: 20%; компенсация 4 000 ₽ на билет. Ожидаемая компенсация: ${fmtMoney(d.snow_expected_compensation)}. Цена оптимизируется заранее.`
    :d.scenario==='peak'
      ?`Участок Петербург → Москва загружен полностью. Дополнительное 151-е кресло даёт ${fmtMoney(d.shadow_price_one_seat_discrete)} при целочисленных билетах.`
      :'Самолёт последовательно летит Петербург → Москва → Сочи → Москва → Петербург.';
  const legContainer=$('networkLegs');legContainer.replaceChildren();
  d.loads.forEach((count,i)=>{
    const item=document.createElement('div');item.className='leg-row'+(count===d.aircraft_capacity_per_leg?' capacity':'');
    const head=document.createElement('div');head.className='leg-head';
    const route=document.createElement('span');route.textContent=d.leg_names[i];
    const num=document.createElement('b');num.textContent=`${count} / ${d.aircraft_capacity_per_leg}`;
    head.append(route,num);
    const bar=document.createElement('div');bar.className='leg-bar';
    const fill=document.createElement('div');fill.style.width=`${100*count/d.aircraft_capacity_per_leg}%`;
    bar.append(fill);item.append(head,bar);legContainer.append(item);
  });
  const table=$('networkRows');table.replaceChildren();
  d.markets.forEach(m=>{
    const tr=document.createElement('tr');
    for(const v of [m.name,fmtMoney(m.price),String(m.tickets)]){
      const td=document.createElement('td');td.textContent=v;tr.append(td);
    }table.append(tr);
  });
}
document.querySelectorAll('.network-tab').forEach(btn=>btn.addEventListener('click',()=>loadNetworkCase(btn.dataset.case)));
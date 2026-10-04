'use strict';
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const demo = new URLSearchParams(location.search).get('demo') === '1' || !location.pathname.startsWith('/dashboard');
let accessToken = '', modalAction, state = {offers: [], campaigns: [], contents: [], analytics: []};
const currency = value => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD',maximumFractionDigits:2}).format(Number(value || 0));
const number = value => new Intl.NumberFormat('en-US').format(Number(value || 0));
const badge = status => `<span class="badge ${escapeHtml(status)}">${escapeHtml(status === 'published' ? 'Tracking ready' : status)}</span>`;
function feedback(message, error = false) { $('feedback').textContent = message; $('feedback').className = error ? 'error' : ''; }
function clearFeedback() { $('feedback').textContent = ''; }
function seedDemo() {
  state = {
    offers: [{id:1,name:'Northstar partnership',brand:'Northstar · Sample',geo:'DE',affiliate_url:'https://example.com/?partner=northstar',cpa:65,revenue_share:25,active:true},{id:2,name:'Atlas partner program',brand:'Atlas · Sample',geo:'GB',affiliate_url:'https://example.com/?partner=atlas',cpa:50,revenue_share:30,active:true},{id:3,name:'Orbit affiliate offer',brand:'Orbit · Sample',geo:'CA',affiliate_url:'https://example.com/?partner=orbit',cpa:55,revenue_share:20,active:true}],
    campaigns:[{id:1,name:'Northstar / Community',offer_id:1,channel:'telegram',status:'active'},{id:2,name:'Atlas / Editorial',offer_id:2,channel:'blog',status:'active'},{id:3,name:'Orbit / Discovery',offer_id:3,channel:'social',status:'draft'}],
    contents:[{id:1,campaign_id:1,platform:'telegram',title:'Community introduction',body:'Sample content for the Northstar partnership. Explore the program details and check the terms for your region.\n\n18+ · Play responsibly. This is a fictional portfolio example.',status:'draft'},{id:2,campaign_id:2,platform:'blog',title:'Partner overview',body:'An editorial introduction to the Atlas partner program, prepared for human review.\n\nThis example does not advertise a real operator or offer.',status:'approved'}],
    analytics:[{campaign_id:1,campaign_name:'Northstar / Community',clicks:2840,registrations:192,ftd:58,revenue:3770},{campaign_id:2,campaign_name:'Atlas / Editorial',clicks:1680,registrations:134,ftd:39,revenue:1950},{campaign_id:3,campaign_name:'Orbit / Discovery',clicks:720,registrations:43,ftd:0,revenue:0}]
  };
  recalculate();
}
function recalculate() {
  state.analytics = state.campaigns.map(c => {
    const m = state.analytics.find(a => a.campaign_id === c.id) || {clicks:0,registrations:0,ftd:0,revenue:0};
    const conversion_rate = m.clicks ? m.registrations/m.clicks*100 : 0;
    const epc = m.clicks ? m.revenue/m.clicks : 0;
    const action = !m.clicks ? 'CREATE_CONTENT' : !m.registrations ? 'CHANGE_CONTENT' : !m.ftd ? 'OPTIMIZE_OFFER' : conversion_rate >= 30 && epc >= 10 ? 'SCALE' : 'TEST';
    return {...m,campaign_id:c.id,campaign_name:c.name,conversion_rate,epc,recommended_action:action};
  });
}
async function api(path, method='GET', body) {
  const response = await fetch(path, {method,headers:{'Content-Type':'application/json',...(accessToken ? {Authorization:`Bearer ${accessToken}`} : {})},...(body === undefined ? {} : {body:JSON.stringify(body)})});
  let data;
  try { data = await response.json(); } catch { throw new Error('The workspace returned an invalid response.'); }
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(e=>`${e.loc.at(-1)}: ${e.msg}`).join('; ') : data.detail || `Request failed (${response.status})`);
  return data;
}
async function load() {
  if (demo) { recalculate(); render(); return; }
  try {
    const [offers,campaigns,contents,analytics,status] = await Promise.all([api('/offers/'),api('/campaigns/'),api('/content/'),api('/agent/analytics'),api('/workspace/status')]);
    state = {offers:offers.offers,campaigns:campaigns.campaigns,contents:contents.contents,analytics:analytics.campaigns};
    $('mode').textContent = 'Local workspace';
    $('notice').textContent = status.ai_configured ? 'Connected to your workspace. AI drafts require human review. Prepare link creates a tracking link; it does not send a Telegram post.' : 'Workspace connected. Add an OpenAI API key to enable AI generation. Manual drafts, review and tracking work without a key.';
    render();
  } catch (error) { $('mode').textContent = 'Connection needed'; feedback(error.message, true); }
}
const reasons = {CREATE_CONTENT:'No traffic yet. Prepare a new content angle and review it before sharing.',CHANGE_CONTENT:'Clicks are not converting to registrations. Review the message and destination.',OPTIMIZE_OFFER:'Registrations have not converted to first deposits. Review offer fit and the conversion path.',SCALE:'Strong conversion and revenue per click. Assess capacity before increasing distribution.',TEST:'Keep testing content angles and compare conversion quality.'};
function render() {
  const totals = state.analytics.reduce((t,m)=>({clicks:t.clicks+m.clicks,registrations:t.registrations+m.registrations,ftd:t.ftd+m.ftd,revenue:t.revenue+m.revenue}),{clicks:0,registrations:0,ftd:0,revenue:0});
  $('metrics').innerHTML = [['Total revenue',currency(totals.revenue),`${state.campaigns.length} campaigns in workspace`],['Tracked clicks',number(totals.clicks),'Traffic across all tracked content'],['Registrations',number(totals.registrations),`${(totals.clicks ? totals.registrations/totals.clicks*100 : 0).toFixed(2)}% registration conversion`],['First deposits',number(totals.ftd),`${currency(totals.clicks ? totals.revenue/totals.clicks : 0)} earnings per click`]].map(([label,value,sub])=>`<div class="metric"><span class="label">${label}</span><strong>${value}</strong><small>${sub}</small></div>`).join('');
  const max = Math.max(1,...state.analytics.map(a=>a.revenue));
  $('chart').innerHTML = state.analytics.length ? state.analytics.map(a=>`<div class="bar-row"><span>${escapeHtml(a.campaign_name)}</span><div class="bar-track"><div class="bar" style="width:${Math.max(0,Math.min(100,a.revenue/max*100))}%"></div></div><span>${currency(a.revenue)}</span></div>`).join('') : '<div class="empty">Add a campaign to see performance.</div>';
  $('insights').innerHTML = state.analytics.length ? state.analytics.slice(0,3).map(a=>`<div class="insight"><strong>${escapeHtml(a.campaign_name)}</strong><p>${escapeHtml(reasons[a.recommended_action] || a.reason)}</p></div>`).join('') : '<p class="muted">Your agent insights will appear here.</p>';
  $('performance').innerHTML = `<table><thead><tr><th>Campaign</th><th>Clicks</th><th>Registrations</th><th>FTD</th><th>Conversion</th><th>EPC</th><th>Revenue</th></tr></thead><tbody>${state.analytics.map(a=>`<tr><td>${escapeHtml(a.campaign_name)}</td><td>${number(a.clicks)}</td><td>${number(a.registrations)}</td><td>${number(a.ftd)}</td><td>${Number(a.conversion_rate).toFixed(2)}%</td><td>${currency(a.epc)}</td><td>${currency(a.revenue)}</td></tr>`).join('')}</tbody></table>`;
  $('campaign-list').innerHTML = state.campaigns.length ? state.campaigns.map(c=>`<article class="card">${badge(c.status)}<h3>${escapeHtml(c.name)}</h3><p>${escapeHtml(state.offers.find(o=>o.id===c.offer_id)?.name || 'No offer')} · ${escapeHtml(c.channel)}</p><button class="secondary" data-draft="${c.id}">Create draft ↗</button></article>`).join('') : '<div class="empty">Start by adding an offer, then create your first campaign.</div>';
  $('offer-list').innerHTML = state.offers.length ? state.offers.map(o=>`<article class="card"><span class="eyebrow">${escapeHtml(o.geo)} / ${escapeHtml(o.brand)}</span><h3>${escapeHtml(o.name)}</h3><dl><div><dt>CPA · USD</dt><dd>${currency(o.cpa)}</dd></div><div><dt>Revenue share</dt><dd>${number(o.revenue_share)}%</dd></div></dl><p class="offer-url">${escapeHtml(o.affiliate_url)}</p></article>`).join('') : '<div class="empty">Add your first partner offer.</div>';
  const filter = $('content-filter').value;
  const contents = state.contents.filter(c=>filter==='all'||c.status===filter).slice().reverse();
  $('content-list').innerHTML = contents.length ? contents.map(c=>`<article class="card content-card"><div class="section-head">${badge(c.status)}<span class="muted">${escapeHtml(c.platform)}</span></div><h3>${escapeHtml(c.title)}</h3><span class="muted">${escapeHtml(state.campaigns.find(a=>a.id===c.campaign_id)?.name || '')}</span><div class="body">${escapeHtml(c.body)}</div><div class="actions">${c.status==='draft' ? `<button class="primary" data-approve="${c.id}">Approve draft</button><button class="danger" data-reject="${c.id}">Reject</button>` : c.status==='approved' ? `<button class="primary" data-publish="${c.id}">Prepare tracking link ↗</button>` : ''}${demo&&c.status==='published' ? `<button class="secondary" data-simulate="${c.id}">Simulate conversion</button>` : ''}</div>${c.tracking_url ? `<span class="tracking-url">${escapeHtml(c.tracking_url)}</span>` : ''}</article>`).join('') : '<div class="empty">No content in this view. Create a draft to get started.</div>';
}
function navigate(view) {
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==view);
  document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('selected',el.dataset.view===view));
  $('page-title').textContent = {overview:'Workspace overview',campaigns:'Campaign management',content:'Content studio',offers:'Partner offers'}[view];
  location.hash=view;
}
function field(name,label,type='text',value='',extra='') { return `<label class="field">${label}${type==='textarea' ? `<textarea name="${name}" required>${escapeHtml(value)}</textarea>` : `<input name="${name}" type="${type}" value="${escapeHtml(value)}" ${extra} required>`}</label>`; }
function campaignSelect(selected) { return `<label class="field">Campaign<select name="campaign_id">${state.campaigns.map(c=>`<option value="${c.id}" ${c.id===selected?'selected':''}>${escapeHtml(c.name)}</option>`).join('')}</select></label>`; }
function showModal(title,fields,submit,action) {
  clearFeedback(); $('modal-title').textContent=title; $('modal-fields').innerHTML=fields; $('submit-modal').textContent=submit; $('form-error').textContent=''; modalAction=action; $('modal').showModal();
}
function draftModal(generated=false,campaignId) {
  if (!state.campaigns.length) return feedback('Create a campaign first.',true);
  showModal(generated ? demo ? 'Generate sample draft' : 'Generate AI draft' : 'Create manual draft',campaignSelect(campaignId)+field('title','Title / topic')+`<label class="field">Platform<select name="platform"><option>telegram</option><option>blog</option><option>social</option></select></label>`+(generated ? `<label class="field">Language<select name="language"><option>Russian</option><option>English</option><option>Thai</option></select></label>`+(demo?'<p class="muted">Demo generation uses sample templates, without an AI API call.</p>':'') : field('body','Content','textarea')),generated?'Generate':'Save draft',async data=>{
    const campaign=state.campaigns.find(c=>c.id===Number(data.campaign_id));
    const body = {campaign_id:campaign.id,platform:data.platform,title:data.title,body:data.body};
    if (demo) {
      if(generated){const offer=state.offers.find(o=>o.id===campaign.offer_id);body.body=data.language==='Russian'?`Демонстрационный текст: ${offer.name}. Ознакомьтесь с условиями программы для вашего региона.\n\n18+ · Играйте ответственно. Это вымышленный пример для портфолио.`:data.language==='Thai'?`ข้อความตัวอย่าง: ${offer.name} โปรดตรวจสอบเงื่อนไขสำหรับพื้นที่ของคุณ\n\n18+ · เล่นอย่างรับผิดชอบ เป็นข้อมูลสมมติสำหรับเดโมผลงานเท่านั้น`:`Sample draft: ${offer.name}. Review the program terms for your region.\n\n18+ · Play responsibly. Fictional portfolio example.`;}
      state.contents.push({...body,id:Math.max(0,...state.contents.map(c=>c.id))+1,status:'draft'});
    } else { await api(generated?'/agent/generate-content':'/content/','POST',generated?{campaign_id:campaign.id,platform:data.platform,topic:data.title,language:data.language}:body); }
    await load(); navigate('content'); feedback(demo&&generated?'Sample template created. Ready for review.':'Draft saved. Ready for review.');
  });
}
$('new-offer').onclick = () => showModal('Add partner offer',field('name','Offer name')+field('brand','Brand')+field('geo','Country / GEO')+field('affiliate_url','Affiliate destination','url','https://example.com')+field('cpa','CPA · USD','number',0,'min="0" step="0.01"')+field('revenue_share','Revenue share · %','number',0,'min="0" max="100" step="0.01"'),'Save offer',async data=>{data.cpa=Number(data.cpa);data.revenue_share=Number(data.revenue_share);if(demo)state.offers.push({...data,id:Math.max(0,...state.offers.map(o=>o.id))+1,active:true});else await api('/offers/','POST',data);await load();feedback('Partner offer added.');});
$('new-campaign').onclick = () => {
  if(!state.offers.length)return feedback('Add a partner offer first.',true);
  showModal('New campaign',field('name','Campaign name')+`<label class="field">Partner offer<select name="offer_id">${state.offers.map(o=>`<option value="${o.id}">${escapeHtml(o.name)}</option>`).join('')}</select></label><label class="field">Channel<select name="channel"><option>telegram</option><option>blog</option><option>social</option></select></label><label class="field">Status<select name="status"><option>draft</option><option>active</option><option>paused</option></select></label>`,'Create campaign',async data=>{data.offer_id=Number(data.offer_id);if(demo)state.campaigns.push({...data,id:Math.max(0,...state.campaigns.map(c=>c.id))+1});else await api('/campaigns/','POST',data);await load();feedback('Campaign created.');});
};
$('new-content').onclick=()=>draftModal();$('generate-content').onclick=()=>draftModal(true);
$('content-filter').onchange=render;
$('settings').onclick=()=>showModal('Workspace access',field('token','Access token','password',accessToken)+'<p class="muted">Only needed for a protected backend. The token stays in memory and is cleared when you reload.</p>','Connect',async data=>{accessToken=data.token;await load();});
$('modal-form').onsubmit=async event=>{event.preventDefault();const button=$('submit-modal');button.disabled=true;try{await modalAction(Object.fromEntries(new FormData(event.target)));$('modal').close();}catch(error){$('form-error').textContent=error.message;}finally{button.disabled=false;}};
$('close-modal').onclick=$('cancel-modal').onclick=()=>$('modal').close();
$('refresh').onclick=async()=>{clearFeedback();await load();};
$('run-cycle').onclick=async()=>{
  const button=$('run-cycle');button.disabled=true;clearFeedback();
  try{if(demo){recalculate();navigate('content');draftModal(true,state.campaigns.find(c=>c.status==='active')?.id);}else{const result=await api('/agent/run-cycle','POST',{});await load();if(result.content)navigate('content');feedback(`Agent recommendation: ${result.action}. ${result.content?'New draft awaits review.':result.reason||''}`);}}catch(error){feedback(error.message,true);}finally{button.disabled=false;}
};
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.view){navigate(button.dataset.view);return;}if(button.dataset.draft){draftModal(false,Number(button.dataset.draft));return;}
  const action=['approve','reject','publish','simulate'].find(a=>button.dataset[a]);if(!action)return;
  const content=state.contents.find(c=>c.id===Number(button.dataset[action]));button.disabled=true;clearFeedback();
  try{
    if(demo){if(action==='simulate'){const m=state.analytics.find(a=>a.campaign_id===content.campaign_id);m.clicks+=1;m.registrations+=1;m.ftd+=1;m.revenue+=state.offers.find(o=>o.id===state.campaigns.find(c=>c.id===content.campaign_id).offer_id).cpa;}else{content.status={approve:'approved',reject:'rejected',publish:'published'}[action];if(action==='publish')content.tracking_url=`Demo tracking code: SAMPLE-${content.id} · no external delivery`;}}
    else{const result=await api(`/agent/${action}/${content.id}`,'POST',{});if(action==='publish')content.tracking_url=new URL(result.tracking.url,location.origin).href;}
    const links = Object.fromEntries(state.contents.filter(c=>c.tracking_url).map(c=>[c.id,c.tracking_url]));
    await load();state.contents.forEach(c=>{if(links[c.id])c.tracking_url=links[c.id];});render();
    feedback({approve:'Draft approved. Prepare its tracking link when ready.',reject:'Draft rejected.',publish:'Tracking link prepared. No external post was sent.',simulate:'Sample conversion recorded. Overview metrics updated.'}[action]);
  }catch(error){feedback(error.message,true);}finally{button.disabled=false;}
});
if(demo){seedDemo();$('mode').textContent='Interactive demo';$('settings').hidden=true;$('notice').innerHTML='Portfolio sandbox · Fictional data, sample drafts, and simulated conversions. No real campaigns or external posts.<button id="reset-demo">Reset demo</button>';$('reset-demo').onclick=()=>{seedDemo();render();feedback('Demo reset.');};}
navigate(['overview','campaigns','content','offers'].includes(location.hash.slice(1))?location.hash.slice(1):'overview');load();

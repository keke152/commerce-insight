const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => '¥' + Number(n || 0).toLocaleString('zh-CN', {minimumFractionDigits:2,maximumFractionDigits:2});
const categories = ['食品饮料','美妆个护','家居生活','数码配件','母婴用品','其他'];
const palette = ['#369767','#73b98c','#afd5b8','#e6bb88','#b8a8e5','#d8ded8'];
let currentPage = 1, currentOrders = [], profiles = [], preview = null, reviewId = null, orderRequest = 0, toastTimer;
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `请求失败 (${response.status})`);
  }
  return response.json();
}
function toast(message) {
  clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').classList.add('show');
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4500);
}
function filters() {
  return new URLSearchParams({q:$('#search').value.trim(),category:$('#category-filter').value,platform:$('#platform-filter').value,review_only:$('#review-only').checked});
}
async function loadOrders() {
  const requestId = ++orderRequest, params = filters();
  params.set('page', currentPage); params.set('page_size', 12);
  const data = await api('/api/orders/page?' + params);
  if (requestId !== orderRequest) return;
  if (!data.items.length && data.total && currentPage > 1) {currentPage=1; return loadOrders();}
  currentOrders = data.items;
  $('#table-count').textContent = `共 ${data.total} 条 · 本页 ${data.items.length} 条`;
  $('#page-number').textContent = `${currentPage} / ${Math.max(1,Math.ceil(data.total / 12))}`;
  $('#prev-page').disabled = currentPage === 1; $('#next-page').disabled = currentPage * 12 >= data.total;
  $('#export').href = '/api/export/orders.csv?' + filters();
  $('#orders-body').innerHTML = data.items.map(o => `<tr><td>${esc(o.order_id)}<small>${esc(o.ordered_at)}</small></td><td class="product-cell">${esc(o.product_name)}</td><td><span class="tag">${esc(o.category)}</span><small>${esc(o.classification_source)}${o.needs_review ? ' · 待复核' : ''}</small></td><td>${esc(o.customer_id)}</td><td>${esc(o.platform)}</td><td class="amount">${money(o.amount)}</td><td><button class="review-button" data-review="${o.id}">${o.reviewed?'已复核 · 查看':'复核'}</button></td></tr>`).join('') || '<tr><td colspan="7" class="loading">没有匹配订单</td></tr>';
}
function renderSummary(s, opps) {
  $('#orders-total').textContent=s.order_count.toLocaleString(); $('#revenue-30').textContent=money(s.revenue_30d);
  $('#customers-total').textContent=s.customers; $('#review-count').textContent=s.review_count;
  $('#due-count').textContent=opps.length; $('#category-total').textContent=s.order_count;
  $('#updated').textContent=new Date(s.refreshed_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
  for (const [id,key] of [['order-growth','order_growth'],['revenue-growth','revenue_growth'],['customer-growth','customer_growth']]) {
    const n=s[key]; $('#'+id).textContent=n===null?'暂无可比基数':`${n>0?'+':''}${n}%`; $('#'+id).className=n===null?'':'trend';
  }
  const entries=Object.entries(s.categories).sort((a,b)=>b[1]-a[1]); let acc=0; const total=s.order_count||1;
  $('#donut').style.background=entries.length ? 'conic-gradient('+entries.map(([_,n],i)=>{const start=acc/total*100;acc+=n;return `${palette[i%6]} ${start}% ${acc/total*100}%`;}).join(',')+')' : '#edf0ed';
  $('#legend').innerHTML=entries.map(([k,n],i)=>`<div class="legend-item"><i style="background:${palette[i%6]}"></i>${esc(k)}<b>${Math.round(n/total*100)}%</b></div>`).join('');
  $('#category-insight').textContent=entries.length ? `当前订单最多的品类是${entries[0][0]}，共${entries[0][1]}笔。分类复核后，分布与复购清单同步更新。` : '导入订单后查看品类分布。';
  const selected=$('#platform-filter').value;
  $('#platform-filter').innerHTML='<option value="">全部平台</option>'+s.platforms.map(p=>`<option>${esc(p)}</option>`).join('');
  $('#platform-filter').value=s.platforms.includes(selected)?selected:'';
  $('#top-opportunities').innerHTML=opps.slice(0,3).map(o=>`<div class="opportunity-row"><div class="customer-avatar">${esc(o.customer_id.slice(-1))}</div><div><div class="opp-name">${esc(o.customer_id)}</div><div class="opp-desc">${esc(o.category)} · ${o.days_since_last}天未购</div></div><div class="bar-wrap"><i style="width:${o.priority_score}%"></i></div><div class="opp-percent">${o.priority_score}分</div></div>`).join('') || '<p class="loading">暂无满足历史周期条件的机会</p>';
  $('#opportunities-body').innerHTML=opps.slice(0,60).map(o=>`<tr><td>${esc(o.customer_id)}<small>${esc(o.category)}</small></td><td>${o.purchase_days}天</td><td>${o.avg_cycle_days}天</td><td>${esc(o.predicted_date)}</td><td><span class="tag">${o.priority_score}分</span></td><td><b>${esc(o.status)}</b><small>${esc(o.reason)}</small></td></tr>`).join('') || '<tr><td colspan="6" class="loading">暂无复购机会</td></tr>';
}
function renderCustomers() {
  const segments=['高价值活跃','成长客户','新客户','待唤回'];
  $('#segment-cards').innerHTML=segments.map(s=>`<div><small>${esc(s)}</small><b>${profiles.filter(p=>p.segment===s).length}<em>位</em></b></div>`).join('');
  const rows=profiles.filter(p=>!$('#segment-filter').value||p.segment===$('#segment-filter').value);
  $('#customer-body').innerHTML=rows.slice(0,100).map(p=>`<tr><td>${esc(p.customer_id)}</td><td><span class="tag">${esc(p.segment)}</span></td><td>${p.recency_days}天</td><td>${p.frequency}天</td><td>${money(p.monetary)}</td><td>${esc(p.platforms.join(' / '))}</td></tr>`).join('') || '<tr><td colspan="6" class="loading">暂无客户</td></tr>';
}
async function load() {
  $('#refresh').disabled=true;
  try {
    const [s,opps,customers,batches,card]=await Promise.all(['/api/summary','/api/recommendations','/api/customers','/api/import/batches','/api/model'].map(p=>api(p)));
    profiles=customers; renderSummary(s,opps); renderCustomers(); await loadOrders();
    $('#model-card').innerHTML=`<b>${esc(card.algorithm)}</b><div class="model-stats"><span>训练样本<strong>${card.training_count}</strong></span><span>独立测试<strong>${card.test_count}</strong></span><span>样例 Macro-F1<strong>${card.macro_f1.toFixed(3)}</strong></span></div><small>${esc(card.dataset_kind)}</small>`;
    $('#batch-list').innerHTML=batches.map(b=>`<div><b>#${b.id} · ${esc(b.source)}</b><span>导入${b.imported}条 · 重复${b.skipped}条 · ${esc(b.created_at.slice(0,16).replace('T',' '))}</span><small title="${esc(b.sha256)}">SHA256 ${esc(b.sha256.slice(0,16))}… · 已记录授权声明</small></div>`).join('')||'<p class="privacy-note">尚无导入记录。默认虚构订单不计入用户导入批次。</p>';
    $('#service-status').textContent='● 本地服务正常';
  } catch(error) {toast(error.message); $('#service-status').textContent='服务请求失败';}
  finally {$('#refresh').disabled=false;}
}
$('#category-filter').innerHTML+=[...categories].map(c=>`<option>${c}</option>`).join('');
$('#review-category').innerHTML=categories.map(c=>`<option>${c}</option>`).join('');
let searchTimer;
$('#search').addEventListener('input',()=>{clearTimeout(searchTimer); searchTimer=setTimeout(()=>{currentPage=1;loadOrders().catch(e=>toast(e.message));},200);});
for(const id of ['category-filter','platform-filter','review-only']) $('#'+id).addEventListener('change',()=>{currentPage=1;loadOrders().catch(e=>toast(e.message));});
$('#prev-page').onclick=()=>{currentPage--;loadOrders().catch(e=>toast(e.message));};
$('#next-page').onclick=()=>{currentPage++;loadOrders().catch(e=>toast(e.message));};
$('#refresh').onclick=load; $('#segment-filter').onchange=renderCustomers;
$('#review-shortcut').onclick=()=>{$('#review-only').checked=true;currentPage=1;loadOrders().catch(e=>toast(e.message));};
document.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('nav a').forEach(n=>n.classList.remove('active'));a.classList.add('active');}));
$('#orders-body').addEventListener('click',event=>{
  const button=event.target.closest('[data-review]'); if(!button)return;
  const o=currentOrders.find(o=>o.id===Number(button.dataset.review)); if(!o)return;
  reviewId=o.id; $('#review-product').textContent=o.product_name+' · '+o.order_id;
  $('#review-reason').textContent=`${o.category_reason}。原模型类别：${o.original_category}；原分值：${o.category_confidence.toFixed(3)}`;
  $('#review-category').value=o.category; $('#review-note').value=''; $('#review-dialog').showModal();
});
$('#review-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('#save-review').disabled=true;
  try {const data=await api(`/api/orders/${reviewId}/category`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:$('#review-category').value,note:$('#review-note').value})});$('#review-dialog').close();toast(data.message);await load();}
  catch(e){toast(e.message);}finally{$('#save-review').disabled=false;}
});
$('#classify-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('#classify-button').disabled=true;
  try {const r=await api('/api/classify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_name:$('#product-input').value})});$('#classify-result').innerHTML=`<b>${esc(r.category)}</b> · 模型分值 ${r.score.toFixed(3)}<p>${esc(r.reason)}</p><small>${r.needs_review?'待人工复核':'可进入分类流程'} · ${esc(r.source)}</small>`;}
  catch(e){toast(e.message);}finally{$('#classify-button').disabled=false;}
});
function importEnabled(){ $('#confirm-import').disabled=!(preview?.can_import&&$('#authorized').checked&&$('#import-source').value.trim()); }
for(const id of ['upload-trigger','integration-upload']) $('#'+id).onclick=()=>$('#import-dialog').showModal();
$('#authorized').onchange=importEnabled; $('#import-source').oninput=importEnabled;
$('#csv-file').addEventListener('change',async()=>{
  preview=null;importEnabled();const file=$('#csv-file').files[0];if(!file)return;
  $('#import-preview').textContent='正在预检…';const data=new FormData();data.append('file',file);
  try {preview=await api('/api/import/preview',{method:'POST',body:data});
    $('#import-preview').innerHTML=`<b>共${preview.total}行 · 新订单${preview.new_rows}条 · 文件内重复${preview.duplicates_in_file}条 · 已存在${preview.duplicates_existing}条 · 无效${preview.invalid}行</b><p>${esc(Object.entries(preview.mapping).map(([a,b])=>a+' → '+b).join('；'))}</p>${preview.errors.map(e=>`<p class="error">第${e.line}行：${esc(e.message)}</p>`).join('')}<div class="preview-samples">${preview.preview.slice(0,4).map(o=>`<p>${esc(o.order_id)} · ${esc(o.product_name)} → ${esc(o.category)} · ${money(o.amount)}</p>`).join('')}</div><small>${preview.can_import?'预检通过，确认授权与来源后可导入。':'请修正错误后重新选择文件，整批尚未写入。'}</small>`;
  }catch(e){$('#import-preview').textContent=e.message;}importEnabled();
});
$('#confirm-import').onclick=async()=>{
  if(!preview?.can_import)return;$('#confirm-import').disabled=true;const data=new FormData();
  data.append('file',$('#csv-file').files[0]);data.append('authorized',String($('#authorized').checked));data.append('source',$('#import-source').value);data.append('expected_sha256',preview.sha256);
  try {const r=await api('/api/import/csv',{method:'POST',body:data});$('#import-dialog').close();toast(r.message);preview=null;$('#csv-file').value='';$('#authorized').checked=false;$('#import-source').value='';$('#import-preview').textContent='选择 CSV 后预检。';currentPage=1;await load();}
  catch(e){toast(e.message);}finally{importEnabled();}
};
$('#today').textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'});
load();

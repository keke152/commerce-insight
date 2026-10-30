/* Hash routes preserve page state, browser history, direct links and mobile navigation. */
const pages={overview:'经营总览',orders:'订单与分类','customers-list':'复购机会',segments:'客户分层',model:'模型实验台',integrations:'数据接入'};
function closeNavigation(restoreFocus=false){
  document.body.classList.remove('sidebar-open');
  document.querySelector('#sidebar-scrim').hidden=true;
  document.querySelector('#menu-toggle').setAttribute('aria-expanded','false');
  if(restoreFocus)document.querySelector('#menu-toggle').focus();
}
function showPage(){
  const fromDrawer=document.body.classList.contains('sidebar-open');
  let name=location.hash.slice(1)||'overview';
  if(!Object.hasOwn(pages,name)){
    name='overview';
    history.replaceState(null,'',location.pathname+location.search+'#overview');
  }
  document.querySelectorAll('.page-view').forEach(page=>{page.hidden=page.id!==name;});
  document.querySelectorAll('[data-page]').forEach(link=>{
    const active=link.dataset.page===name;
    link.classList.toggle('active',active);
    if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  document.querySelector('#breadcrumb-current').textContent=pages[name];
  document.title=pages[name]+' · 知购 Commerce Insight';
  document.body.dataset.view=name;
  closeNavigation();
  if(fromDrawer){
    const heading=document.querySelector('#'+name+' h1');
    heading.tabIndex=-1;
    heading.focus({preventScroll:true});
  }
  window.scrollTo({top:0,behavior:'instant'});
}
document.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#"]');
  if(!link||!Object.hasOwn(pages,link.hash.slice(1)))return;
  event.preventDefault();
  if(location.hash===link.hash)showPage();else location.hash=link.hash;
});
window.addEventListener('hashchange',showPage);
document.querySelector('#menu-toggle').addEventListener('click',()=>{
  const expanded=document.body.classList.toggle('sidebar-open');
  document.querySelector('#sidebar-scrim').hidden=!expanded;
  document.querySelector('#menu-toggle').setAttribute('aria-expanded',String(expanded));
  if(expanded)document.querySelector('a[aria-current="page"]').focus();
});
document.querySelector('#sidebar-scrim').addEventListener('click',()=>closeNavigation(true));
document.querySelector('#global-search-form').addEventListener('submit',event=>{
  event.preventDefault();
  document.querySelector('#search').value=document.querySelector('#global-search').value;
  document.querySelector('#category-filter').value='';
  document.querySelector('#platform-filter').value='';
  document.querySelector('#review-only').checked=false;
  currentPage=1;
  if(location.hash!=='#orders')location.hash='#orders';else showPage();
  loadOrders().catch(error=>toast(error.message));
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&document.body.classList.contains('sidebar-open')){closeNavigation(true);return;}
  if(event.key==='/'&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)&&!document.querySelector('dialog[open]')){
    event.preventDefault();
    if(matchMedia('(max-width:760px)').matches){
      location.hash='#orders';
      requestAnimationFrame(()=>document.querySelector('#search').focus());
    }else document.querySelector('#global-search').focus();
  }
  if(event.key==='Tab'&&document.body.classList.contains('sidebar-open')){
    const links=[...document.querySelectorAll('.sidebar a[href]')];
    if(event.shiftKey&&document.activeElement===links[0]){event.preventDefault();links.at(-1).focus();}
    else if(!event.shiftKey&&document.activeElement===links.at(-1)){event.preventDefault();links[0].focus();}
  }
});
window.matchMedia('(min-width:761px)').addEventListener('change',event=>{if(event.matches)closeNavigation();});
showPage();

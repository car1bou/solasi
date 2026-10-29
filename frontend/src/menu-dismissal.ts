export function closeMenu(menu:HTMLDetailsElement){menu.open=false;menu.querySelectorAll<HTMLDetailsElement>('details[open]').forEach(child=>{child.open=false;});}
export function listenForMenuDismissal(menu:HTMLDetailsElement,doc:Document=document,events:Window=window){
  const close=()=>closeMenu(menu);
  // WebKit can focus the body on a button press; only Tab closes by focus.
  function outside(event:Event){if(menu.open&&!menu.contains(event.target as Node)){close();if(event.type==='pointerdown'&&event.target instanceof Element&&event.target.closest('.page-viewport')){event.preventDefault();event.stopPropagation();}}}
  function escape(event:KeyboardEvent){if(menu.open&&event.key==='Tab')setTimeout(()=>{if(menu.open&&!menu.contains(doc.activeElement))close();},0);if(menu.open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close();menu.querySelector<HTMLElement>('summary')?.focus();}}
  function opened(event:Event){const element=(event as CustomEvent<Node>).detail;if(element&&!menu.contains(element))close();}
  function toggle(event:Event){if(event.target===menu&&menu.open)events.dispatchEvent(new CustomEvent('solasi-popup-open',{detail:menu}));}
  doc.addEventListener('pointerdown',outside,{capture:true});doc.addEventListener('keydown',escape,{capture:true});
  menu.addEventListener('toggle',toggle);events.addEventListener('solasi-popup-open',opened);events.addEventListener('solasi-navigated',close);
  return()=>{doc.removeEventListener('pointerdown',outside,{capture:true});doc.removeEventListener('keydown',escape,{capture:true});menu.removeEventListener('toggle',toggle);events.removeEventListener('solasi-popup-open',opened);events.removeEventListener('solasi-navigated',close);};
}

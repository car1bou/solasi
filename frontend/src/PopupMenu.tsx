import React,{useEffect,useState} from 'react';
import {closeMenu,listenForMenuDismissal} from './menu-dismissal';

export default function PopupMenu(props:React.DetailsHTMLAttributes<HTMLDetailsElement>){
  const [element,setElement]=useState<HTMLDetailsElement|null>(null);
  useEffect(()=>{
    if(!element)return;
    const fit=()=>{
      const panel=element.querySelector<HTMLElement>('.notebook-menu-panel');if(!element.open||!panel)return;
      const rect=element.getBoundingClientRect(),below=window.innerHeight-rect.bottom-18,above=rect.top-18,up=below<180&&above>below;
      panel.style.top=up?'auto':'calc(100% + 6px)';panel.style.bottom=up?'calc(100% + 6px)':'auto';
      panel.style.maxHeight=Math.max(60,Math.min(window.innerHeight*.55,up?above:below))+'px';
    };
    const dismiss=listenForMenuDismissal(element);
    element.addEventListener('toggle',fit);window.addEventListener('resize',fit);document.addEventListener('scroll',fit,true);
    return()=>{dismiss();element.removeEventListener('toggle',fit);window.removeEventListener('resize',fit);document.removeEventListener('scroll',fit,true);};
  },[element]);
  return <details {...props} ref={setElement} onClick={event=>{
    props.onClick?.(event);
    // Close in React's bubbling handler, after the chosen item's handler has run.
    if(event.target instanceof Element&&event.target.closest('[data-menu-action]')){closeMenu(event.currentTarget);event.currentTarget.querySelector<HTMLElement>('summary')?.focus();}
  }}/>;
}

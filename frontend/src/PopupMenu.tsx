import React,{useEffect,useState} from 'react';
import {closeMenu,listenForMenuDismissal} from './menu-dismissal';

export default function PopupMenu(props:React.DetailsHTMLAttributes<HTMLDetailsElement>){
  const [element,setElement]=useState<HTMLDetailsElement|null>(null);
  useEffect(()=>element?listenForMenuDismissal(element):undefined,[element]);
  return <details {...props} ref={setElement} onClick={event=>{
    props.onClick?.(event);
    // Close in React's bubbling handler, after the chosen item's handler has run.
    if(event.target instanceof Element&&event.target.closest('[data-menu-action]')){closeMenu(event.currentTarget);event.currentTarget.querySelector<HTMLElement>('summary')?.focus();}
  }}/>;
}

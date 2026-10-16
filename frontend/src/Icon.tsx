import React from 'react';

const paths={
  book:<><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4z"/><path d="M13 7a3 3 0 0 1 3-3h5v14h-4a4 4 0 0 0-4 3"/></>,
  mic:<><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></>,
  settings:<><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/></>,
  plus:<path d="M12 5v14M5 12h14"/>,
  arrow:<path d="M5 12h14m-6-6 6 6-6 6"/>,
  chevron:<path d="m9 5 7 7-7 7"/>,
  wave:<path d="M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4"/>,
  shield:<><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/></>,
};
export default function Icon({name,size=20}:{name:keyof typeof paths;size?:number}){
  return <svg className="ui-icon" aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

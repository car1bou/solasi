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
  pen:<><path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z"/><path d="m4 14 5 5"/></>,
  highlighter:<><path d="m14 3 7 7-9 9-7-7zM5 12l-2 5 4 4 5-2M3 21h5"/><path d="m11 6 7 7"/></>,
  'stroke-eraser':<><path d="m14 3 7 7-10 10H7l-4-4a2 2 0 0 1 0-3zM8 8l8 8M14 21h7"/><path d="m3 3 3 3m0-3L3 6"/></>,
  'partial-eraser':<><path d="m14 3 7 7-10 10H7l-4-4a2 2 0 0 1 0-3zM8 8l8 8"/><path d="M14 21h2m3 0h2" strokeDasharray="1 2"/></>,
  lasso:<><path d="M5 16C-2 9 4 3 12 3s12 6 8 11-14 5-14 1 6-3 4 2-1 5 3 5" strokeDasharray="3 2"/></>,
  hand:<><path d="M18 11V7a2 2 0 0 0-4 0M14 10V5a2 2 0 0 0-4 0v2M10 11V7a2 2 0 0 0-4 0v7"/><path d="M18 9a2 2 0 0 1 4 0v6a7 7 0 0 1-7 7h-3c-3 0-4-2-6-4l-3-4a2 2 0 0 1 3-3l2 2"/></>,
  undo:<path d="m9 4-6 6 6 6M3 10h11a7 7 0 0 1 0 14" transform="translate(0 -2)"/>,
  redo:<path d="m15 4 6 6-6 6M21 10H10a7 7 0 0 0 0 14" transform="translate(0 -2)"/>,
  fit:<><path d="M4 4v16M20 4v16M7 12h10m-7-3-3 3 3 3m4-6 3 3-3 3"/></>,
  rotate:<><path d="M20 9a8 8 0 1 0 0 6M20 3v6h-6"/></>,
  save:<><path d="M4 3h13l4 4v14H3V3zM7 3v6h10V3M7 21v-8h10v8"/></>,
  download:<><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
  'panel-close':<><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16m-7-11 3 3-3 3"/></>,
  'panel-open':<><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16m-4-11-3 3 3 3"/></>,
  refresh:<><path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5"/></>,
  previous:<path d="m15 5-7 7 7 7"/>,
  next:<path d="m9 5 7 7-7 7"/>,
  close:<path d="m6 6 12 12M6 18 18 6"/>,
  play:<path d="m8 4 12 8-12 8z" fill="currentColor" stroke="none"/>,
  pause:<><rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/></>,
};
export default function Icon({name,size=20}:{name:keyof typeof paths;size?:number}){
  return <svg className="ui-icon" aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

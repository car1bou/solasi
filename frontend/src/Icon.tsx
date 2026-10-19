import React from 'react';

// Handwriting glyphs follow Solasi’s approved A outline concept. Other glyphs: Lucide 1ef60af944de207e0d5176905a0759ba12e6ee8d; notices: public/notices/lucide.txt.
const paths={
  'book':<><path d="M12 5v16" /><path d="M20.001 19A2 2 0 0022 17V5a2 2 0 00-1.999-2L16 3.002A5 5 0 0012 5a5 5 0 00-4-2H4a2 2 0 00-2 2v12a2 2 0 001.999 2H8a5 5 0 014 2 5 5 0 014-2z" /></>,
  'mic':<><path d="M12 19v3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><rect x="9" y="2" width="6" height="13" rx="3" /></>,
  'settings':<><path d="M10 5H3" /><path d="M12 19H3" /><path d="M14 3v4" /><path d="M16 17v4" /><path d="M21 12h-9" /><path d="M21 19h-5" /><path d="M21 5h-7" /><path d="M8 10v4" /><path d="M8 12H3" /></>,
  'plus':<><path d="M5 12h14" /><path d="M12 5v14" /></>,
  'arrow':<><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></>,
  'chevron':<><path d="m9 18 6-6-6-6" /></>,
  'wave':<><path d="M2 10v3" /><path d="M6 6v11" /><path d="M10 3v18" /><path d="M14 8v7" /><path d="M18 5v13" /><path d="M22 10v3" /></>,
  'shield':<><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></>,
  'pen':<g transform="rotate(40 12 12)"><rect x="9" y="2" width="6" height="13.5" rx="2.8" /><path d="m9.3 15.1.5 4.4 2.2 3 2.2-3 .5-4.4M15 5h1.8v6" /><circle cx="12" cy="19" r=".65" fill="currentColor" stroke="none" /></g>,
  'highlighter':<g transform="rotate(40 12 12)"><path d="M10 2h4a2 2 0 0 1 2 2v11l-2 3h-4l-2-3V4a2 2 0 0 1 2-2ZM8 15h8M10 18v4h4v-4" /></g>,
  'stroke-eraser':<g transform="rotate(45 12 12)"><rect x="7" y="3" width="10" height="18" rx="2.2" /><path d="M7 14h10" /></g>,
  'partial-eraser':<g transform="rotate(45 12 12)"><rect x="7" y="3" width="10" height="18" rx="2.2" /><path d="M7 14h10" /></g>,
  'lasso':<><ellipse cx="12" cy="11" rx="9.5" ry="5.8" transform="rotate(-25 12 11)" strokeDasharray="2.5 2.6" /><path d="m16.3 17.4 1.5 2.5" /></>,
  'hand':<path d="M7 12V5.5a1.5 1.5 0 0 1 3 0V10 3.5a1.5 1.5 0 0 1 3 0V10 5a1.5 1.5 0 0 1 3 0v6-3.5a1.5 1.5 0 0 1 3 0V14c0 5-2.4 8-6.8 8-3 0-4.7-1.6-6.2-4L3 13.5a1.6 1.6 0 0 1 2.4-2Z" />,
  'undo':<><path d="m7.5 5-4.5 4.5L7.5 14" /><path d="M3 9.5h10.5c7 0 9 7.2 4 10.5" /></>,
  'redo':<><path d="m16.5 5 4.5 4.5-4.5 4.5" /><path d="M21 9.5H10.5c-7 0-9 7.2-4 10.5" /></>,
  'fit':<><path d="m18 8 4 4-4 4" /><path d="M2 12h20" /><path d="m6 8-4 4 4 4" /></>,
  'rotate':<><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /></>,
  'save':<><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" /><path d="M7 3v4a1 1 0 0 0 1 1h7" /></>,
  'download':<><path d="M12 15V3" /><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /></>,
  'panel-close':<><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M15 3v18" /><path d="m8 9 3 3-3 3" /></>,
  'panel-open':<><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M15 3v18" /><path d="m10 15-3-3 3-3" /></>,
  'refresh':<><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></>,
  'previous':<><path d="m15 18-6-6 6-6" /></>,
  'next':<><path d="m9 18 6-6-6-6" /></>,
  'close':<><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
  'play':<><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" /></>,
  'pause':<><rect x="14" y="3" width="5" height="18" rx="1" /><rect x="5" y="3" width="5" height="18" rx="1" /></>,
};
const handwritingIcons=new Set(['pen','highlighter','stroke-eraser','partial-eraser','lasso','hand','undo','redo']);
export default function Icon({name,size=20}:{name:keyof typeof paths;size?:number}){
  return <svg className="ui-icon" aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={handwritingIcons.has(name)?1.65:2} strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

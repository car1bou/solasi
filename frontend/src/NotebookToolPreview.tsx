import React from 'react';
import InkMark from './InkMark';
import type {InkStroke} from './types';
import type {NotebookTools} from './notebook-preferences';

export default function NotebookToolPreview({tools}:{tools:NotebookTools}){
 const {tool}=tools,highlighter=tool==='highlighter',eraser=tool.includes('eraser');
 const common={id:'preview',input:'mouse' as const,color:highlighter?tools.highlighterColor:tools.penColor,opacity:highlighter?tools.highlighterOpacity:tools.penOpacity};
 const stroke:InkStroke=tool==='text'?{...common,tool:'text',width:tools.textSize??.025,text:'가 Aa',points:[{x:16/680,y:.12,pressure:.5},{x:224/680,y:.96,pressure:.5}]}:{...common,tool:highlighter?'highlighter':'pen',width:highlighter?tools.highlighterWidth:tools.penWidth,points:[{x:20/680,y:.5,pressure:.5},{x:220/680,y:.5,pressure:.5}]};
 return <div className="ink-setting-preview" aria-hidden="true"><svg width="240" height="96" viewBox="0 0 240 96">{eraser?<circle cx="120" cy="48" r={tools.eraserSize*680} fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3"/>:<InkMark stroke={stroke} width={680} height={96}/>}</svg></div>;
}

import React from 'react';
import {inkPath} from './ink';
import type {InkStroke} from './types';

export default React.memo(function InkMark({stroke,width,height}:{stroke:InkStroke;width:number;height:number}){
  if(stroke.tool!=='text')return <path d={inkPath(stroke,width,height)} fill={stroke.color} opacity={stroke.opacity} pointerEvents="none"/>;
  const [start,end]=stroke.points;
  if(!start||!end)return null;
  return <foreignObject x={start.x*width} y={start.y*height} width={Math.max(0,end.x-start.x)*width} height={Math.max(0,end.y-start.y)*height} opacity={stroke.opacity} pointerEvents="none" style={{overflow:'hidden'}}>
    <div style={{fontFamily:'sans-serif',fontSize:stroke.width*width,lineHeight:1.25,color:stroke.color,whiteSpace:'pre-wrap',overflowWrap:'anywhere',height:'100%',overflow:'hidden'}}>{stroke.text}</div>
  </foreignObject>;
});

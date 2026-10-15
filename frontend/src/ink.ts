import type {InkPoint,InkStroke} from './types';
export type Point={x:number;y:number};
export type Bounds={x:number;y:number;width:number;height:number};
export const clamp=(value:number,min=0,max=1)=>Math.max(min,Math.min(max,value));
export function inkPath(stroke:InkStroke,width:number,height:number){
  const points=stroke.points;if(!points.length)return '';
  const half=(point:InkPoint)=>stroke.width*width*(stroke.tool==='pen'?.35+.65*point.pressure:1)/2;
  if(points.length===1){const p=points[0],r=half(p),x=p.x*width,y=p.y*height;return `M${x-r},${y}a${r},${r} 0 1,0 ${r*2},0a${r},${r} 0 1,0 ${-r*2},0`;}
  const left:Point[]=[],right:Point[]=[];
  points.forEach((p,i)=>{const previous=points[Math.max(0,i-1)],next=points[Math.min(points.length-1,i+1)],dx=(next.x-previous.x)*width,dy=(next.y-previous.y)*height,length=Math.hypot(dx,dy)||1,r=half(p),x=p.x*width,y=p.y*height;left.push({x:x-dy/length*r,y:y+dx/length*r});right.push({x:x+dy/length*r,y:y-dx/length*r});});
  return 'M'+left.concat(right.reverse()).map(p=>p.x+','+p.y).join('L')+'Z';
}
export function inkBounds(strokes:InkStroke[]):Bounds|null{let minX=1,minY=1,maxX=0,maxY=0,found=false;for(const stroke of strokes)for(const point of stroke.points){found=true;minX=Math.min(minX,point.x);minY=Math.min(minY,point.y);maxX=Math.max(maxX,point.x);maxY=Math.max(maxY,point.y);}return found?{x:minX,y:minY,width:Math.max(.003,maxX-minX),height:Math.max(.003,maxY-minY)}:null;}
export function inside(point:Point,polygon:Point[]){let hit=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.y>point.y)!==(b.y>point.y)&&point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x)hit=!hit;}return hit;}
function distance(p:Point,a:Point,b:Point,aspect:number){const dx=b.x-a.x,dy=(b.y-a.y)*aspect,length=dx*dx+dy*dy,t=length?clamp(((p.x-a.x)*dx+(p.y-a.y)*aspect*dy)/length):0;return Math.hypot(p.x-a.x-t*dx,(p.y-a.y)*aspect-t*dy);}
function interpolate(a:InkPoint,b:InkPoint,t:number):InkPoint{return{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,pressure:a.pressure+(b.pressure-a.pressure)*t,...(a.tilt_x!==undefined?{tilt_x:a.tilt_x+((b.tilt_x??a.tilt_x)-a.tilt_x)*t}:{}),...(a.tilt_y!==undefined?{tilt_y:a.tilt_y+((b.tilt_y??a.tilt_y)-a.tilt_y)*t}:{})};}
export function eraseInk(strokes:InkStroke[],center:Point,radius:number,partial:boolean,aspect:number):InkStroke[]{
  return strokes.flatMap(stroke=>{
    const points=stroke.points,r=radius+stroke.width/2;
    const hits=points.length===1?Math.hypot(points[0].x-center.x,(points[0].y-center.y)*aspect)<=r:points.some((p,i)=>i>0&&distance(center,points[i-1],p,aspect)<=r);
    if(!hits)return[stroke];if(!partial||points.length===1)return[];
    const pieces:InkPoint[][]=[];let current:InkPoint[]=[];
    for(let i=1;i<points.length;i++){
      const a=points[i-1],b=points[i],dx=b.x-a.x,dy=(b.y-a.y)*aspect,ax=a.x-center.x,ay=(a.y-center.y)*aspect,A=dx*dx+dy*dy,B=2*(ax*dx+ay*dy),C=ax*ax+ay*ay-r*r,D=B*B-4*A*C;
      const cuts=[0,1];if(A>0&&D>0){for(const t of [(-B-Math.sqrt(D))/(2*A),(-B+Math.sqrt(D))/(2*A)])if(t>0&&t<1)cuts.push(t);}cuts.sort((x,y)=>x-y);
      for(let j=1;j<cuts.length;j++){const from=cuts[j-1],to=cuts[j],mid=(from+to)/2,outside=Math.hypot(ax+dx*mid,ay+dy*mid)>r;
        if(outside){const start=interpolate(a,b,from);if(!current.length)current.push(start);current.push(interpolate(a,b,to));}else if(current.length){pieces.push(current);current=[];}}
    }
    if(current.length)pieces.push(current);
    return pieces.map((points,i)=>({...stroke,id:i===0?stroke.id:crypto.randomUUID(),points}));
  });
}

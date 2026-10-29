export function pageAtPosition(pages:{page:number;top:number;bottom:number}[],position:number){
  if(!pages.length)return null;
  return (pages.find(row=>row.bottom>=position)||pages[pages.length-1]).page;
}

export function pageShortcut(key:string,editable:boolean,modified:boolean,page:number,total:number){
  if(editable||modified)return null;
  const next=key==='ArrowLeft'?page-1:key==='ArrowRight'?page+1:page;
  return next!==page&&next>=1&&next<=total?next:null;
}

export function parsePageNumber(value:string,total:number){
  const text=value.trim();if(!/^\d+$/.test(text))return null;
  const page=Number(text);return Number.isSafeInteger(page)&&page>=1&&page<=total?page:null;
}

export function notebookViewportHeight(height:number,top:number){
  return Math.max(180,height-Math.max(0,top)-12);
}

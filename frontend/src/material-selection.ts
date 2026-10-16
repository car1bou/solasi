export type MaterialView={selected:string|null;page:number};
// shortcut: remembers navigation for this app window only; persist if cross-launch restoration is needed.
const views=new Map<string,MaterialView>();
export function materialView(owner:string):MaterialView{return views.get(owner)||{selected:null,page:1};}
export function rememberMaterialView(owner:string,view:MaterialView){views.set(owner,view);}
export function connectedMaterialView(current:MaterialView,files:{asset:{id:string}}[]):MaterialView{
  return files.length?{selected:files[0].asset.id,page:1}:current;
}

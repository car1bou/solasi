const closeGuards=new Map<symbol,{label:string;dirty:()=>boolean}>();

export function registerCloseGuard(label:string,dirty:()=>boolean){
  const key=Symbol(label);closeGuards.set(key,{label,dirty});
  return()=>{closeGuards.delete(key);};
}

function unsavedEditors(preserved:string[]=[]){return [...new Set([...closeGuards.values()].filter(guard=>!preserved.includes(guard.label)&&guard.dirty()).map(guard=>guard.label))];}
export function navigate(action:()=>void,preserved:string[]=[]){
  const labels=unsavedEditors(preserved);
  if(labels.length){window.dispatchEvent(new CustomEvent('solasi-navigation-blocked',{detail:labels.join(' · ')+'에 저장하지 않은 입력이 있습니다. 저장하거나 입력을 되돌린 뒤 이동하세요.'}));return false;}
  window.dispatchEvent(new Event('solasi-finish-ink'));
  action();window.dispatchEvent(new Event('solasi-navigated'));return true;
}

export function createCloseLifecycle(flush:()=>Promise<void>,resumeDrafts:()=>void){
  let attempt=0,closing=false;
  function resume(){attempt++;closing=false;document.getElementById('root')!.inert=false;resumeDrafts();}
  function checkEditors(){
    const labels=unsavedEditors();
    if(labels.length)throw new Error([...new Set(labels)].join(' · ')+'에 저장하지 않은 수정이 있습니다. 저장하거나 수정을 취소한 뒤 다시 닫아 주세요.');
  }
  return {
    async prepareClose(){
      if(closing)throw new Error('초안 저장을 기다려 주세요.');
      checkEditors();
      const current=++attempt;closing=true;
      try{
        window.dispatchEvent(new Event('solasi-finish-ink'));
        document.getElementById('root')!.inert=true;
        await flush();
        if(current!==attempt)throw new Error('창 닫기가 취소되었습니다.');
        checkEditors();
        return true;
      }catch(error){if(current===attempt)resume();throw error;}
    },
    resume,
  };
}

declare global {interface Window {solasiLifecycle?:ReturnType<typeof createCloseLifecycle>;}}

const closeGuards=new Map<symbol,{label:string;dirty:()=>boolean}>();

export function registerCloseGuard(label:string,dirty:()=>boolean){
  const key=Symbol(label);closeGuards.set(key,{label,dirty});
  return()=>{closeGuards.delete(key);};
}

export function createCloseLifecycle(flush:()=>Promise<void>,resumeDrafts:()=>void){
  let attempt=0,closing=false;
  function resume(){attempt++;closing=false;document.getElementById('root')!.inert=false;resumeDrafts();}
  function checkEditors(){
    const labels=[...closeGuards.values()].filter(guard=>guard.dirty()).map(guard=>guard.label);
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

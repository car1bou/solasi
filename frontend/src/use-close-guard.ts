import {useEffect,useRef} from 'react';
import {registerCloseGuard} from './native-lifecycle';

export function useCloseGuard(label:string,dirty:boolean){
  const current=useRef(dirty);current.current=dirty;
  useEffect(()=>registerCloseGuard(label,()=>current.current),[label]);
}

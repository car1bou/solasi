import {useEffect,useRef} from 'react';
import {nativeApp} from './api';
import {registerCloseGuard} from './native-lifecycle';

export function useCloseGuard(label:string,dirty:boolean){
  const current=useRef(dirty);current.current=dirty;
  useEffect(()=>nativeApp()?registerCloseGuard(label,()=>current.current):undefined,[label]);
}

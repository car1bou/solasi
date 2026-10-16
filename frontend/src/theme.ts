import {api,nativeApp} from './api.ts';
export type ThemePreference='system'|'light'|'dark';
const key='solasi.theme';
let preference:ThemePreference='system';
let system:MediaQueryList;

function apply(){
  const theme=preference==='system'?(system.matches?'dark':'light'):preference;
  document.documentElement.dataset.theme=theme;
  document.documentElement.style.colorScheme=theme;
  const meta=document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if(meta)meta.content=theme==='dark'?'#171717':'#FFFFFF';
}
export function initializeTheme(initial?:ThemePreference){
  system=window.matchMedia('(prefers-color-scheme: dark)');
  try{const value=initial??window.localStorage.getItem(key);preference=value==='light'||value==='dark'?value:'system';}catch{preference='system';}
  apply();
  system.addEventListener('change',apply);
}
export function getThemePreference(){return preference;}
export async function setThemePreference(value:ThemePreference){
  preference=value;
  let saved=true;
  apply();
  try{if(nativeApp())await api('/native/theme',{method:'PUT',body:JSON.stringify({theme:value})});else window.localStorage.setItem(key,value);}catch{saved=false;}
  return saved;
}

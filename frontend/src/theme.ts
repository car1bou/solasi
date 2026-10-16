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
export function initializeTheme(){
  system=window.matchMedia('(prefers-color-scheme: dark)');
  try{const value=window.localStorage.getItem(key);preference=value==='light'||value==='dark'?value:'system';}catch{preference='system';}
  apply();
  system.addEventListener('change',apply);
}
export function getThemePreference(){return preference;}
export function setThemePreference(value:ThemePreference){
  preference=value;
  let saved=true;
  try{window.localStorage.setItem(key,value);}catch{saved=false;}
  apply();
  return saved;
}

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import {initializeTheme} from './theme';
import type {ThemePreference} from './theme';
import {api,nativeApp} from './api';
import {createCloseLifecycle} from './native-lifecycle';
import {flushPageDrafts,resumePageDrafts} from './page-drafts';
import {flushNotebookPreferences} from './notebook-preferences';
import './styles.css';
if(nativeApp())window.solasiLifecycle=createCloseLifecycle(async()=>{await flushPageDrafts();await flushNotebookPreferences();},resumePageDrafts);
async function start(){
  const state=nativeApp()?await api<{theme:ThemePreference}>('/native/state'):undefined;
  initializeTheme(state?.theme);
  createRoot(document.getElementById('root')!).render(<App />);
}
async function boot(){
  try{await start();}catch(error){
    const root=document.getElementById('root')!,message=document.createElement('p'),retry=document.createElement('button');
    message.setAttribute('role','alert');message.textContent='앱 보관함을 열지 못했습니다. '+(error as Error).message;
    retry.textContent='다시 연결';retry.onclick=()=>{retry.disabled=true;retry.textContent='연결 중…';void boot();};
    root.replaceChildren(message,retry);
  }
}
void boot();

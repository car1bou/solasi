import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import {initializeTheme} from './theme';
import type {ThemePreference} from './theme';
import {api,nativeApp} from './api';
import {createCloseLifecycle} from './native-lifecycle';
import {flushPageDrafts,resumePageDrafts} from './page-drafts';
import './styles.css';
if(nativeApp())window.solasiLifecycle=createCloseLifecycle(flushPageDrafts,resumePageDrafts);
async function start(){
  const state=nativeApp()?await api<{theme:ThemePreference}>('/native/state'):undefined;
  initializeTheme(state?.theme);
  createRoot(document.getElementById('root')!).render(<App />);
}
void start().catch(error=>{document.getElementById('root')!.textContent='앱 보관함을 열지 못했습니다. Solasi를 다시 실행해 주세요. '+(error as Error).message;});

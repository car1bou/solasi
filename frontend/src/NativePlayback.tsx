import {useEffect,useState} from 'react';
import PlaybackAudio from './PlaybackAudio';
import {subscribeNativeAudio} from './native-playback-links';
import type {NativeClip} from './native-playback-links';

export default function NativePlayback(){
  const [clip,setClip]=useState<NativeClip|null>(null),[error,setError]=useState('');
  useEffect(()=>subscribeNativeAudio(value=>{setClip(value);setError('');},setError),[]);
  if(!clip)return error?<p role="alert">{error}</p>:null;
  return <dialog open aria-label="내보낸 대본의 원음" className="native-playback"><p>원음 {clip.start.toFixed(1)}–{clip.end.toFixed(1)}초</p><PlaybackAudio key={clip.url+clip.start} controls src={clip.url} onLoadedMetadata={event=>{event.currentTarget.currentTime=clip.start;}} onPlay={event=>{if(event.currentTarget.currentTime<clip.start||event.currentTarget.currentTime>=clip.end)event.currentTarget.currentTime=clip.start;}} onTimeUpdate={event=>{if(event.currentTarget.currentTime>=clip.end)event.currentTarget.pause();}} onError={()=>setError('이 보관함에서 원음을 열 수 없습니다.')}/>{error&&<p role="alert">{error}</p>}<button onClick={()=>setClip(null)}>닫기</button></dialog>;
}

import React,{useEffect,useRef,useState} from 'react';
import type {Asset,Course,DocumentMetadata,DocumentPage} from './types';
import PageNotebook from './PageNotebook';

export default function ContinuousPage({asset,course,metadata,page,active,controlsTarget,headingTarget,menuActions,notesTarget,scrollViewport,hidden=false}:{hidden?:boolean;asset:Asset;course?:Course;metadata:DocumentMetadata;page:DocumentPage;active:boolean;controlsTarget?:HTMLElement|null;headingTarget?:HTMLElement|null;menuActions?:React.ReactNode;notesTarget?:HTMLElement|null;scrollViewport?:React.RefObject<HTMLDivElement|null>}){
  const element=useRef<HTMLDivElement>(null),[loaded,setLoaded]=useState(active);
  useEffect(()=>{
    const target=element.current;if(!target)return;
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setLoaded(true);observer.disconnect();}},{root:scrollViewport?.current||null,rootMargin:'800px 0px'});
    observer.observe(target);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{if(active)setLoaded(true);},[active]);
  return <div ref={element} hidden={hidden} className="continuous-page" data-material-page={page.page}>
    {loaded?(course?<PageNotebook courseId={course.id} document={metadata} page={page} filename={asset.filename} handwritten={asset.handwritten} active={active} controlsTarget={controlsTarget} headingTarget={headingTarget} menuActions={menuActions} notesTarget={notesTarget} scrollViewport={scrollViewport}/>:<div className="page-image original-page"><strong>{page.page}쪽</strong><img loading="lazy" alt={asset.filename+' '+page.page+'쪽 원본'} src={'/api/assets/'+asset.id+'/pages/'+page.page+'?document_sha256='+encodeURIComponent(metadata.sha256)}/></div>):<div className="continuous-placeholder" style={{aspectRatio:`${page.width} / ${page.height}`}} aria-label={page.page+'쪽 불러오기 대기'}/>}
  </div>;
}

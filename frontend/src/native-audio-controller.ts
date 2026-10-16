export type NativeAudioState={ready:boolean;duration:number;currentTime:number;paused:boolean;ended:boolean;seeked:boolean;error:string};
type Command=(fields:Record<string,unknown>)=>Promise<unknown>;
type Notify=(state:NativeAudioState,previous:NativeAudioState,event:boolean)=>void;

// Only playing/loading audio owns an AVPlayer; paused controls retain their cursor here.
export class NativeAudioController {
  state:NativeAudioState={ready:false,duration:0,currentTime:0,paused:true,ended:false,seeked:false,error:''};
  private path:string;
  private command:Command;
  private notify:Notify;
  private id:string|null=null;
  private queue:Promise<void>=Promise.resolve();
  private disposed=false;
  private desiredPaused=true;
  private pendingSeeks=0;
  private restoring=false;
  private volume=1;
  private releaseScheduled=new Set<string>();

  constructor(path:string,command:Command,notify:Notify){this.path=path;this.command=command;this.notify=notify;}
  private update(next:NativeAudioState,event=false){
    const previous=this.state;this.state=next;if(!this.disposed)this.notify(next,previous,event);
  }
  private run(action:()=>Promise<void>){
    const result=this.queue.then(async()=>{if(!this.disposed)await action();});
    this.queue=result.catch(()=>{});return result;
  }
  private async load(restore=true){
    if(this.id)return this.id;
    const id=crypto.randomUUID();this.id=id;this.restoring=restore&&this.state.currentTime>0;
    try{
      await this.command({op:'playback_load',id,path:this.path});
      await this.command({op:'playback_volume',id,volume:this.volume});
      if(this.restoring)await this.command({op:'playback_seek',id,time:this.state.currentTime});
      return id;
    }catch(error){
      if(this.id===id)this.id=null;
      await this.command({op:'playback_close',id}).catch(()=>{});throw error;
    }finally{this.restoring=false;}
  }
  private async release(){
    const id=this.id;if(!id)return;
    const result=await this.command({op:'playback_release',id}) as Partial<NativeAudioState>;
    if(this.id!==id)return;this.id=null;
    const time=result.currentTime;
    this.update({...this.state,currentTime:this.pendingSeeks||typeof time!=='number'||!Number.isFinite(time)?this.state.currentTime:time,paused:true});
  }
  preload(){return this.run(async()=>{await this.load();});}
  play(){
    this.desiredPaused=false;
    return this.run(async()=>{
      const id=await this.load();
      if(!this.disposed&&!this.desiredPaused)await this.command({op:'playback_play',id});
    });
  }
  pause(){
    this.desiredPaused=true;this.update({...this.state,paused:true});
    return this.run(()=>this.release());
  }
  seek(time:number){
    if(!Number.isFinite(time)||time<0)return Promise.reject(new Error('재생 시각을 확인하세요.'));
    this.pendingSeeks++;this.update({...this.state,currentTime:time,ended:false});
    return this.run(async()=>{
      const id=await this.load(false);await this.command({op:'playback_seek',id,time});
    }).finally(()=>{this.pendingSeeks--;});
  }
  setVolume(volume:number){
    this.volume=volume;
    return this.run(async()=>{if(this.id)await this.command({op:'playback_volume',id:this.id,volume});});
  }
  receive(next:NativeAudioState&{id:string}){
    if(this.disposed||next.id!==this.id)return;
    this.update({...next,ready:this.state.ready||next.ready,currentTime:this.restoring||this.pendingSeeks?this.state.currentTime:next.currentTime,paused:this.desiredPaused||next.paused},true);
    if(next.ended)this.desiredPaused=true;
    const id=this.id;
    if(id&&(next.ready&&this.desiredPaused||next.ended||next.error)&&!this.releaseScheduled.has(id)){
      this.releaseScheduled.add(id);
      void this.run(async()=>{if(this.id===id&&(this.desiredPaused||next.error))await this.release();})
        .catch(error=>this.fail(error)).finally(()=>this.releaseScheduled.delete(id));
    }
  }
  fail(error:unknown){this.update({...this.state,error:error instanceof Error?error.message:String(error)},true);}
  dispose(){
    this.disposed=true;this.desiredPaused=true;
    return this.queue.then(async()=>{const id=this.id;this.id=null;if(id)await this.command({op:'playback_close',id});});
  }
}

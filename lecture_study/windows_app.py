"""Windows WebView2 shell. All HTTPS app resources stay in-process; no web server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
import webbrowser

from .config import AppConfig
from .windows_bridge import Commands, Engine, ORIGIN, Response, publish_export, resource_path, static_response, trusted_url

MARKER="if(window===window.top&&location.origin==='https://solasi.invalid'){Object.defineProperty(window,'solasiWindows',{value:{command:(message)=>window.pywebview.api.command(message)},writable:false,configurable:false});}"


def finish_close(engine,prepare,confirm,resume):
    prepare()
    if engine.captures and not confirm():resume();return False
    engine.close();return True


class CommandAPI:
    # Expose only command; pywebview recursively exposes public object attributes.
    def __init__(self,host):self._host=host
    def command(self,message):return self._host.command(message)


class Host:
    def __init__(self,engine,frontend):
        self.engine=engine;self.frontend=Path(frontend).resolve();self.window=None;self.core=None
        self.trusted=False;self.ready=False;self.approved_close=False;self.closing=False
        self.navigation_id=None
        self.pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='Solasi.resources')
        self.pending=0;self.pending_lock=threading.Lock()
        self.instance=None;self.pending_audio=None;self.audio_lock=threading.Lock();self.delivering_audio=False

    def bind(self,window):
        self.window=window
        self.commands=Commands(self.engine,lambda:self.trusted,self.select_files,self.save_file,self.emit)
        window.events.before_show+=self.attach
        window.events.closing+=self.on_close

    def command(self,message):
        result=self.commands.command(message)
        if message.get('op')=='ui_ready':self.ready=True;self.deliver_audio()
        return result

    def ui(self,callback):
        from System import Action
        self.window.native.webview.BeginInvoke(Action(callback))

    def attach(self):
        def connect():
            try:
                from .windows_instance import Receiver
                self.instance=Receiver(self.window.native.Handle.ToInt64(),self.engine.config.data_dir,self.queue_audio)
                native=self.window.native.webview
                if native.CoreWebView2:self.configure()
                else:
                    def initialized(_,args):
                        if args.IsSuccess:self.configure()
                        else:self.startup_error(str(args.InitializationException))
                    native.CoreWebView2InitializationCompleted+=initialized
                    native.EnsureCoreWebView2Async(None)
            except Exception as error:self.startup_error(str(error))
        self.ui(connect)

    def configure(self):
        from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
        from System import Action,String
        from System.Threading.Tasks import Task
        try:
            self.core=self.window.native.webview.CoreWebView2
            self.core.AddWebResourceRequestedFilter('*',CoreWebView2WebResourceContext.All)
            self.core.WebResourceRequested+=self.resource
            self.core.NavigationStarting+=self.navigation
            self.core.SourceChanged+=self.source_changed
            self.core.NavigationCompleted+=self.loaded
            self.core.NewWindowRequested+=self.new_window
            self.core.DownloadStarting+=self.download
            self.core.ProcessFailed+=self.process_failed
            self.core.FrameCreated+=self.frame_created
            task=self.core.AddScriptToExecuteOnDocumentCreatedAsync(MARKER)
            def installed(done):
                if done.IsFaulted:self.ui(lambda:self.startup_error(str(done.Exception)))
                else:self.ui(lambda:self.core.Navigate(ORIGIN+'/'))
            task.ContinueWith(Action[Task[String]](installed))
        except Exception as error:self.startup_error(str(error))

    def startup_error(self,message):
        logging.error('WebView2 initialization failed: %s',message)
        self.show_error('화면 엔진을 시작하지 못했습니다. WebView2 Runtime 설치와 앱 로그를 확인하세요.\n'+message)

    def navigation(self,_,args):
        url=str(args.Uri)
        if url=='about:blank' and self.core is None:return
        if trusted_url(url):self.navigation_id=int(args.NavigationId);self.trusted=False;self.ready=False;return
        args.Cancel=True
        if args.IsUserInitiated:self.pool.submit(self.open_link,url)

    def loaded(self,_,args):
        if self.navigation_id is None or int(args.NavigationId)!=self.navigation_id:return
        self.trusted=bool(args.IsSuccess and trusted_url(str(self.core.Source)))
        if not args.IsSuccess:
            self.ready=False
            self.pool.submit(self.show_error,'화면을 불러오지 못했습니다. 앱을 다시 열고 저장된 기록을 확인하세요.')

    def source_changed(self,_,args):
        # SourceChanged precedes document scripts, unlike NavigationCompleted.
        self.trusted=trusted_url(str(self.core.Source))

    def frame_created(self,_,args):
        def reject(_,navigation):navigation.Cancel=True
        args.Frame.NavigationStarting+=reject

    def new_window(self,_,args):
        args.Handled=True
        if self.trusted and args.IsUserInitiated:self.pool.submit(self.open_link,str(args.Uri))

    def download(self,_,args):
        args.Cancel=True
        if self.trusted:self.pool.submit(self.export_url,str(args.DownloadOperation.Uri))

    def resource(self,_,args):
        from System.IO import MemoryStream
        from System import Array,Byte
        with self.pending_lock:
            if self.pending>=32:
                args.Response=self.core.Environment.CreateWebResourceResponse(MemoryStream(Array[Byte](b'')),503,'Busy','Content-Length: 0')
                return
            self.pending+=1
        uri=str(args.Request.Uri);method=str(args.Request.Method)
        headers={}
        for key in ('range','if-range','accept'):
            if args.Request.Headers.Contains(key):headers[key]=str(args.Request.Headers.GetHeader(key))
        deferral=args.GetDeferral()
        def work():
            response=None
            try:
                path=resource_path(uri)
                if method not in ('GET','HEAD'):raise ValueError('허용하지 않은 자료 요청입니다')
                if path.startswith('/api/'):
                    response=self.engine.submit(self.engine.http(path,method,headers=headers)).result(120)
                else:response=static_response(self.frontend,path,method,headers)
            except Exception:
                logging.exception('App resource failed: %s',uri)
                response=Response(403,[('Content-Type','text/plain; charset=utf-8')])
                response.body.write('자료를 열 수 없습니다. 원본과 앱 저장 상태를 확인하세요.'.encode());response.body.flush();response.body.seek(0)
            def deliver():
                from System.IO import FileAccess,FileMode,FileOptions,FileShare,FileStream
                stream=None
                try:
                    response.body.close()
                    # shortcut: temp cleanup waits for CLR finalization, bundle an EOF-disposing Stream if long-session disk retention occurs.
                    stream=FileStream(str(response.path),FileMode.Open,FileAccess.Read,FileShare.Read|FileShare.Delete,4096,FileOptions.DeleteOnClose)
                    fields='\r\n'.join(str(key)+': '+str(value) for key,value in response.headers)
                    args.Response=self.core.Environment.CreateWebResourceResponse(stream,response.status,'OK' if response.status<400 else 'Error',fields)
                except Exception:
                    if stream:stream.Dispose()
                    response.close();logging.exception('Failed to deliver app resource')
                finally:
                    with self.pending_lock:self.pending-=1
                    deferral.Complete()
            try:self.ui(deliver)
            except Exception:
                response.close()
                with self.pending_lock:self.pending-=1
                deferral.Complete()
        self.pool.submit(work)

    def emit(self,name,value):
        if not self.ready:return False
        script='window.dispatchEvent(new CustomEvent('+json.dumps(name)+',{detail:'+json.dumps(value,ensure_ascii=False)+'}));'
        try:self.ui(lambda:self.core.ExecuteScriptAsync(script));return True
        except Exception:logging.exception('Could not publish native app state');return False

    def queue_audio(self,url):
        with self.audio_lock:self.pending_audio=url
        if self.window:
            def activate():
                from System.Windows.Forms import FormWindowState
                self.window.native.WindowState=FormWindowState.Normal
                self.window.native.Show();self.window.native.Activate()
            self.ui(activate)
        self.deliver_audio()

    def deliver_audio(self):
        with self.audio_lock:
            if not self.ready or not self.pending_audio or self.delivering_audio:return
            url=self.pending_audio;self.delivering_audio=True
        def deliver():
            try:
                clip=self.engine.submit(self.engine.clip(url)).result(10)
                if self.emit('solasi-open-audio',clip):
                    with self.audio_lock:
                        if self.pending_audio==url:self.pending_audio=None
            except Exception as error:
                with self.audio_lock:
                    if self.pending_audio==url:self.pending_audio=None
                self.show_error(str(error))
            finally:
                with self.audio_lock:
                    self.delivering_audio=False;again=self.pending_audio and self.pending_audio!=url
                if again:self.deliver_audio()
        self.pool.submit(deliver)

    def select_files(self,path):
        import webview
        audio=path.endswith('/recordings')
        types=('녹음 파일 (*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.webm;*.mp4)',) if audio else ('강의 자료 (*.pdf;*.png;*.jpg;*.jpeg;*.txt;*.md)',)
        selected=self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=True,file_types=types)
        if selected and len(selected)>64:raise ValueError('한 번에 파일 64개까지 연결할 수 있습니다')
        return selected

    def save_file(self,filename):
        import webview
        selected=self.window.create_file_dialog(webview.FileDialog.SAVE,save_filename=filename)
        return selected[0] if selected else None

    def open_link(self,url):
        try:
            if url.startswith('solasi://audio/'):self.queue_audio(url);return
            if url.startswith(ORIGIN+'/api/assets/') and urlsplit(url).path.endswith('/original'):
                path=self.engine.submit(self.engine.original(url)).result(30)
                os.startfile(str(path));return
            if url.startswith(ORIGIN+'/api/'):
                self.export_url(url);return
            parts=urlsplit(url)
            if self.trusted and parts.scheme in ('http','https') and parts.hostname and parts.netloc!='solasi.invalid':webbrowser.open(url)
        except Exception as error:self.show_error(str(error))

    def export_url(self,url):
        try:
            path=resource_path(url)
            if not path.startswith('/api/'):raise ValueError('내보내기 경로를 확인하세요')
            with self.engine.submit(self.engine.http(path)).result(120) as response:
                if not 200<=response.status<300:raise ValueError('내보낼 자료를 읽지 못했습니다')
                from email.message import Message
                disposition=Message();disposition['Content-Disposition']=dict((k.lower(),v) for k,v in response.headers).get('content-disposition','')
                filename=Path(disposition.get_filename() or 'solasi-export').name
                destination=self.save_file(filename)
                if not destination:return
                destination=Path(destination)
                with tempfile.NamedTemporaryFile(prefix='.solasi-export-',dir=destination.parent,delete=False) as output:
                    staging=Path(output.name)
                    shutil.copyfileobj(response.body,output,256*1024);output.flush();os.fsync(output.fileno())
                publish_export(staging,destination)
        except Exception as error:self.show_error(str(error))

    def prepare_close(self):
        if not self.ready:
            if self.engine.captures:raise ValueError('화면 연결을 확인하지 못했습니다. 저장된 원음을 확인한 뒤 다시 종료하세요.')
            return
        completed=threading.Event();result=[]
        script="(async()=>{try{if(!window.solasiLifecycle)throw new Error('초안 저장 연결이 없습니다');await window.solasiLifecycle.prepareClose();return {ok:true};}catch(error){return {ok:false,error:String(error.message||error)};}})()"
        self.window.evaluate_js(script,lambda value:(result.append(value),completed.set()))
        if not completed.wait(20):raise ValueError('초안 저장이 끝나지 않아 창을 유지했습니다')
        if not isinstance(result[0],dict) or not result[0].get('ok'):raise ValueError(result[0].get('error','초안 저장을 확인하지 못했습니다') if isinstance(result[0],dict) else '초안 저장을 확인하지 못했습니다')

    def resume(self):
        self.ui(lambda:self.core.ExecuteScriptAsync('window.solasiLifecycle?.resume();'))

    def on_close(self):
        if self.approved_close:
            if self.instance:self.instance.close()
            return True
        if self.closing:return False
        self.closing=True
        def close():
            try:
                if finish_close(self.engine,self.prepare_close,lambda:self.window.create_confirmation_dialog('녹음을 저장하고 종료','진행 중인 녹음을 끝내고 받은 원음을 저장한 뒤 종료하시겠습니까?'),self.resume):
                    self.approved_close=True;self.pool.shutdown(wait=False,cancel_futures=True);self.window.destroy()
            except Exception as error:
                self.resume();self.show_error(str(error))
            finally:self.closing=False
        threading.Thread(target=close,name='Solasi.close',daemon=True).start();return False

    def show_error(self,message):
        logging.error('%s',message)
        from System.Windows.Forms import MessageBox
        self.ui(lambda:MessageBox.Show(self.window.native,str(message),'Solasi'))

    def process_failed(self,_,args):
        self.ready=False
        def preserve():
            try:
                self.engine.submit(self.engine.stop_captures()).result(20)
                self.show_error('화면 프로세스가 종료되어 녹음을 마쳤습니다. 앱을 다시 열고 저장된 원음을 확인하세요.')
            except Exception:
                logging.exception('Failed to stop capture after WebView process failure')
                self.show_error('화면 프로세스가 종료되었습니다. 원음 저장 상태를 확인하지 못했습니다. 앱을 다시 열고 저장된 원음을 확인하세요.')
        threading.Thread(target=preserve,name='Solasi.recovery',daemon=True).start()


def run(data_dir,runtime_dir,frontend_dir,audio_link=None):
    if os.name!='nt':raise ValueError('Windows 11 x64에서 실행하세요')
    import webview
    from .windows_job import own_process_tree
    frontend_dir=Path(frontend_dir).resolve()
    if not (frontend_dir/'index.html').is_file():raise ValueError('앱 화면 파일이 없습니다. Windows 배포 파일을 확인하세요')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
    job=own_process_tree()
    engine=Engine(AppConfig(Path(data_dir),Path(runtime_dir),embedded=True));engine.start()
    host=Host(engine,frontend_dir)
    host.pending_audio=audio_link
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    webview.settings['ALLOW_FILE_URLS']=False
    # pywebview treats even about:blank as a local URL and starts Bottle; HTML has no URL to serve.
    window=webview.create_window('Solasi',html='<!doctype html><title>Solasi</title>',js_api=CommandAPI(host),width=1200,height=820,min_size=(600,420))
    host.bind(window)
    try:webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(Path(data_dir)/'webview'))
    finally:
        host.pool.shutdown(wait=False,cancel_futures=True)
        engine.close()
        # Keep the job handle until process exit, so descendants cannot outlive the app.
        _=job


def main():
    root=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Solasi'
    parser=argparse.ArgumentParser(description='Solasi Windows application')
    parser.add_argument('--data-dir',type=Path,default=root/'data')
    parser.add_argument('--runtime-dir',type=Path,default=root/'runtime')
    parser.add_argument('--frontend-dir',type=Path,default=Path(__file__).resolve().parent.parent/'frontend'/'dist')
    parser.add_argument('--audio-link')
    args=parser.parse_args();log=args.data_dir.parent/'logs';log.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=log/'solasi-windows.log',level=logging.INFO,encoding='utf-8')
    from .windows_instance import send_audio_link
    if args.audio_link and send_audio_link(args.data_dir,args.audio_link):return
    try:run(args.data_dir,args.runtime_dir,args.frontend_dir,args.audio_link)
    except ValueError as error:
        if args.audio_link and str(error)=='이 데이터 폴더의 앱이 이미 실행 중입니다':
            for _ in range(30):
                if send_audio_link(args.data_dir,args.audio_link):return
                time.sleep(.1)
        raise


if __name__=='__main__':main()

import hashlib,json,os,plistlib,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from lecture_study.config import AppConfig
from lecture_study.db import open_db

@unittest.skipUnless(sys.platform=='darwin' and shutil.which('xcrun'),'Mac Swift required')
class NativeUninstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.tmp=tempfile.TemporaryDirectory(prefix='solasi-uninstall-compile-');cls.addClassCleanup(cls.tmp.cleanup)
        cls.binary=Path(cls.tmp.name)/'fixture'
        fixture=Path(cls.tmp.name)/'Fixture.swift'
        fixture.write_text('''import Foundation
import Darwin
@main enum Fixture { static func main() { do {
 if CommandLine.arguments[1]=="reset-plan" { print(try RemovalPlan.prepareReset(URL(fileURLWithPath:CommandLine.arguments[2]),digest:CommandLine.arguments[3]));return }
 if CommandLine.arguments[1]=="reset-consent" { print(removalConsent(verified:CommandLine.arguments[2]=="yes",confirmed:CommandLine.arguments[3]=="yes",phrase:CommandLine.arguments[4],reset:true) ? "allowed" : "blocked");return }
 if CommandLine.arguments[1]=="optional" {
  if let (parent,name)=try optionalRemovalParent(CommandLine.arguments[2]) {
   var value=stat();let exists=fstatat(parent,name,&value,AT_SYMLINK_NOFOLLOW)==0;close(parent);print(exists ? "present" : "absent")
  } else { print("absent") };return
 }
 if CommandLine.arguments[1]=="selection" {
  print(removalSelectionSummary(["documents":true,"audio":false,"results":false]));return
 }
 if CommandLine.arguments[1]=="consent" {
  print(removalConsent(verified:CommandLine.arguments[2]=="yes",confirmed:CommandLine.arguments[3]=="yes",phrase:CommandLine.arguments[4]) ? "allowed" : "blocked");return
 }
 let plan=try RemovalPlan.load(URL(fileURLWithPath:CommandLine.arguments[2]),digest:CommandLine.arguments[3])
 try plan.validate()
 if CommandLine.arguments[1]=="execute" { try plan.remove() }
 print("ok")
 } catch { fputs("\\(error)\\n",stderr);exit(1) } } }
''')
        cls.fixture=fixture

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='solasi-uninstall-fixture-');self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name).resolve();cfg=AppConfig(self.folder/'vault',self.folder/'runtime',embedded=True);cfg.runtime_dir.mkdir()
        db=open_db(cfg.data_dir);self.addCleanup(db.close)
        bundle=self.folder/'Solasi.app';resources=bundle/'Contents/Resources';resources.mkdir(parents=True)
        (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.solasi.internal-validation','CFBundleExecutable':'Solasi'}))
        (resources/'launch.json').write_text(json.dumps({'data':str(cfg.data_dir),'runtime':str(cfg.runtime_dir)}))
        self.config=cfg;self.db=db;self.bundle=bundle
        (cfg.data_dir/'instance.lock').touch()
        self.out=self.folder/'exports';self.out.mkdir();self.retained=self.out/'기록.txt';self.retained.write_text('보존된 기록')
        self.backup=cfg.data_dir/'backup.sqlite3';self.backup.write_bytes(b'backup')

    def compile(self):
        self.assertTrue((self.root/'macos/UninstallPlan.swift').exists(),'safe native removal implementation missing')
        if not self.binary.exists():
            built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(self.root/'.local-state/swift-cache'),str(self.root/'macos/UninstallPlan.swift'),str(self.fixture),'-o',str(self.binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stderr)

    def plan(self):
        from lecture_study.uninstall_plan import build_plan
        from lecture_study.uninstall_export import regular_file,identity,json_bytes
        receipt={'format':1,'id':'a'*32,'directory':str(self.out),'directory_identity':identity(self.out),'selection':dict(documents=True,audio=False,results=False),'files':[dict(path=self.retained.name,category='documents',kind='text',**regular_file(self.retained))],'records':[dict(id='test',path=self.retained.name,category='documents')],'sources':[]}
        manifest=self.out/'보존 목록.json';manifest.write_bytes(json_bytes(receipt));receipt.update(manifest=str(manifest),manifest_sha256=regular_file(manifest)['sha256'])
        plan=build_plan(self.db,self.config,self.bundle,receipt)
        # A plain fixture must not contain real-user preferences or credentials.
        plan['targets']=[t for t in plan['targets'] if str(t['path']).startswith(str(self.folder)+'/')]
        plan['os_paths']=[]
        plan['service']='LectureStudy:'+hashlib.sha256(str(self.config.data_dir).encode()).hexdigest()[:16]
        self.db.close();self.addCleanup(lambda:None)
        path=self.folder/'plan.json';path.write_bytes(json_bytes(plan));path.chmod(0o600)
        return path,hashlib.sha256(path.read_bytes()).hexdigest()

    def run_fixture(self,mode,path,digest):
        return subprocess.run([str(self.binary),mode,str(path),digest],capture_output=True,text=True,timeout=30)

    def test_optional_missing_ancestors_are_absent_but_symlinks_are_rejected(self):
        self.compile()
        for path in [self.folder/'missing-parent/leaf',self.folder/'missing-leaf']:
            result=subprocess.run([str(self.binary),'optional',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'absent')
        (self.folder/'alias').symlink_to(self.config.runtime_dir,target_is_directory=True)
        result=subprocess.run([str(self.binary),'optional',str(self.folder/'alias/leaf')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)

    def test_final_summary_repeats_preserved_and_lost_categories(self):
        self.compile()
        result=subprocess.run([str(self.binary),'selection'],capture_output=True,text=True)
        self.assertIn('보존: 필기·문서',result.stdout);self.assertIn('미보존·삭제: 녹음, 전사·AI 결과',result.stdout)

    def test_open_model_and_replaced_app_block_before_any_record_deletion(self):
        self.compile()
        blob=self.config.runtime_dir/'ollama-models/blobs'/('sha256-'+'a'*64);blob.parent.mkdir(parents=True);blob.write_bytes(b'owned model')
        path,digest=self.plan()
        with blob.open('rb'):
            result=self.run_fixture('execute',path,digest)
            self.assertNotEqual(result.returncode,0);self.assertTrue((self.config.data_dir/'app.sqlite3').exists())
        moved=self.folder/'moved.app';self.bundle.rename(moved);self.bundle.symlink_to(moved,target_is_directory=True)
        result=self.run_fixture('execute',path,digest)
        self.assertNotEqual(result.returncode,0);self.assertTrue((self.config.data_dir/'app.sqlite3').exists())

    def test_worker_cannot_reopen_vault_during_removal(self):
        from lecture_study.config import acquire_data_lock
        marker=self.config.data_dir/'.solasi-uninstalling';marker.write_text('removal in progress')
        with self.assertRaises(ValueError):
            acquired=acquire_data_lock(self.config.data_dir)
            acquired.close()

    def test_final_consent_requires_verification_confirmation_and_exact_phrase(self):
        self.compile()
        for verified,confirmed,phrase,want in [('no','yes','솔라시 삭제','blocked'),('yes','no','솔라시 삭제','blocked'),('yes','yes','삭제','blocked'),('yes','yes','솔라시 삭제','allowed')]:
            result=subprocess.run([str(self.binary),'consent',verified,confirmed,phrase],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),want)

    def test_only_verified_authorized_execution_removes_fake_app_and_vault_files(self):
        self.compile();path,digest=self.plan()
        checked=self.run_fixture('check',path,digest);self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertTrue(self.bundle.exists());self.assertTrue((self.config.data_dir/'app.sqlite3').exists())
        denied=self.run_fixture('execute',path,'0'*64);self.assertNotEqual(denied.returncode,0)
        self.assertTrue(self.bundle.exists())
        done=self.run_fixture('execute',path,digest);self.assertEqual(done.returncode,0,done.stderr)
        self.assertFalse(self.bundle.exists());self.assertFalse((self.config.data_dir/'app.sqlite3').exists())
        self.assertEqual(self.retained.read_text(),'보존된 기록');self.assertEqual(self.backup.read_bytes(),b'backup')

    def test_corrupt_export_changed_database_symlink_and_active_lock_block_all_removal(self):
        self.compile();path,digest=self.plan()
        self.retained.write_text('corrupt')
        failed=self.run_fixture('execute',path,digest);self.assertNotEqual(failed.returncode,0);self.assertTrue(self.bundle.exists())
        self.retained.write_text('보존된 기록')
        import fcntl
        with (self.config.data_dir/'instance.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            failed=self.run_fixture('execute',path,digest);self.assertNotEqual(failed.returncode,0);self.assertTrue(self.bundle.exists())
        source=self.config.data_dir/'app.sqlite3';source.write_bytes(source.read_bytes()+b'changed')
        failed=self.run_fixture('execute',path,digest);self.assertNotEqual(failed.returncode,0);self.assertTrue(self.bundle.exists())

    def test_partial_filesystem_failure_is_reported_and_preserved_exports_survive(self):
        self.compile()
        resources=self.bundle/'Contents/Resources';resources.chmod(0o500)
        try:
            path,digest=self.plan();result=self.run_fixture('execute',path,digest)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('일부 항목',result.stderr)
            self.assertFalse((self.config.data_dir/'app.sqlite3').exists())
            self.assertEqual(self.retained.read_text(),'보존된 기록');self.assertTrue(self.backup.exists())
        finally:
            for path in self.folder.rglob('Resources'):
                if path.is_dir() and not path.is_symlink():path.chmod(0o700)

    def test_helper_waits_for_app_and_worker_exit_before_any_deletion(self):
        self.compile();path,digest=self.plan()
        helper_source=(self.root/'macos/UninstallHelper.swift').read_text().split('        let alert = NSAlert()',1)[0]
        helper_source+='        print(result); exit(success ? 0 : 1)\n    }\n}\n'
        source=self.folder/'HeadlessHelper.swift';source.write_text(helper_source);binary=self.folder/'helper'
        built=subprocess.run(['xcrun','swiftc','-module-cache-path',str(self.root/'.local-state/swift-cache'),str(self.root/'macos/UninstallPlan.swift'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=90)
        self.assertEqual(built.returncode,0,built.stderr)
        parent=subprocess.Popen(['/bin/sleep','1.5']);worker=subprocess.Popen(['/bin/sleep','1.5'],start_new_session=True)
        helper=subprocess.Popen([str(binary),'--execute',str(path),digest,str(parent.pid),str(worker.pid)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        import time
        time.sleep(.2)
        self.assertIsNone(helper.poll());self.assertTrue(self.bundle.exists());self.assertTrue((self.config.data_dir/'app.sqlite3').exists())
        parent.wait();worker.wait();out,error=helper.communicate(timeout=20)
        self.assertEqual(helper.returncode,0,error+'\n'+out)
        self.assertFalse(self.bundle.exists());self.assertEqual(self.retained.read_text(),'보존된 기록')

    def test_reset_retains_app_removes_owned_models_and_allows_fresh_vault(self):
        self.compile()
        blob=self.config.runtime_dir/'ollama-models/blobs'/('sha256-'+'b'*64);blob.parent.mkdir(parents=True);blob.write_bytes(b'owned model')
        before={str(p.relative_to(self.bundle)):p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        path,digest=self.plan()
        staged=self.run_fixture('reset-plan',path,digest);self.assertEqual(staged.returncode,0,staged.stderr)
        plan=json.loads(path.read_bytes());self.assertEqual(plan['operation'],'reset')
        self.assertEqual(plan['bytes'],sum(e['bytes'] for t in plan['targets'] if t['path']!=str(self.bundle) for e in t['entries'] if e['kind']=='file'))
        result=self.run_fixture('execute',path,staged.stdout.strip());self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,{str(p.relative_to(self.bundle)):p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()})
        self.assertFalse(blob.exists());self.assertFalse((self.config.data_dir/'app.sqlite3').exists())
        self.assertTrue(self.backup.exists());self.assertEqual(self.retained.read_text(),'보존된 기록')
        from lecture_study.config import acquire_data_lock
        with acquire_data_lock(self.config.data_dir):
            db=open_db(self.config.data_dir)
            self.assertEqual(db.execute('SELECT count(*) FROM courses').fetchone()[0],0);db.close()

    def test_reset_rejects_changed_exports_unknown_mode_and_targets_inside_app(self):
        self.compile();path,digest=self.plan()
        staged=self.run_fixture('reset-plan',path,digest);self.assertEqual(staged.returncode,0,staged.stderr)
        digest=staged.stdout.strip();self.retained.write_text('changed')
        result=self.run_fixture('execute',path,digest);self.assertNotEqual(result.returncode,0)
        self.assertTrue(self.bundle.exists());self.assertTrue((self.config.data_dir/'app.sqlite3').exists())
        self.retained.write_text('보존된 기록')
        plan=json.loads(path.read_bytes());plan['operation']='unknown'
        path.write_text(json.dumps(plan));digest=hashlib.sha256(path.read_bytes()).hexdigest()
        result=self.run_fixture('execute',path,digest);self.assertNotEqual(result.returncode,0)
        plan['operation']='reset';plan['targets'].insert(0,dict(plan['targets'][-1],path=str(self.bundle/'Contents/Resources/launch.json')))
        path.write_text(json.dumps(plan));digest=hashlib.sha256(path.read_bytes()).hexdigest()
        result=self.run_fixture('execute',path,digest);self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.config.data_dir/'app.sqlite3').exists())

    def test_reset_consent_cannot_accept_uninstall_phrase_or_unverified_data(self):
        self.compile()
        for verified,confirmed,phrase,want in [('no','yes','솔라시 초기화','blocked'),('yes','no','솔라시 초기화','blocked'),('yes','yes','솔라시 삭제','blocked'),('yes','yes','솔라시 초기화','allowed')]:
            result=subprocess.run([str(self.binary),'reset-consent',verified,confirmed,phrase],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),want)

    def test_reset_rejects_a_removal_target_containing_the_retained_app(self):
        from lecture_study.uninstall_plan import snapshot
        self.compile();path,digest=self.plan();plan=json.loads(path.read_bytes())
        container=self.config.runtime_dir/'private-app';container.mkdir()
        moved=container/'Solasi.app';self.bundle.rename(moved)
        plan['app']=str(moved);plan['targets'][-1]=snapshot(moved)
        plan['targets'].insert(0,snapshot(container));plan['operation']='reset'
        path.write_text(json.dumps(plan));digest=hashlib.sha256(path.read_bytes()).hexdigest()
        result=self.run_fixture('execute',path,digest)
        self.assertNotEqual(result.returncode,0,result.stderr)
        self.assertTrue(moved.exists());self.assertTrue((self.config.data_dir/'app.sqlite3').exists())

    def test_reset_keeps_empty_data_and_runtime_roots_for_native_app_startup(self):
        self.compile();self.backup.unlink();path,digest=self.plan()
        staged=self.run_fixture('reset-plan',path,digest);self.assertEqual(staged.returncode,0,staged.stderr)
        result=self.run_fixture('execute',path,staged.stdout.strip());self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(self.config.data_dir.is_dir(),'native launch requires data root before starting worker')
        self.assertTrue(self.config.runtime_dir.is_dir(),'native launch requires runtime root before starting worker')
        self.assertFalse((self.config.data_dir/'app.sqlite3').exists());self.assertTrue(self.bundle.exists())

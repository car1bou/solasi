"""Shared frozen entry point: GUI launcher and a console child with real stdio."""
import sys


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv)>1 and sys.argv[1] in ('material-worker','qwen-worker','model-worker'):
        from lecture_study.engine_main import main as worker
        worker()
    elif '--self-check' in sys.argv:
        import importlib.metadata,json,platform
        names=('pywebview','pythonnet','sounddevice','pypdfium2','pillow','liteparse')
        print(json.dumps({'platform':platform.system(),'architecture':platform.machine(),
                          'frozen':bool(getattr(sys,'frozen',False)),
                          'versions':{name:importlib.metadata.version(name) for name in names}}))
    else:
        from lecture_study.windows_app import main as app
        app()


if __name__=='__main__':main()

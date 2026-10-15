import asyncio
import json
import plistlib
import sys
from pathlib import Path


async def select_files(runtime_dir,kind="material"):
    if sys.platform=="darwin":
        app = Path(runtime_dir).resolve()/"FilePicker.app"
        binary = app/"Contents/MacOS/FilePicker"
        source = Path(__file__).with_name("FilePicker.swift")
        if not binary.is_file() or binary.stat().st_mtime<source.stat().st_mtime:
            binary.parent.mkdir(parents=True,exist_ok=True)
            info = {"CFBundleExecutable":"FilePicker","CFBundleIdentifier":"app.lecturestudy.filepicker",
                    "CFBundleName":"자료 연결","CFBundlePackageType":"APPL","LSUIElement":True}
            (app/"Contents/Info.plist").write_bytes(plistlib.dumps(info))
            build = await asyncio.create_subprocess_exec("xcrun","swiftc","-O",str(source),"-o",str(binary),
                                                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            if await build.wait():
                raise ValueError("파일 선택 도구를 준비할 수 없습니다")
        command = [str(binary),kind]
    else:
        command = [sys.executable,"-m","lecture_study.file_access",kind]
    process = await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout,_ = await asyncio.wait_for(process.communicate(),610)
        if process.returncode:
            raise ValueError("파일 선택 창을 열 수 없습니다")
        return [Path(path) for path in json.loads(stdout)["paths"]]
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


def main():
    import tkinter as tk
    from tkinter.filedialog import askopenfilenames
    root = tk.Tk()
    root.withdraw()
    try:
        audio = len(sys.argv)>1 and sys.argv[1]=="audio"
        types = [("녹음 파일","*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.webm *.mp4")] if audio else [
            ("강의 자료","*.pdf *.png *.jpg *.jpeg *.txt *.md")]
        paths = askopenfilenames(parent=root,title="녹음 파일 연결" if audio else "자료 연결",filetypes=types)
        print(json.dumps({"paths":list(paths)},ensure_ascii=False))
    finally:
        root.destroy()


if __name__=="__main__":
    main()

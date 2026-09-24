# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# Web 相关包（含数据文件与二进制）
for pkg in ("fastapi", "uvicorn", "jinja2", "starlette"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 应用源码（作为数据文件，运行时从磁盘导入，保持原逻辑不变）
datas += [
    (os.path.join(ROOT, "src", "web", "app.py"), "web"),
    (os.path.join(ROOT, "src", "web", "youtube.py"), "web"),
    (os.path.join(ROOT, "src", "web", "templates"), "web/templates"),
    (os.path.join(ROOT, "src", "douyin-video", "scripts", "douyin_downloader.py"), "douyin-video/scripts"),
]

# 内置 FFmpeg
datas += [
    (os.path.join(ROOT, "ffmpeg", "ffmpeg.exe"), "ffmpeg"),
    (os.path.join(ROOT, "ffmpeg", "ffprobe.exe"), "ffmpeg"),
]

# 内置 yt-dlp 与 node（YouTube 下载所需）
datas += [
    (os.path.join(ROOT, "ytdlp", "yt-dlp.exe"), "ytdlp"),
    (os.path.join(ROOT, "node", "node.exe"), "node"),
]

hiddenimports += ["requests", "ffmpeg", "pydantic", "anyio", "sniffio", "h11"]

a = Analysis(
    [os.path.join(ROOT, "src", "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "IPython",
              "notebook", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="抖音文案提取器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="抖音文案提取器",
)

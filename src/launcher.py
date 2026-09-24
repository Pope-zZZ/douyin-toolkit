#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音文案提取器 —— 启动器
双击运行：自动把内置 FFmpeg 加入 PATH、注入 API Key、启动服务并打开浏览器。
"""
import os
import sys
import time
import threading
import webbrowser


def app_base_dir():
    """定位资源目录。PyInstaller 6.x one-folder 模式下数据文件在 _MEIPASS（即 _internal）。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE = app_base_dir()

# 1) 把内置的 ffmpeg / ffprobe 放到 PATH 最前面，供 ffmpeg-python 调用
_ffmpeg_dir = os.path.join(BASE, "ffmpeg")
if os.path.isdir(_ffmpeg_dir):
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

# 2) 不内置任何 API Key：每位用户首次使用时在网页里配置自己的硅基流动 Key
#    （key 保存在各自浏览器本地，互不影响、各自计费）

# 3) 让 Python 能找到数据文件形式的 web.app 和 douyin_downloader
sys.path.insert(0, os.path.join(BASE, "douyin-video", "scripts"))
sys.path.insert(0, BASE)


def _open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open("http://localhost:8080")
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()

    from web.app import app
    import uvicorn

    print("=" * 48)
    print("  抖音文案提取器 已启动")
    print("  浏览器将自动打开 http://localhost:8080")
    print("  若未自动打开，请手动在浏览器输入该地址")
    print("  关闭本窗口即退出程序")
    print("=" * 48)

    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")

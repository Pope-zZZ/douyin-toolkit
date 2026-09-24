#!/usr/bin/env python3
"""
抖音视频文案提取器 WebUI

启动方式:
    cd douyin-mcp-server
    export API_KEY="sk-xxx"
    python web/app.py
    # 访问 http://localhost:8080
"""

import os
import re
import sys
import asyncio
from pathlib import Path
from urllib.parse import quote

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "douyin-video" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))  # 让同目录 youtube 模块可导入

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
import requests

# 导入抖音处理模块
from douyin_downloader import get_video_info, extract_text, HEADERS, DouyinProcessor
import youtube

app = FastAPI(title="抖音文案提取器", version="1.0.0")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class VideoRequest(BaseModel):
    """视频请求模型"""
    url: str
    api_key: str = ""  # 可选，从前端传入
    max_duration: int | None = None  # 可选，只提取前 N 秒音频


class VideoInfoResponse(BaseModel):
    """视频信息响应"""
    success: bool
    video_id: str = ""
    title: str = ""
    download_url: str = ""
    error: str = ""


class ExtractResponse(BaseModel):
    """文案提取响应"""
    success: bool
    video_id: str = ""
    title: str = ""
    text: str = ""
    download_url: str = ""
    error: str = ""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页面"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health_check():
    """健康检查"""
    api_key = os.getenv("API_KEY", "")
    return {
        "status": "ok",
        "api_key_configured": bool(api_key)
    }


@app.post("/api/video/info", response_model=VideoInfoResponse)
async def get_info(req: VideoRequest):
    """获取视频信息（无需 API_KEY）"""
    try:
        info = await asyncio.to_thread(get_video_info, req.url)
        return VideoInfoResponse(
            success=True,
            video_id=info["video_id"],
            title=info["title"],
            download_url=info["url"]
        )
    except Exception as e:
        return VideoInfoResponse(success=False, error=str(e))


@app.post("/api/video/extract", response_model=ExtractResponse)
async def extract_transcript(req: VideoRequest):
    """提取视频文案（需要 API_KEY）"""
    # 优先使用请求中的 API Key，其次使用环境变量
    api_key = req.api_key or os.getenv("API_KEY", "")
    if not api_key:
        return ExtractResponse(
            success=False,
            error="请先配置 API Key"
        )

    try:
        result = await asyncio.to_thread(
            extract_text, req.url, api_key=api_key, show_progress=False,
            max_duration=req.max_duration
        )
        return ExtractResponse(
            success=True,
            video_id=result["video_info"]["video_id"],
            title=result["video_info"]["title"],
            text=result["text"],
            download_url=result["video_info"]["url"]
        )
    except Exception as e:
        return ExtractResponse(success=False, error=str(e))


def _content_disposition(filename: str) -> str:
    """构造安全的 Content-Disposition 头（ASCII 回退 + RFC 5987 编码）"""
    ascii_name = re.sub(r'[^A-Za-z0-9._-]', '_', filename) or "video.mp4"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class BatchParseRequest(BaseModel):
    """批量解析请求"""
    text: str


class BatchParseResponse(BaseModel):
    """批量解析响应"""
    success: bool
    urls: list = []
    count: int = 0
    error: str = ""


@app.post("/api/video/parse-urls", response_model=BatchParseResponse)
async def parse_urls(req: BatchParseRequest):
    """从文本中解析多个视频链接"""
    urls = re.findall(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
        req.text
    )
    # 去重并保持顺序
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    return BatchParseResponse(success=True, urls=unique_urls, count=len(unique_urls))


@app.get("/api/video/download")
async def download_video(video_id: str, filename: str = "video.mp4"):
    """代理下载视频（解决跨域和请求头问题）

    只接受抖音视频 ID，由服务端自行解析出 CDN 链接，避免代理任意 URL。
    """
    if not re.fullmatch(r'\d+', video_id):
        raise HTTPException(status_code=400, detail="无效的视频 ID")

    try:
        share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
        info = await asyncio.to_thread(get_video_info, share_url)

        # 完整的请求头，模拟浏览器访问
        download_headers = {
            'User-Agent': HEADERS['User-Agent'],
            'Referer': 'https://www.douyin.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        }

        response = await asyncio.to_thread(
            requests.get, info["url"], headers=download_headers, stream=True, allow_redirects=True
        )
        response.raise_for_status()

        content_length = response.headers.get("content-length", "")

        def iter_content():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        headers = {
            "Content-Disposition": _content_disposition(filename),
        }
        if content_length:
            headers["Content-Length"] = content_length

        return StreamingResponse(
            iter_content(),
            media_type="video/mp4",
            headers=headers
        )
    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"下载失败: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class YouTubeInfoRequest(BaseModel):
    """油管视频信息请求"""
    url: str
    proxy: str = ""
    cookies: str = ""


class YouTubeExtractRequest(BaseModel):
    """油管文案提取请求"""
    url: str
    proxy: str = ""
    cookies: str = ""
    api_key: str = ""


class YouTubeDownloadRequest(BaseModel):
    """油管视频下载请求"""
    url: str
    proxy: str = ""
    cookies: str = ""
    quality: str = "best"


def _cleanup_file(path: str):
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


@app.post("/api/youtube/info")
async def youtube_info(req: YouTubeInfoRequest):
    return await asyncio.to_thread(youtube.get_info, req.url, req.proxy, req.cookies)


@app.post("/api/youtube/extract", response_model=ExtractResponse)
async def youtube_extract(req: YouTubeExtractRequest):
    info = await asyncio.to_thread(youtube.get_info, req.url, req.proxy, req.cookies)
    title = info.get("title", "") if info.get("success") else ""

    # 1) 优先用字幕
    sub = await asyncio.to_thread(youtube.extract_subtitle, req.url, req.proxy, req.cookies)
    if sub.get("success") and sub.get("text"):
        return ExtractResponse(success=True, video_id="", title=title, text=sub["text"], download_url=req.url)

    # 2) 无字幕 → 语音识别兜底
    api_key = req.api_key or os.getenv("API_KEY", "")
    if not api_key:
        return ExtractResponse(success=False, error="该视频没有可用字幕，且未配置 API Key，无法语音识别")

    audio = await asyncio.to_thread(youtube.extract_audio, req.url, req.proxy, req.cookies)
    if not audio.get("success"):
        return ExtractResponse(success=False, error=audio.get("error"))

    def _transcribe():
        processor = DouyinProcessor(api_key)
        return processor.extract_text_from_audio(Path(audio["path"]), show_progress=False)

    try:
        text = await asyncio.to_thread(_transcribe)
        Path(audio["path"]).unlink(missing_ok=True)
        return ExtractResponse(success=True, video_id="", title=title, text=text, download_url=req.url)
    except Exception as e:
        return ExtractResponse(success=False, error=str(e))


@app.get("/api/youtube/download")
async def youtube_download(background_tasks: BackgroundTasks, url: str,
                           quality: str = "best", proxy: str = "", cookies: str = ""):
    result = await asyncio.to_thread(youtube.download_video, url, proxy, cookies, quality)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "下载失败"))
    path = result["path"]
    filename = Path(path).name
    background_tasks.add_task(_cleanup_file, path)
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


def main():
    """启动服务"""
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    print(f"🚀 启动文案提取器 WebUI: http://localhost:{port}")
    print(f"📝 API_KEY 配置状态: {'已配置' if os.getenv('API_KEY') else '未配置'}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

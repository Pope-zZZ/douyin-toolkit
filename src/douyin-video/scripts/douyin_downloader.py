#!/usr/bin/env python3
"""
抖音无水印视频下载和文案提取工具

功能:
1. 从抖音分享链接获取无水印视频下载链接
2. 下载视频并提取音频
3. 使用硅基流动 API 从音频中提取文本
4. 自动保存文案到文件 (一个视频一个文件夹)
6. 批量提取用户多个视频的前 N 秒文案

环境变量:
- API_KEY: 硅基流动 API 密钥 (用于文案提取功能)

使用示例:
  # 获取下载链接 (无需 API 密钥)
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 提取文案并保存到文件 (需要 API_KEY 环境变量)
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

  # 获取用户视频列表

  # 批量提取用户前10个视频的前30秒文案
"""

import os
import re
import sys
import json
import argparse
import tempfile
import shutil
import time
from pathlib import Path
from typing import Optional
from datetime import datetime


def check_dependencies():
    """检查必要的依赖是否已安装"""
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    try:
        import ffmpeg
    except ImportError:
        missing.append("ffmpeg-python")

    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        sys.exit(1)


check_dependencies()

import requests
import ffmpeg

# 请求头，模拟移动端访问
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}

WEB_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 硅基流动 API 配置
DEFAULT_API_BASE_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"

# 表情符号正则：SenseVoice 对背景音乐/笑声等音频事件会输出 emoji（如音符/笑脸），需从文案中剥离
_EMOJI_RE = re.compile(
    "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in (
        (0x1F000, 0x1FAFF),  # 补充符号与象形文字（表情、交通、游戏符号等）
        (0x2600, 0x27BF),    # 杂项符号与装饰符号
        (0x1F1E6, 0x1F1FF),  # 国旗（区域指示符）
        (0xFE00, 0xFE0F),    # 变体选择符
    )) + chr(0x200D) + "]+",  # 零宽连接符（组合表情）
    flags=re.UNICODE,
)


def _ffmpeg_error_detail(e: Exception) -> str:
    """从 ffmpeg-python 异常中取出真实 stderr（默认 str(e) 只有笼统提示）。"""
    stderr = getattr(e, "stderr", None)
    if stderr:
        try:
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            s = str(stderr).strip()
            if s:
                return s
        except Exception:
            pass
    return str(e)


class DouyinProcessor:
    """抖音视频处理器"""

    def __init__(self, api_key: str = "", api_base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.api_base_url = api_base_url or DEFAULT_API_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.temp_dir = Path(tempfile.mkdtemp())

    def __del__(self):
        """清理临时目录"""
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def parse_share_url(self, share_text: str, max_retries: int = 5) -> dict:
        """从分享文本中提取无水印视频链接（含 Session cookie 预热与自动重试）

        抖音反爬机制：首次请求分享页时，页面虽含 window._ROUTER_DATA，
        但其中的 videoInfoRes 往往为空，服务端会同时下发 cookie；
        使用同一 Session 携带 cookie 再次请求后，才会返回完整的视频数据。
        因此这里复用 Session cookie，并在解析不到数据时自动退避重试，
        以同时应对「videoInfoRes 缺失」与「WAF JS 挑战页」两类拦截。
        """
        # 提取分享链接
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")

        session = requests.Session()
        session.headers.update(HEADERS)

        # 跟随短链重定向，保留带签名参数的完整分享页 URL（切勿丢弃 query 参数）
        response = session.get(urls[0], timeout=15)
        response.raise_for_status()
        share_url = response.url
        video_id = share_url.split("?")[0].strip("/").split("/")[-1]

        # 首次响应通常缺少 videoInfoRes，需携带 cookie 重新请求预热后重试
        info = None
        for attempt in range(max_retries):
            info = self._extract_video_info(response.text, video_id)
            if info:
                break
            if attempt == max_retries - 1:
                break
            # 命中 WAF 挑战页时退避更久，普通预热等待较短
            wait = (attempt + 1) * 3 if self._is_waf_page(response.text) else (attempt + 1)
            time.sleep(wait)
            response = session.get(share_url, timeout=15)

        if not info:
            raise ValueError(f"从HTML中解析视频信息失败（已重试 {max_retries} 次，可能被反爬拦截或视频不可用）")

        return info

    @staticmethod
    def _is_waf_page(html: str) -> bool:
        """判断是否为抖音 WAF JS 挑战页（无法直接解析，需要退避重试）"""
        if not html:
            return True
        return ("out-sha256.js" in html or "waf-jschallenge" in html
                or ("_ROUTER_DATA" not in html and len(html) < 5000))

    @staticmethod
    def _extract_video_info(html: str, video_id: str) -> Optional[dict]:
        """从分享页 HTML 中解析无水印视频信息；数据不完整时返回 None（触发重试）"""
        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", flags=re.DOTALL)
        find_res = pattern.search(html)
        if not find_res or not find_res.group(1):
            return None

        try:
            json_data = json.loads(find_res.group(1).strip())
        except (ValueError, json.JSONDecodeError):
            return None

        loader_data = json_data.get("loaderData", {})
        VIDEO_ID_PAGE_KEY = "video_(id)/page"
        NOTE_ID_PAGE_KEY = "note_(id)/page"
        page_data = loader_data.get(VIDEO_ID_PAGE_KEY) or loader_data.get(NOTE_ID_PAGE_KEY)
        if not isinstance(page_data, dict):
            return None

        # 关键：videoInfoRes 首次请求常缺失或为空，此处返回 None 以触发预热重试
        video_info_res = page_data.get("videoInfoRes")
        if not isinstance(video_info_res, dict):
            return None

        item_list = video_info_res.get("item_list") or []
        if not item_list:
            return None

        data = item_list[0]
        try:
            video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        except (KeyError, IndexError, TypeError):
            return None

        desc = (data.get("desc") or "").strip() or f"douyin_{video_id}"
        # 替换文件名中的非法字符
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)

        return {
            "url": video_url,
            "title": desc,
            "video_id": video_id
        }

    def download_video(self, video_info: dict, output_dir: Optional[Path] = None, show_progress: bool = True) -> Path:
        """下载视频"""
        if output_dir is None:
            output_dir = self.temp_dir
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{video_info['video_id']}.mp4"
        filepath = output_dir / filename

        if show_progress:
            print(f"正在下载视频: {video_info['title']}")

        response = requests.get(video_info['url'], headers=HEADERS, stream=True)
        response.raise_for_status()

        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))

        # 下载文件
        downloaded = 0
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total_size > 0:
                        progress = downloaded / total_size * 100
                        print(f"\r下载进度: {progress:.1f}%", end="", flush=True)

        if show_progress:
            print(f"\n视频下载完成: {filepath}")
        return filepath

    def extract_audio(self, video_path: Path, show_progress: bool = True, max_duration: Optional[int] = None) -> Path:
        """从视频文件中提取音频

        参数:
            video_path: 视频文件路径
            show_progress: 是否显示进度
            max_duration: 最多提取的秒数，None 表示完整音频
        """
        audio_path = video_path.with_suffix('.mp3')

        duration_msg = f"（前 {max_duration} 秒）" if max_duration else ""
        if show_progress:
            print(f"正在提取音频{duration_msg}...")
        try:
            stream = ffmpeg.input(str(video_path))
            output_kwargs = {'acodec': 'libmp3lame', 'q': 0}
            if max_duration:
                output_kwargs['t'] = max_duration
            (
                stream
                .output(str(audio_path), **output_kwargs)
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            if show_progress:
                print(f"音频提取完成: {audio_path}")
            return audio_path
        except Exception as e:
            raise Exception(f"提取音频时出错: {_ffmpeg_error_detail(e)}")

    def stream_extract_audio(self, video_url: str, video_id: str,
                              show_progress: bool = True,
                              max_duration: Optional[int] = None) -> Path:
        """直接从视频 URL 流式提取音频，不下载完整视频文件

        适用场景：视频很长（如 1 小时+）但只需要前 N 秒的文案。
        ffmpeg 边下载边解码，只拉取前 max_duration 秒的数据就停止，
        全程不生成完整视频文件，极大节省带宽和时间。

        参数:
            video_url: 视频 CDN 直链
            video_id: 视频 ID，用于临时文件命名
            show_progress: 是否显示进度
            max_duration: 最多提取的秒数

        返回:
            生成的音频文件路径
        """
        audio_path = self.temp_dir / f"{video_id}.mp3"
        duration_msg = f"前 {max_duration} 秒" if max_duration else "完整音频"
        if show_progress:
            print(f"正在流式提取音频（{duration_msg}），跳过视频下载...")
        try:
            (
                ffmpeg
                .input(
                    video_url,
                    headers={'User-Agent': HEADERS['User-Agent']},
                    **({'t': max_duration} if max_duration else {})
                )
                .output(str(audio_path), acodec='libmp3lame', q=0)
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            if show_progress:
                print(f"流式提取完成: {audio_path}")
            return audio_path
        except Exception as e:
            raise Exception(f"流式提取音频时出错: {_ffmpeg_error_detail(e)}")

    def get_audio_info(self, audio_path: Path) -> dict:
        """获取音频文件信息（时长和大小）"""
        try:
            probe = ffmpeg.probe(str(audio_path))
            duration = float(probe['format'].get('duration', 0))
            size = audio_path.stat().st_size
            return {'duration': duration, 'size': size}
        except Exception:
            return {'duration': 0, 'size': audio_path.stat().st_size}

    def split_audio(self, audio_path: Path, segment_duration: int = 600, show_progress: bool = True) -> list:
        """
        将音频分割成多个片段

        参数:
            audio_path: 音频文件路径
            segment_duration: 每段时长（秒），默认 10 分钟
            show_progress: 是否显示进度

        返回:
            分割后的音频文件路径列表
        """
        audio_info = self.get_audio_info(audio_path)
        duration = audio_info['duration']

        if duration <= segment_duration:
            return [audio_path]

        segments = []
        segment_index = 0
        current_time = 0

        if show_progress:
            total_segments = int(duration / segment_duration) + 1
            print(f"音频时长 {duration:.0f} 秒，将分割为 {total_segments} 段...")

        while current_time < duration:
            segment_path = self.temp_dir / f"segment_{segment_index}.mp3"

            try:
                (
                    ffmpeg
                    .input(str(audio_path), ss=current_time, t=segment_duration)
                    .output(str(segment_path), acodec='libmp3lame', q=0)
                    .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                )
                segments.append(segment_path)

                if show_progress:
                    print(f"  分割片段 {segment_index + 1}: {current_time:.0f}s - {min(current_time + segment_duration, duration):.0f}s")

            except Exception as e:
                raise Exception(f"分割音频片段 {segment_index} 时出错: {str(e)}")

            current_time += segment_duration
            segment_index += 1

        return segments

    @staticmethod
    def _clean_transcript(text: str) -> str:
        """清洗 SenseVoice 返回文本中的模型结构化标签

        SenseVoice 会在识别结果里插入形如 <|zh|> <|NEUTRAL|> <|Speech|> <|withitn|>
        <|BGM|> <|Laughter|> <|nospeech|> 等特殊 token，用于标记语种/情绪/音频事件，
        直接写入文案会影响阅读。这里统一剥离这些标签并压缩多余空白。
        """
        if not text:
            return text
        # 去掉所有 <|...|> 形式的模型标签
        cleaned = re.sub(r"<\|[^|>]*\|>", "", text)
        # 去掉表情符号（SenseVoice 对 BGM/笑声等音频事件输出的 emoji）
        cleaned = _EMOJI_RE.sub("", cleaned)
        # 压缩多余空白，保留正常标点
        cleaned = re.sub(r"[ \t\r\n]{2,}", " ", cleaned).strip()
        return cleaned

    def transcribe_single_audio(self, audio_path: Path) -> str:
        """转录单个音频文件"""
        files = {
            'file': (audio_path.name, open(audio_path, 'rb'), 'audio/mpeg'),
            'model': (None, self.model)
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            response = requests.post(self.api_base_url, files=files, headers=headers)
            response.raise_for_status()

            result = response.json()
            if 'text' in result:
                return self._clean_transcript(result['text'])
            else:
                return response.text

        except Exception as e:
            raise Exception(f"提取文字时出错: {str(e)}")
        finally:
            files['file'][1].close()

    def extract_text_from_audio(self, audio_path: Path, show_progress: bool = True) -> str:
        """从音频文件中提取文字（支持大文件自动分段）"""
        if not self.api_key:
            raise ValueError("未设置 API 密钥，请设置环境变量 API_KEY")

        # 检查文件大小和时长
        audio_info = self.get_audio_info(audio_path)
        max_duration = 3600  # 1 小时
        max_size = 50 * 1024 * 1024  # 50MB

        # 判断是否需要分段
        need_split = audio_info['duration'] > max_duration or audio_info['size'] > max_size

        if not need_split:
            # 文件在限制范围内，直接处理
            if show_progress:
                print("正在识别语音...")
            return self.transcribe_single_audio(audio_path)

        # 需要分段处理
        if show_progress:
            print(f"音频文件较大（时长: {audio_info['duration']:.0f}秒, 大小: {audio_info['size'] / 1024 / 1024:.1f}MB）")
            print("将自动分段处理...")

        # 分割音频
        segments = self.split_audio(audio_path, segment_duration=540, show_progress=show_progress)  # 9分钟一段，留余量

        # 逐段转录
        all_texts = []
        for i, segment_path in enumerate(segments):
            if show_progress:
                print(f"正在识别第 {i + 1}/{len(segments)} 段...")

            text = self.transcribe_single_audio(segment_path)
            all_texts.append(text)

            # 清理分段文件
            if segment_path != audio_path:
                self.cleanup_files(segment_path)

        # 合并文本
        merged_text = ''.join(all_texts)

        if show_progress:
            print(f"语音识别完成，共处理 {len(segments)} 个片段")

        return merged_text

    def cleanup_files(self, *file_paths: Path):
        """清理指定的文件"""
        for file_path in file_paths:
            if file_path.exists():
                file_path.unlink()


def get_video_info(share_link: str) -> dict:
    """获取视频信息和下载链接"""
    processor = DouyinProcessor()
    return processor.parse_share_url(share_link)


def download_video(share_link: str, output_dir: str = ".") -> Path:
    """下载视频到指定目录"""
    processor = DouyinProcessor()
    video_info = processor.parse_share_url(share_link)
    return processor.download_video(video_info, Path(output_dir))


def extract_text(share_link: str, api_key: Optional[str] = None, output_dir: Optional[str] = None,
                 save_video: bool = False, show_progress: bool = True, max_duration: Optional[int] = None) -> dict:
    """
    从视频中提取文案并保存到文件

    返回:
        dict: 包含 video_info, text, output_path 的字典
    """
    api_key = api_key or os.getenv('API_KEY') or os.getenv('DOUYIN_API_KEY')
    if not api_key:
        raise ValueError("未设置环境变量 API_KEY，请先获取硅基流动 API 密钥")

    processor = DouyinProcessor(api_key)

    if show_progress:
        print("正在解析抖音分享链接...")
    video_info = processor.parse_share_url(share_link)

    # 优化：设置了 max_duration 且不需要保存视频时，直接流式提取，不下载完整视频
    use_stream = (max_duration is not None and not save_video)
    video_path = None

    if use_stream:
        audio_path = processor.stream_extract_audio(
            video_info['url'], video_info['video_id'],
            show_progress=show_progress, max_duration=max_duration
        )
    else:
        if show_progress:
            print("正在下载视频...")
        video_path = processor.download_video(video_info, show_progress=show_progress)

        if show_progress:
            print("正在提取音频...")
        audio_path = processor.extract_audio(video_path, show_progress=show_progress, max_duration=max_duration)

    if show_progress:
        print("正在从音频中提取文本...")
    text_content = processor.extract_text_from_audio(audio_path, show_progress=show_progress)

    result = {
        "video_info": video_info,
        "text": text_content,
        "output_path": None
    }

    # 保存到文件
    if output_dir:
        output_base = Path(output_dir)
        video_folder = output_base / video_info['video_id']
        video_folder.mkdir(parents=True, exist_ok=True)

        # 保存文案为 Markdown 格式
        transcript_path = video_folder / "transcript.md"
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(f"# {video_info['title']}\n\n")
            f.write(f"| 属性 | 值 |\n")
            f.write(f"|------|----|\n")
            f.write(f"| 视频ID | `{video_info['video_id']}` |\n")
            f.write(f"| 提取时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |\n")
            f.write(f"| 下载链接 | [点击下载]({video_info['url']}) |\n\n")
            f.write(f"---\n\n")
            f.write(f"## 文案内容\n\n")
            f.write(text_content)

        result["output_path"] = str(video_folder)

        if show_progress:
            print(f"文案已保存到: {transcript_path}")

        # 保存视频 (可选)
        if save_video and video_path:
            saved_video_path = video_folder / f"{video_info['video_id']}.mp4"
            shutil.copy2(video_path, saved_video_path)
            if show_progress:
                print(f"视频已保存到: {saved_video_path}")

    # 清理临时文件
    if show_progress:
        print("正在清理临时文件...")
    cleanup_paths = [p for p in (video_path, audio_path) if p is not None]
    processor.cleanup_files(*cleanup_paths)

    return result


def batch_extract(source: str, api_key: Optional[str] = None, max_count: int = 10,
                  max_duration: Optional[int] = None, output_dir: Optional[str] = None,
                  save_video: bool = False, show_progress: bool = True) -> list:
    """
    批量提取多个视频的文案

    参数:
        source: 可以是:
            - 文本文件路径（每行一个视频分享链接）
            - 多个链接用逗号或空格分隔的字符串
        api_key: API 密钥
        max_count: 最多处理的视频数量（多个链接时取前 N 个）
        max_duration: 每个视频最多提取前 N 秒的音频
        output_dir: 输出目录（所有视频的文案合并写入该目录下的 transcripts.md）
        save_video: 是否保存视频文件（保存到 output_dir 下，文件名为 视频ID.mp4）
        show_progress: 是否显示进度

    返回:
        结果列表，每个元素包含 video_info, text, output_path(合并文件路径), error
    """
    api_key = api_key or os.getenv('API_KEY') or os.getenv('DOUYIN_API_KEY')
    if not api_key:
        raise ValueError("未设置环境变量 API_KEY，请先获取硅基流动 API 密钥")

    processor = DouyinProcessor(api_key)

    # 解析输入源，获取视频分享链接列表
    share_links = _parse_link_source(source, max_count, show_progress)

    # 逐个解析视频信息
    videos = []
    for i, link in enumerate(share_links, 1):
        if i > 1:
            time.sleep(2)  # 链接间礼貌延时，降低触发抖音反爬的概率
        try:
            if show_progress:
                print(f"[{i}/{len(share_links)}] 解析链接: {link[:60]}...")
            info = processor.parse_share_url(link)
            videos.append(info)
        except Exception as e:
            if show_progress:
                print(f"[{i}/{len(share_links)}] 解析失败: {e}")

    if not videos:
        raise ValueError("未成功解析任何视频链接")

    if show_progress:
        print(f"\n成功解析 {len(videos)}/{len(share_links)} 个视频\n")

    results = []
    total = len(videos)
    success_count = 0

    # 所有视频的文案合并写入单个 Markdown 文件，方便统一提取与总结
    output_base = Path(output_dir) if output_dir else None
    combined_path = None
    duration_note = f"（前 {max_duration} 秒）" if max_duration else ""
    if output_base:
        output_base.mkdir(parents=True, exist_ok=True)
        combined_path = output_base / "transcripts.md"
        with open(combined_path, 'w', encoding='utf-8') as f:
            f.write(f"# 抖音视频文案合集{duration_note}\n\n")
            f.write(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 视频数量：{total}\n")
            f.write(f"- 音频范围：{duration_note or '完整音频'}\n\n")
            f.write(f"---\n\n")
        if show_progress:
            print(f"文案将合并保存到: {combined_path}")

    for i, video_info in enumerate(videos, 1):
        video_path = None
        audio_path = None
        try:
            if show_progress:
                print(f"\n{'='*50}")
                print(f"[{i}/{total}] 处理视频: {video_info['title']}")
                print(f"{'='*50}")

            # 优化：有 max_duration 且不需要保存视频时，直接流式提取，跳过完整下载
            use_stream = (max_duration is not None and not save_video)

            if use_stream:
                audio_path = processor.stream_extract_audio(
                    video_info['url'], video_info['video_id'],
                    show_progress=show_progress, max_duration=max_duration
                )
            else:
                if show_progress:
                    print("正在下载视频...")
                video_path = processor.download_video(video_info, show_progress=show_progress)

                if show_progress:
                    duration_msg = f"（前 {max_duration} 秒）" if max_duration else ""
                    print(f"正在提取音频{duration_msg}...")
                audio_path = processor.extract_audio(video_path, show_progress=show_progress, max_duration=max_duration)

            if show_progress:
                print("正在识别语音...")
            text_content = processor.extract_text_from_audio(audio_path, show_progress=show_progress)

            result = {
                "video_info": video_info,
                "text": text_content,
                "output_path": None,
                "error": None
            }

            # 追加写入合并的 Markdown 文件（一个视频一个二级标题区块）
            if combined_path:
                with open(combined_path, 'a', encoding='utf-8') as f:
                    f.write(f"## {i}. {video_info['title']}\n\n")
                    f.write(f"> 视频ID：`{video_info['video_id']}`"
                            f"｜[下载链接]({video_info['url']})"
                            f"｜提取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"{text_content.strip()}\n\n")
                    f.write(f"---\n\n")

                result["output_path"] = str(combined_path)
                if show_progress:
                    print(f"文案已追加到: {combined_path}")

                if save_video and video_path:
                    saved_video_path = output_base / f"{video_info['video_id']}.mp4"
                    shutil.copy2(video_path, saved_video_path)
                    if show_progress:
                        print(f"视频已保存到: {saved_video_path}")

            success_count += 1
            results.append(result)

        except Exception as e:
            if show_progress:
                print(f"[{i}/{total}] 处理失败: {e}")
            results.append({
                "video_info": video_info,
                "text": "",
                "output_path": None,
                "error": str(e)
            })
        finally:
            for path in (video_path, audio_path):
                if path is not None and path.exists():
                    path.unlink(missing_ok=True)

    if show_progress:
        print(f"\n{'='*50}")
        print(f"批量提取完成！成功: {success_count}/{total}")
        print(f"{'='*50}")

    return results


def _parse_link_source(source: str, max_count: int, show_progress: bool) -> list:
    """解析批量输入源，返回分享链接列表

    支持三种输入形式:
    1. 文本文件路径（每行一个链接）
    2. 多个链接用逗号或换行分隔
    """
    source = source.strip()

    # 1. 检查是否为文本文件
    if os.path.isfile(source):
        if show_progress:
            print(f"从文件读取链接: {source}")
        with open(source, 'r', encoding='utf-8') as f:
            links = [line.strip() for line in f if line.strip() and line.strip().startswith('http')]
        if not links:
            raise ValueError(f"文件 {source} 中未找到有效链接（每行一个 http 链接）")
        return links[:max_count]

    # 2. 检查是否包含多个链接（逗号或换行分隔）
    if ',' in source or '\n' in source:
        links = [s.strip() for s in re.split(r'[,\n]', source) if s.strip() and 'http' in s]
        if len(links) > 1:
            return links[:max_count]

    # 3. 单个链接
    if source.startswith('http'):
        return [source]

    raise ValueError(f"无法识别的输入: {source}\n支持的格式：\n  - 视频分享链接\n  - 文本文件路径（每行一个链接）")


def main():
    parser = argparse.ArgumentParser(
        description="抖音无水印视频下载和文案提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 获取视频信息和下载链接
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 提取文案并保存到文件 (需要设置 API_KEY 环境变量)
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

  # 提取文案并同时保存视频
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output --save-video

  # 批量提取（从文件读取多个视频链接，每行一个）
  # 先把链接保存到 links.txt，然后：
  python douyin_downloader.py --link links.txt --action batch --max-duration 30 --output ./output
        """
    )

    parser.add_argument("--link", "-l", required=True, help="视频分享链接，或文本文件路径（每行一个链接）")
    parser.add_argument("--action", "-a", choices=["info", "download", "extract", "batch"],
                        default="info", help="操作类型: info/download/extract/batch(批量提取，支持 links.txt)")
    parser.add_argument("--output", "-o", default="./output", help="输出目录 (默认 ./output)")
    parser.add_argument("--api-key", "-k", help="硅基流动 API 密钥 (也可通过 API_KEY 环境变量设置)")
    parser.add_argument("--save-video", "-v", action="store_true", help="提取文案时同时保存视频")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式，减少输出")
    parser.add_argument("--max-count", "-n", type=int, default=10, help="批量模式最多处理的视频数量 (默认 10)")
    parser.add_argument("--max-duration", "-d", type=int, default=None, help="每个视频最多提取前 N 秒音频（如 30 表示前30秒）")

    args = parser.parse_args()

    try:
        if args.action == "info":
            info = get_video_info(args.link)
            print("\n" + "=" * 50)
            print("视频信息:")
            print("=" * 50)
            print(f"视频ID: {info['video_id']}")
            print(f"标题: {info['title']}")
            print(f"下载链接: {info['url']}")
            print("=" * 50)

        elif args.action == "download":
            video_path = download_video(args.link, args.output)
            print(f"\n视频已保存到: {video_path}")

        elif args.action == "extract":
            result = extract_text(
                args.link,
                args.api_key,
                output_dir=args.output,
                save_video=args.save_video,
                show_progress=not args.quiet,
                max_duration=args.max_duration
            )

            if not args.quiet:
                print("\n" + "=" * 50)
                print("提取完成!")
                print("=" * 50)
                print(f"视频ID: {result['video_info']['video_id']}")
                print(f"标题: {result['video_info']['title']}")
                if result['output_path']:
                    print(f"保存位置: {result['output_path']}")
                print("=" * 50)
                print("\n文案内容:\n")
                print(result['text'][:500] + "..." if len(result['text']) > 500 else result['text'])
                print("\n" + "=" * 50)

        elif args.action == "batch":
            results = batch_extract(
                args.link,
                api_key=args.api_key,
                max_count=args.max_count,
                max_duration=args.max_duration,
                output_dir=args.output,
                save_video=args.save_video,
                show_progress=not args.quiet
            )

            if not args.quiet:
                success = [r for r in results if not r.get("error")]
                failed = [r for r in results if r.get("error")]
                print("\n" + "=" * 50)
                print("批量处理结果汇总:")
                print("=" * 50)
                for r in success:
                    title = r['video_info']['title'][:30]
                    print(f"  ✓ {title}...")
                for r in failed:
                    title = r['video_info']['title'][:30]
                    print(f"  ✗ {title}... ({r['error']})")
                print("=" * 50)
                print(f"成功: {len(success)}, 失败: {len(failed)}")

    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

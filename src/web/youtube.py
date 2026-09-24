# -*- coding: utf-8 -*-
"""YouTube 下载与文案提取（基于 yt-dlp 命令行）。"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _base_dir() -> Path:
    """包根目录（资源所在）。冻结时 = _internal；开发时 = web/ 的上一级。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).resolve().parent.parent


def _ytdlp() -> Path:
    return _base_dir() / "ytdlp" / "yt-dlp.exe"


def _node_dir() -> Path:
    return _base_dir() / "node"


def _build_cmd(proxy: str = "", cookies: str = "") -> list:
    cmd = [str(_ytdlp())]
    if proxy:
        cmd += ["--proxy", proxy]
    if cookies and os.path.isfile(cookies):
        cmd += ["--cookies", cookies]
    cmd += ["--js-runtimes", "node"]  # YouTube 必须，node 已随包分发并在 PATH 中
    return cmd


def _run(cmd: list, timeout: int = 300):
    """运行 yt-dlp。返回 (ok, stdout, stderr)。"""
    env = os.environ.copy()
    env["PATH"] = str(_node_dir()) + os.pathsep + env.get("PATH", "")
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
        return p.returncode == 0, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return False, "", "下载超时"
    except Exception as e:
        return False, "", str(e)


def _clean_err(err: str) -> str:
    """取 stderr 最后几行作为可读错误。"""
    if not err:
        return "未知错误"
    lines = [l for l in err.strip().splitlines() if l.strip()]
    return lines[-1] if lines else err[:300]


def _quality_selector(quality: str) -> str:
    if quality == "audio":
        return "ba/b"
    if quality == "best":
        # 优先 mp4(H.264)+m4a(AAC) 合并成 mp4；4K 只有 webm 则回退
        return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    h = quality.replace("p", "")
    # 优先 mp4+m4a（合并成 mp4），回退任意（mkv/webm）
    return f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"


def get_info(url: str, proxy: str = "", cookies: str = "") -> dict:
    """获取视频信息 + 画质档位 + 可用字幕语言。"""
    cmd = _build_cmd(proxy, cookies) + ["--dump-single-json", "--no-warnings", url]
    ok, out, err = _run(cmd, timeout=120)
    if not ok:
        return {"success": False, "error": _clean_err(err)}
    try:
        data = json.loads(out)
    except Exception:
        return {"success": False, "error": "解析返回数据失败"}

    # 画质：每个高度取一个代表（优先 mp4/含视频流）
    formats = []
    seen = set()
    for f in data.get("formats", []):
        h = f.get("height") or 0
        vcodec = f.get("vcodec") or "none"
        if h <= 0 or vcodec == "none":
            continue
        if h in seen:
            continue
        seen.add(h)
        formats.append({
            "height": h,
            "ext": f.get("ext"),
            "vcodec": vcodec,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })
    formats.sort(key=lambda x: -x["height"])

    # 字幕语言（合并人工字幕与自动字幕）
    sub_langs = []
    for src in ("subtitles", "automatic_captions"):
        for lang in (data.get(src) or {}):
            if lang not in sub_langs:
                sub_langs.append(lang)

    return {
        "success": True,
        "title": data.get("title"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "uploader": data.get("uploader"),
        "webpage_url": data.get("webpage_url"),
        "formats": formats,
        "subtitles": sub_langs,
    }


def _pick_subtitle_lang(langs: list) -> str:
    """优先中文，其次英文，再次任意。"""
    zh = [l for l in langs if l.lower().startswith("zh")]
    if zh:
        return zh[0]
    en = [l for l in langs if l.lower().startswith("en")]
    if en:
        return en[0]
    return langs[0] if langs else ""


def _vtt_to_text(vtt: str) -> str:
    """VTT 字幕转纯文本。"""
    lines = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if "-->" in s or re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)  # 去内联标签
        if s:
            lines.append(s)
    # 去相邻重复行，拼接
    out = []
    prev = ""
    for l in lines:
        if l != prev:
            out.append(l)
        prev = l
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def extract_subtitle(url: str, proxy: str = "", cookies: str = "", lang: str = "") -> dict:
    """下载字幕并转纯文本。返回 {success, text, lang}。"""
    if not lang:
        lang = _pick_subtitle_lang(get_info(url, proxy, cookies).get("subtitles", []))
    if not lang:
        return {"success": False, "error": "该视频没有可用字幕"}

    tmp = Path(tempfile.mkdtemp())
    cmd = _build_cmd(proxy, cookies) + [
        "--skip-download", "--write-auto-subs", "--write-subs",
        "--sub-lang", lang, "--no-playlist",
        "-o", str(tmp / "%(id)s.%(ext)s"),
        url,
    ]
    ok, out, err = _run(cmd, timeout=180)
    if not ok:
        return {"success": False, "error": _clean_err(err)}

    vtt_files = list(tmp.glob("*.vtt"))
    if not vtt_files:
        return {"success": False, "error": "未找到字幕文件"}
    try:
        text = _vtt_to_text(vtt_files[0].read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {"success": False, "error": f"字幕解析失败: {e}"}
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
    if not text:
        return {"success": False, "error": "字幕内容为空"}
    return {"success": True, "text": text, "lang": lang}


def download_video(url: str, proxy: str = "", cookies: str = "",
                   quality: str = "best", output_dir: str = "") -> dict:
    """下载视频，返回 {success, path, error}。"""
    outdir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp())
    outdir.mkdir(parents=True, exist_ok=True)
    fmt = _quality_selector(quality)
    cmd = _build_cmd(proxy, cookies) + [
        "-f", fmt,
        "--no-playlist",
        "-o", str(outdir / "%(id)s.%(ext)s"),
        url,
    ]
    ok, out, err = _run(cmd, timeout=1800)
    if not ok:
        return {"success": False, "error": _clean_err(err)}
    files = [f for f in outdir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
    if not files:
        return {"success": False, "error": "未找到下载产物"}
    return {"success": True, "path": str(files[0])}


def extract_audio(url: str, proxy: str = "", cookies: str = "") -> dict:
    """下载音频（mp3），用于语音识别兜底。返回 {success, path, error}。"""
    outdir = Path(tempfile.mkdtemp())
    cmd = _build_cmd(proxy, cookies) + [
        "-x", "--audio-format", "mp3",
        "--no-playlist",
        "-o", str(outdir / "%(id)s.%(ext)s"),
        url,
    ]
    ok, out, err = _run(cmd, timeout=1800)
    if not ok:
        return {"success": False, "error": _clean_err(err)}
    files = [f for f in outdir.iterdir() if f.is_file() and f.suffix.lower() == ".mp3"]
    if not files:
        return {"success": False, "error": "未找到音频产物"}
    return {"success": True, "path": str(files[0])}

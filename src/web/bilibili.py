# -*- coding: utf-8 -*-
"""B 站（bilibili）下载与文案提取（基于 yt-dlp 命令行）。"""
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


def _build_cmd(cookies: str = "") -> list:
    """B 站国内直连，不需要代理；需要 cookies 才能下高画质和字幕。"""
    cmd = [str(_ytdlp())]
    if cookies and os.path.isfile(cookies):
        cmd += ["--cookies", cookies]
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
    """B 站画质档位（1080p/720p 需登录，4K 需大会员）。"""
    if quality == "audio":
        return "ba/b"
    if quality == "best":
        return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    h = quality.replace("p", "")
    return f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"


def get_info(url: str, cookies: str = "") -> dict:
    """获取视频信息 + 画质档位 + 可用字幕语言（排除弹幕）。"""
    cmd = _build_cmd(cookies) + ["--dump-single-json", "--no-warnings", "--no-playlist", url]
    ok, out, err = _run(cmd, timeout=120)
    if not ok:
        return {"success": False, "error": _clean_err(err)}
    try:
        data = json.loads(out)
    except Exception:
        return {"success": False, "error": "解析返回数据失败"}

    # 画质：每个高度取一个代表（优先含视频流）
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

    # 字幕语言：dump-json 不含字幕，用 --list-subs 单独拿（排除弹幕）
    sub_langs = _list_subtitle_langs(url, cookies)

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


def _list_subtitle_langs(url: str, cookies: str = "") -> list:
    """用 --list-subs 拿可用字幕语言（B 站 dump-json 的 subtitles 恒为空）。"""
    cmd = _build_cmd(cookies) + ["--list-subs", "--no-warnings", "--no-playlist", url]
    ok, out, err = _run(cmd, timeout=120)
    if not ok:
        return []
    langs = []
    in_table = False
    for line in out.splitlines():
        if "Language" in line and "Formats" in line:
            in_table = True
            continue
        if in_table:
            parts = line.split()
            if not parts:
                continue
            lang = parts[0]
            if lang == "danmaku":  # 弹幕不是字幕
                continue
            if lang not in langs:
                langs.append(lang)
    return langs


def _srt_to_text(srt: str) -> str:
    """SRT 字幕转纯文本。"""
    lines = []
    for line in srt.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^\d+$", s):  # 序号
            continue
        if "-->" in s:  # 时间轴
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


def _vtt_to_text(vtt: str) -> str:
    """VTT 字幕转纯文本（兜底）。"""
    lines = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if "-->" in s or re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if s:
            lines.append(s)
    out = []
    prev = ""
    for l in lines:
        if l != prev:
            out.append(l)
        prev = l
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def extract_subtitle(url: str, cookies: str = "", lang: str = "") -> dict:
    """下载字幕并转纯文本。返回 {success, text, lang}。"""
    if not lang:
        # B 站常见字幕语言（dump-json 拿不到字幕，直接列常见语言让 yt-dlp 自己挑）
        lang = "zh-CN,zh-Hans,zh,zh-Hant,ai-zh"

    tmp = Path(tempfile.mkdtemp())
    cmd = _build_cmd(cookies) + [
        "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-lang", lang, "--no-playlist",
        "-o", str(tmp / "%(id)s.%(ext)s"),
        url,
    ]
    ok, out, err = _run(cmd, timeout=180)
    if not ok:
        return {"success": False, "error": _clean_err(err)}

    # B 站字幕 yt-dlp 转成 .srt，也可能有 .vtt
    sub_files = list(tmp.glob("*.srt")) + list(tmp.glob("*.vtt"))
    if not sub_files:
        return {"success": False, "error": "该视频没有可用 CC 字幕（多数 B 站视频没有字幕，或需登录）"}
    # 优先简中 CC 字幕（zh-CN / zh-Hans），其次任意
    pick = None
    for f in sub_files:
        if "zh-cn" in f.name.lower() or "zh-hans" in f.name.lower():
            pick = f
            break
    if pick is None:
        pick = sub_files[0]
    try:
        raw = pick.read_text(encoding="utf-8", errors="replace")
        text = _srt_to_text(raw) if pick.suffix.lower() == ".srt" else _vtt_to_text(raw)
    except Exception as e:
        return {"success": False, "error": f"字幕解析失败: {e}"}
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
    if not text:
        return {"success": False, "error": "字幕内容为空"}
    m = re.search(r"\.([A-Za-z0-9-]+)\.(?:srt|vtt)$", pick.name)
    actual_lang = m.group(1) if m else lang
    return {"success": True, "text": text, "lang": actual_lang}


def download_video(url: str, cookies: str = "", quality: str = "best",
                   output_dir: str = "") -> dict:
    """下载视频，返回 {success, path, error}。"""
    outdir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp())
    outdir.mkdir(parents=True, exist_ok=True)
    fmt = _quality_selector(quality)
    cmd = _build_cmd(cookies) + [
        "-f", fmt,
        "--no-playlist",
        "-o", str(outdir / "%(id)s.%(ext)s"),
        url,
    ]
    ok, out, err = _run(cmd, timeout=1800)
    if not ok:
        return {"success": False, "error": _clean_err(err)}
    files = [f for f in outdir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".flv")]
    if not files:
        return {"success": False, "error": "未找到下载产物"}
    return {"success": True, "path": str(files[0])}


def extract_audio(url: str, cookies: str = "") -> dict:
    """下载音频（mp3），用于语音识别兜底。返回 {success, path, error}。"""
    outdir = Path(tempfile.mkdtemp())
    cmd = _build_cmd(cookies) + [
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

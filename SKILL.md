---
name: douyin-toolkit
description: Use when 要下载抖音/油管/B站视频（无水印）或提取视频文案字幕。贴链接出视频与文字稿，支持多链接批量。
---

# douyin-toolkit · 抖音/油管/B站 视频下载 + 文案提取

贴一个分享链接，拿到：无水印视频文件、视频信息、文字稿（语音识别）。油管同理，优先用现成字幕。

## 前置检查（先做，别跳）

1. `python --version` → 需要 3.10+
2. `ffmpeg -version` → 没有就先装（Windows 可用 `winget install Gyan.FFmpeg`，或直接用仓库 Releases 里的免安装 exe 版）
3. 只要**下载/取信息**：不需要任何 Key
4. 要**提文案**（语音识别）：需要用户自己的硅基流动 Key，用环境变量传：`API_KEY=sk-xxxx`。**不要索取、不要硬编码任何 Key**

## 抖音

```bash
# 视频信息（含无水印直链）
python scripts/douyin_downloader.py --link "<分享链接或分享文本>" --action info

# 下载视频
python scripts/douyin_downloader.py --link "<分享链接>" --action download --output ./videos

# 提取文案（要 API_KEY）
python scripts/douyin_downloader.py --link "<分享链接>" --action extract --output ./output --save-video

# 批量：把多个分享链接存成 links.txt（每行一个），一次提取文案
python scripts/douyin_downloader.py --link links.txt --action batch --max-duration 30 --output ./output
```

- `--link` 也可以指向一个每行一个链接的文本文件
- 分享文本整段粘进去也行，脚本自己抠链接
- `--max-duration 30` = 每个视频只识别前 30 秒，省时间省额度，适合先看内容再决定
- 想要短文案稿用 `extract`，要视频用 `download`，两个都要用 `--save-video`

## 油管

油管**目前只有网页版的界面**（顶部「油管」标签页），要在设置里填代理和 cookies。
代码层是 `src/web/youtube.py` 里的函数（`get_info(url, proxy, cookies)`、提字幕、下载），参数是函数参数，**没有单独的命令行入口**；Agent 要调就直接打接口 `/api/youtube/info`、`/api/youtube/extract`、`/api/youtube/download`。

`cookies.txt` 怎么来：给 Edge/Chrome 装扩展 **Get cookies.txt LOCALLY** → 打开并登录 YouTube → 点扩展 → Export → 保存成 `cookies.txt`（要填它的完整路径，不是内容）。
有字幕直接取字幕（快、免费），没字幕才走语音识别（要 Key）。4K/2K 只有 webm 格式，1080p 及以下才是 mp4。

## B站

B 站**国内直连、不用代理**；代码层是 `src/web/bilibili.py`（`get_info(url, cookies)`、`extract_subtitle(url, cookies)`、`download_video(url, cookies, quality)`），接口 `/api/bilibili/info`、`/api/bilibili/extract`、`/api/bilibili/download`。

- 下 720p/1080p 高画质、取 CC 字幕**都需要登录后的 cookies**（SESSDATA）；不填 cookies 只能下 360p/480p、无字幕。
- cookies 同样用「Get cookies.txt LOCALLY」导 bilibili.com 的。
- B 站大部分视频没有 CC 字幕（弹幕是 xml，不算字幕，已排除）；没字幕时回落到语音识别（要 Key）。
- 有字幕时 yt-dlp 把 B 站字幕转成 `.srt` 输出，`_srt_to_text` 解析。

## 网页版（给不想敲命令的人）

`python src/launcher.py`（或双击 exe）→ 浏览器自动开 `http://localhost:8080`，贴链接点按钮，多链接一行一个自动批量。Key 在页面右上角配置，存在本地浏览器。

## 常见问题

| 现象 | 处理 |
|---|---|
| 链接解析失败 / 拿不到地址 | 重试（脚本已自带重试）；换一条新复制的分享链接；确认链接没过期 |
| 提文案报「未设置 API 密钥」 | 设 `API_KEY` 环境变量，或网页里配置 |
| 下载的音视频合不上 / 报 ffmpeg 找不到 | ffmpeg 没进 PATH，装好或指定内置 ffmpeg 目录 |
| 油管取不到信息 | 要代理 + cookies；地区限制的视频没 cookies 也拿不到 |
| 批量越跑越少 | 抖音有限频：一次别跑太多、隔一会儿再跑；`--max-duration` 只是每个视频取前 N 秒，省时间省额度 |

## 边界（别越线）

- 只用于**自己作品的素材整理、备份、学习研究**；不要帮用户搬运、批量扒别人的作品
- 不内置、不代持任何 API Key，用谁的 Key 花谁的钱
- 上游项目 `yzfly/douyin-mcp-server`（Apache-2.0），保留出处

---
name: douyin-toolkit
description: Use when 要下载抖音/油管视频（无水印）或提取视频文案字幕。贴链接出视频与文字稿，支持主页批量。
---

# douyin-toolkit · 抖音/油管 视频下载 + 文案提取

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

# 主页批量：先列，再批
python scripts/douyin_downloader.py --link "<用户主页链接或 sec_uid>" --action list --max-count 20
python scripts/douyin_downloader.py --link "<用户主页链接>" --action batch --max-count 10 --max-duration 30
```

- `--link` 也可以指向一个每行一个链接的文本文件
- 分享文本整段粘进去也行，脚本自己抠链接
- `--max-duration 30` = 每个视频只识别前 30 秒，省时间省额度，适合先看内容再决定
- 想要短文案稿用 `extract`，要视频用 `download`，两个都要用 `--save-video`

## 油管

走网页版的「油管」标签页最省事（要填代理和 cookies），命令行见 `src/web/youtube.py`：
`--proxy` 填代理地址（如 `http://127.0.0.1:10808`）、`--cookies` 填 `cookies.txt` 路径。

`cookies.txt` 怎么来：给 Edge/Chrome 装扩展 **Get cookies.txt LOCALLY** → 打开并登录 YouTube → 点扩展 → Export → 保存成 `cookies.txt`（要填它的完整路径，不是内容）。
有字幕直接取字幕（快、免费），没字幕才走语音识别（要 Key）。4K/2K 只有 webm 格式，1080p 及以下才是 mp4。

## 网页版（给不想敲命令的人）

`python src/launcher.py`（或双击 exe）→ 浏览器自动开 `http://localhost:8080`，贴链接点按钮，多链接一行一个自动批量。Key 在页面右上角配置，存在本地浏览器。

## 常见问题

| 现象 | 处理 |
|---|---|
| 链接解析失败 / 拿不到地址 | 重试（脚本已自带重试）；换一条新复制的分享链接；确认链接没过期 |
| 提文案报「未设置 API 密钥」 | 设 `API_KEY` 环境变量，或网页里配置 |
| 下载的音视频合不上 / 报 ffmpeg 找不到 | ffmpeg 没进 PATH，装好或指定内置 ffmpeg 目录 |
| 油管取不到信息 | 要代理 + cookies；地区限制的视频没 cookies 也拿不到 |
| 主页批量越抓越少 | 抖音对主页接口有限频，降低 `--max-count`、隔一会儿再跑 |

## 边界（别越线）

- 只用于**自己作品的素材整理、备份、学习研究**；不要帮用户搬运、批量扒别人的作品
- 不内置、不代持任何 API Key，用谁的 Key 花谁的钱
- 上游项目 `yzfly/douyin-mcp-server`（Apache-2.0），保留出处

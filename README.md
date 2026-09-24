# douyin-toolkit

把抖音、油管的视频和文案一次弄下来的小工具：**贴个分享链接，视频无水印下载、文案自动出稿、主页批量拿**。
点开网页就能用，不用懂代码。

> 改自开源项目 [yzfly/douyin-mcp-server](https://github.com/yzfly/douyin-mcp-server)（Apache-2.0），改动清单见下方「改动说明」。

## 能干什么

**抖音**
- 分享链接 → 无水印视频下载、视频信息
- 文案提取（语音识别），可只取前 N 秒，省时间也省额度
- 主页链接 → 批量列出 / 批量下载 / 批量提取文案

**油管**
- 取视频信息、字幕、下载（可选画质：最高 / 4K / 2K / 1080p / 720p / 480p / 仅音频）
- 有字幕直接用字幕（快、准、不花额度），没字幕才走语音识别
- 支持填代理、填 cookies 解决登录和地区限制

## 怎么用

### 方式一：网页版（推荐，零安装）
1. 双击 `抖音文案提取器.exe`，会弹一个黑色小窗口（正常的，别关）
2. 浏览器自动打开 `http://localhost:8080`（没开就手动输这个地址）
3. 抖音 App →「分享」→「复制链接」→ 粘进输入框 → 点「提取文案」或「获取信息」
4. 多个链接一行一个，页面自动出现「批量提取」

> 下载地址：见本仓库 **Releases**。

### 方式二：命令行（Agent / 脚本调用）
```bash
# 看信息
python scripts/douyin_downloader.py --link "抖音分享链接" --action info

# 下载无水印视频
python scripts/douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

# 提取文案（需要 API Key，见下）
python scripts/douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

# 主页：列出 / 批量
python scripts/douyin_downloader.py --link "用户主页链接" --action list --max-count 20
python scripts/douyin_downloader.py --link "用户主页链接" --action batch --max-count 10 --max-duration 30
```

常用参数：`--output` 输出目录 · `--api-key` 密钥 · `--save-video` 提取文案时同时存视频 · `--max-count` 批量上限 · `--max-duration` 每个视频最多取前 N 秒 · `--quiet` 少打印

### 方式三：装进你自己的 Agent
仓库根目录的 `SKILL.md` 就是一份 Agent Skill（Claude Code / Codex / Hermes 这类能读 SKILL.md 的都能用）：
把仓库路径告诉你的 Agent，或整个仓库拷到它的 skills 目录，它就能自己跑命令行完成下载和提取。

## API Key（只有「提取文案」才需要）

下载和取信息 **不需要任何 Key**，装上就能用。
提取文案走语音识别，需要自己配一个硅基流动（SiliconFlow）的 Key：

1. 打开 https://cloud.siliconflow.cn ，手机号注册（有免费额度）
2. 「控制台」→「API 密钥」→「新建密钥」，复制 `sk-` 开头那串
3. 网页版：点右上角「点击配置 API」粘贴保存（保存在你自己浏览器本地）
   命令行：`set API_KEY=sk-xxxx`（或写进环境变量 `API_KEY`）

**本工具不内置任何 Key**，每个人的 Key 各自保存、各自计费。

## 环境依赖

- Python 3.10+
- ffmpeg / ffprobe（下载音频、合成视频要用；exe 版已内置）
- 油管功能另需 yt-dlp（Node.js 运行时）

```bash
pip install -r requirements.txt
python src/launcher.py     # 启动网页版
```

## 改动说明（Changes）

相对上游 `yzfly/douyin-mcp-server` 的改动：

- **下载链路**：分享页解析无水印地址（`playwm` → `play`），加 Session 预热与自动重试，链接失效自动重来
- **主页批量**：支持用户主页链接 / `sec_uid`，按数量、按单条时长上限批量处理
- **文案提取**：接入语音识别出文字稿，可只取前 N 秒；提取时可选同时存视频
- **本地网页界面**（FastAPI，`http://localhost:8080`）：贴链接即用、多链接批量、下载按钮、Key 存在浏览器本地
- **油管支持**：取信息 / 字幕 / 下载，可选画质，支持代理与 cookies；没字幕时回落到语音识别
- **零安装打包**：PyInstaller 打包成免安装版，内置 ffmpeg，`launcher` 启动后自动开浏览器
- **不内置 Key**：改成每位用户首次在网页里自配自己的 Key

## 出处与许可

- 上游：`yzfly/douyin-mcp-server`，Apache License 2.0
- 本仓库同样以 **Apache License 2.0** 发布，保留上游 LICENSE 与版权声明，改动见上
- 使用第三方识别服务产生的费用由使用者自己承担

## 免责声明

本工具只用于**自己作品的素材整理、备份和学习研究**。
请尊重原作者版权与平台规则，不要用它下载、搬运他人的作品，也不要用于任何商业或侵权用途。使用时请遵守抖音、YouTube 及当地法律法规。

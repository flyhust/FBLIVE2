# Live Notes — Facebook 直播本地分析工具

Windows 本地工具，输入 Facebook 直播录像链接，或导入本地音视频／逐字稿，生成带时间戳的完整逐字稿与可追溯的内容复盘。

## Vercel 网页工作台（1.1）

网页位于 https://fb-live-analyzer.vercel.app 。网页托管在 Vercel，下载、转录、分析及文件保存仍在本机。完整解压 Online 版本后，运行 `Start-Online.cmd` 自动启动并配对；旧版 EXE 不支持网页连接。详见 [线上工作台使用说明](线上工作台使用说明.md)。

Vercel 部署目录为 `web/`，不上传模型、录像、EXE、会话令牌或分析历史。源码方式可运行 `python tool.py --portal https://fb-live-analyzer.vercel.app`；在线打包使用 `build.ps1 -Online`。本地处理程序仅监听 127.0.0.1，只有指定网站来源及正确会话令牌才能调用 API。

## 本地使用

打包完成后，双击 `FB-Live-Analyzer.exe`，会自动打开本机浏览器界面。无需安装 Python，无需 API Key。源码运行方式见下文。

1. 输入 Facebook 录像链接，或导入 MP4、MP3 等本地音视频。
2. 可选导入已有 SRT、VTT、TXT、JSON 逐字稿，以及留言 CSV。
3. 点击「开始转录与分析」。本机 CPU 完成语音转录；首次使用会下载所选语音模型，以后复用。
4. 查看完整逐字稿、语言风格线索、优点、待改进之处及对应证据。
5. 导出逐字稿 TXT、SRT、JSON，以及分析报告 HTML、Markdown。HTML 报告可打印为 PDF。

所有任务、音视频、模型缓存和报告存放在程序旁的 `FB_Live_Data` 文件夹。关闭浏览器不会停止任务；点击界面的「关闭工具」结束进程。

如果浏览器没有自动打开，可查看 `FB_Live_Data/local-address.txt` 中的本机地址。程序首次解压运行库时可能需要数秒。

## 分析方式

- **本地规则初筛**：无需语言模型。按逐字稿识别教学讲解、互动邀请、促销、故事及演示语言线索，展示原文和时间戳。关键词线索不等于质量评分，建议需要复核。
- **本地 AI 复盘（可选）**：如果本机已运行 Ollama，并已有语言模型，在设置里选择模型。工具会逐块覆盖全部逐字稿，并验证每条结论引用的证据编号。文字和留言仅发送到 `127.0.0.1:11434`，不调用云端 AI。
- **交给聊天进一步分析**：点击「复制给 AI 进一步复盘」，或导出完整资料 JSON 后发到聊天，可以继续由助手分析。

本版本基于逐字稿评价内容及语言表达方式，不直接分析声调、表情、肢体和镜头。

## 完整逐字稿

本地语音识别使用 faster-whisper，默认 `small` 多语言模型，CPU int8。可改用 `base`、`tiny`、`medium`、`large-v3`。模型越大，下载量、内存和处理时间通常越高。自动识别的人名、价格、数字及混合语言请回听核对。

导入 SRT/VTT 时保留真实起止时间；纯文本没有时间戳也可分析，但不会编造时间。只有全部片段有真实起止时间时才提供 SRT 导出。

## 留言格式

CSV 内容列支持 `text`、`comment`、`message`、`留言`、`内容`；时间列支持 `timestamp`、`created_time`、`time`、`时间`、`相对时间`、`发布时间`。可选列：`id` / `comment_id`、`user_id` / `username`、`parent_id`。

留言按实际 ID 去重，保留回复关系，用户 ID 在输出里匿名化。时间支持相对秒数、HH:MM:SS、ISO 日期时间或 Unix 秒；绝对时间需要在设置中填写带时区的直播开始时间，例如 `2026-10-18T15:00:00+08:00`。录像剪掉开头时，填写裁剪秒数。

## Facebook 数据边界

仅尝试下载公开可访问、已结束的直播录像；不导入浏览器登录凭证，不绕过访问控制。部分链接会因登录、权限、地区或平台变化无法下载，可导入你已有的录像继续。

下载录像不代表取得了留言、Reactions 或分享。留言需要 CSV 补充；互动指标只展示下载器实际返回的字段。缺失值保留为缺失，不以 0 替代，不从整场总数推算每分钟曲线。互动数量不等于成交。

已用独立 EXE 完成合成语音转录、导出，以及真实 Facebook 录像 90 秒中文片段的转录验收。该实际录像全长约 2 小时 37 分，尚未完成整场转录验收，也未人工回听确认所有识别文字。详细结果见 [使用验收清单](使用验收清单.md)。

## 源码运行

需要 Python 3.12（Windows 64 位）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tool.py
```

## Windows 打包

运行 `build.ps1`，产物位于 `dist/FB-Live-Analyzer.exe`。首次构建会下载 Python 依赖；`requirements-lock.txt` 固定本次实际验证的版本，其中 PyAV 固定为 16.1.0，以匹配 faster-whisper 的音频解码接口。语音模型不打进 EXE，在首次使用时下载到本地缓存。发布时请同时附上生成的 `THIRD_PARTY_NOTICES.txt`。

## 开源组件

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：录像获取；项目源码为 Unlicense，打包组件许可需分别核对。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：MIT，本机多语言语音转录；使用 CTranslate2 和 PyAV，音频解码无需额外安装 FFmpeg 程序。
- [Ollama](https://github.com/ollama/ollama)：可选本地语义分析服务，本工具不自动安装它或下载其语言模型。
- PyInstaller：仅用于 Windows 打包；保留其运行时许可例外。

此仓库用于 private 源码备份，不包含用户直播资料、模型缓存、密钥或大型打包产物。

# 安装、依赖与参考视频

## 安装与运行

将完整 `yl-remotion-talking-head-editor` 目录放入所用 Agent 支持的 Skill 目录，保留目录结构并重新加载。具体位置由该 Agent 的说明确定，不依赖作者的工作目录或 Junction。调用 `$yl-remotion-talking-head-editor` 并提供自己的原片；新任务未选模式时，执行者先询问全自动或半自动。

此包是 Agent 执行工作流和辅助脚本集合，需要本地文件、命令运行、图像检查及实际音频理解能力。它不是一键自动剪辑软件；ASR、能量图和技术检查不能替代原声听审。

| 功能 | 依赖 |
| --- | --- |
| 脚本与技术检查 | Python 3.10+；FFmpeg、FFprobe，放入 PATH 或显式传路径 |
| 停顿能量探测 | NumPy、SciPy；输入为 16-bit 单声道 16kHz WAV |
| 转写与字词定位 | 安装者可用的 ASR 或 faster-whisper，模型由安装者选择 |
| Remotion 文字层 | Node.js、同版本 Remotion 及 React/渲染依赖、可用浏览器 |
| 字体 | 自行取得合法可用的中文字体，默认 Noto Sans SC，真实支持 700/900 字重 |
| 开拍增强 | 自行取得的官方 Kaipai SDK、requests、alibabacloud-oss-v2、当前用户自己的凭证 |

Python 依赖按实际使用安装，例如 `python -m pip install numpy scipy requests alibabacloud-oss-v2`；只做本地技术检查不需要开拍依赖。HLG 转换需要 FFmpeg 的 zscale/tonemap 滤镜；以 `ffmpeg -filters` 验证。不要为单条视频升级其他项目的依赖。

在 Skill 根目录运行脚本的 `--help` 查看接口。文档中的 `./work`、`./input` 和 `./output` 是通用项目路径示例，按当前工程替换；EDL 的相对输入路径以 EDL 所在目录解析，manifest 的相对图像路径以 manifest 所在目录解析。

## 开拍 SDK 与安全配置

分享包不包含第三方 SDK 源代码。安装者从美图开拍官方渠道取得 SDK 并遵守其许可／服务条款。包装器按 SDK 1.2.2 的接口适配：`SkillClient`、异步提交回调、`query`、`core.config.INVOKE` 和 `core.api._deep_merge_params`。其他版本先检查兼容性，再以授权短样核验，不自动下载或执行网上代码。

通过 `--sdk-dir` 或 `KAIPAI_SDK_DIR` 指定 SDK 包本身的目录，其中应有 `__init__.py`、`core/client.py` 等文件。凭证通过 `MT_AK`、`MT_SK` 注入进程，或通过 `--env-file` 指定本地凭证文件；凭证文件只有这两个键和安装者自己的值。不要将真实值写入 Skill、终端历史或分享包。

```text
python scripts/kaipai_enhance.py --task hdvideoallinone --input ./work/approved_sdr.mp4 --out ./output/kaipai_raw.mp4 --sdk-dir ./dependencies/kaipai-sdk/sdk --ffprobe ffprobe
```

上例在环境变量已配置凭证后执行。API 会上传指定素材并使用当前账户的服务额度；仅在用户授权的模式、素材和增强范围内调用。没有凭据、SDK 或可用额度时如实记录未完成，不伪称开拍增强通过。断线按原 checkpoint/task ID 续查，禁止盲目重新提交。

SDK、模型、字体、凭证、源视频、转写、checkpoint、日志和输出放在安装者的独立项目目录；这些运行数据不回写进 Skill 分发目录，也不随本包分享。

## 参考与工程复用边界

参考由当前用户提供。视觉、节奏与美颜分别核对，不把某一方面通过当成其他方面通过。没有参考时使用本 Skill 的视觉与停顿参数起步。每条重新计算时长、帧数、字幕分行、卡片时机与位置例外，不复制旧片文案、切点、标题或人物画面。

- Remotion 组件可参考 `Title.tsx`、`Captions.tsx`、`Cards.tsx` 的职责拆分，但这些名称是实现示意，本包不包含完整工程；按当前任务生成所需组件。
- 字幕禁止逐句 `fitFontSize`；整条固定字号、底部锚点和统一分行规则，少量连续镜头才允许位置例外。
- 字体载入、真实字重与预检指向同一个实际字体文件，记录内容哈希。
- 静态层缓存键覆盖字体、组件、配置、字幕和源片；依赖改变就重渲染，不凭文件存在直接复用。
- 代理仅用于布局，正式导出从原片按当前 EDL 一次合成；重排使用支持 trim/concat 的时间线。
- 独立工程中保存 EDL、完整稿、导出命令及五项验收证据。入库按当前用户指定目标和授权执行。

## 方法归属

内容、逐字稿衔接与开头诊断的方法来源于 dontbesilent 的 DBS 对应模块，具体适配见 [内容分析](content-analysis.md)。该上游采用 CC BY-NC 4.0；本成员的工作流文档保留其署名与非商业条件，自制脚本采用 MIT，准确范围见 [来源与许可](../NOTICE.md)。Remotion、美图开拍、FFmpeg 与 Noto Sans SC 为相应项目／服务名称；软件、字体、SDK 和服务按各自许可使用，不声称官方背书。

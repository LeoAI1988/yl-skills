# 本地执行合同

Python 3.10+ 与 FFmpeg/ffprobe 外部配置；转写需要已可用的 faster-whisper、模型和 NumPy，中文分词可用已有 jieba。字体、二进制、模型、个人热词及真实工程不打进 Skill。缺依赖先检查宿主现有环境，安装/下载按当前授权，不自动开收费服务或上传素材。

`course_edit.py` 的分析/计划使用标准库；渲染和验收调用安装者提供的工具。它接受**明确审核过**的剪留方案，不自动决定什么是有效演示。

```text
python -B scripts/course_edit.py scan --asr /work/source_asr.json --output /work/candidates.json
python -B scripts/course_edit.py prepare --plan /work/plan.json --ffprobe /tools/ffprobe
python -B scripts/course_edit.py render --plan /work/plan.json --ffmpeg /tools/ffmpeg --ffprobe /tools/ffprobe
python -B scripts/course_edit.py verify --plan /work/plan.json --ffmpeg /tools/ffmpeg --ffprobe /tools/ffprobe
python -B scripts/transcribe_course.py /work/analysis.wav /work/source_asr.json --hotwords /config/hotwords.json
```

方案格式见 [plan.example.json](plan.example.json)。`sources` 绑定原片路径与 SHA-256，`parts` 给出保持原顺序的保留区间和源时间字幕；一个输出可有多个源段，一个文件可被相邻课程分别使用。不同课程独立方案。候选台账需无 pending，词删除要有理由，`mute` 仅列已核定的无话操作噪声。播放声独立处理可给 `audio_source`（同长度、同时间轴的修正音频）和 `audio_sha256`，不是混合轨整段减音量。

prepare 统一到目标帧率网格并形成实际映射；render 再核原片哈希，拒绝已存在成品同名覆盖；工作目录保存 filter 脚本，避开 Windows 命令行长度限制。音频修正文件作为输入后仍需单独验证其声源处理。编码先探测能力，默认 libx264；使用 QSV 等已验证编码器时按参数选，不因厂商推断 NVENC 可用。

首次渲染若源帧率不一致/可变帧率，先在外部工程规范时间基并核验；helper 会拒绝与目标帧率不同的源。帧网格不能牺牲保留词，prepare 若检测到有效词在量化边缘被截断须调剪点。删去极短碎片前同样检查词覆盖。

verify 做完整解码、最终时长及视频流检查，输出明确的待听审/待画面审状态；不自动宣称感知质量通过。Agent 另执行对应源段抽帧和音频映射抽查、字体像素/安全区检查及音量窗口复核，将证据写在外部工程。不要重复烧录字幕或把已倍速成片再次输入全流程。

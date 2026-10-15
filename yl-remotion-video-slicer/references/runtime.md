# 参数化运行与限制

依赖：Python 3.10+（标准库）、FFmpeg/FFprobe（支持libx264及AAC）、Node.js和模板列明的Remotion/React。工具位置可通过参数指定，从个人配置读取，不能在核心中写死。依赖/Chromium下载和商业许可遵守本轮授权；已有兼容运行环境可在任务工程外复用，不向核心复制node_modules。

所有命令输出必须在Skill核心之外。示例使用当前任务目录中的相对路径：

```text
python -B scripts/slicer.py validate manifest.json
python -B scripts/slicer.py prepare manifest.json slice-v1 --ffprobe ffprobe
```

从新工程 `slice-v1/Remotion` 安装/复用依赖，启动预览：

```text
npm install
npm run start
```

需要最终MP4时，在同目录渲染静态透明层，再从Skill路径运行导出：

```text
node render-layers.mjs
python -B scripts/slicer.py export slice-v1/Remotion --ffmpeg ffmpeg --ffprobe ffprobe
python -B scripts/slicer.py verify slice-v1/Remotion --ffmpeg ffmpeg --ffprobe ffprobe
```

`scripts/slicer.py` 指Skill脚本的实际路径；从工程运行时不要误用不存在的相对脚本。所有文件参数支持空格/非ASCII路径，脚本使用参数数组而非shell字符串。输出目录、透明层目录、导出目录均拒绝覆盖。失败重试另建版本；不要删除已批准文件来绕过保护。

已有兼容Chromium可用环境变量`YL_SLICE_BROWSER`传入实际可执行文件路径，避免重复下载。未设置时Remotion可能下载其匹配浏览器，先核实安装/下载授权。行为测试支持`--browser`，不会修改用户正在使用的浏览器会话。

## 输入合同

- `source`：原片路径，相对manifest定位；仅一个源视频，CFR、方形像素、无旋转的8bit SDR。宽高与总帧数必须真实探测；脚本完整计数并核对。VFR、HDR、旋转、特殊色彩/声道需求先做显式转换映射或用专门流程，不静默套快路径。默认SDR编码保留源色彩解释，特殊色域需另行校准；模板不是色彩管理系统。
- `fps`：有理数字符串，如`30000/1001`。所有起止为整数帧，半开区间。脚本允许短于30秒/长于120秒用于测试或明确要求，内容范围由Agent判断。
- `preview_source`：可选等帧率、等帧数、等画幅的代理；用于Studio。准备前核对等时映射；正式导出始终读取source。工程public中复制预览媒体，计划磁盘空间；仅原片时会复制原片，不修改原件。
- `segments.text`：这一段实际保留的完整原话；转写必须人工回源，不填摘要。脚本生成按成片顺序的完整顺读稿，标题和解释单列。
- `title`：可不传/为null。lines保留明确分行，duration_frames控制出场。默认模板为全行同色；需要局部黄字、SVG基线或其他样式时按个人视觉规范编辑Layer后重新prepare/绑定。`font_file`真实字体外置，不捆绑；字重匹配其真实字重。
- 横版标题独立按目标画布排版；不能仅把竖版标题按高度缩小后直接使用。按用户标注确定标题区域、实际字高、安全边距和换行，长短标题同批核对。`style.title_panel`可传`rect:[x,y,w,h]`、`color`、`opacity`、`radius`添加半透明底板，底板透明度不影响文字；`line_colors`逐行设色，`title_align`控制居中。具体尺寸、字体和底板参数从个人层或本轮参考取得，不作为所有横片的强制默认。
- `masks`：源帧区间及源像素rect，多处/移动码用多个互相可解释的矩形区间。color必须不透明#RRGGBB。text为用户要求的替换文案，默认为空。静态遮挡不支持追踪算法；Agent须视觉确定区间并检查全覆盖。
- `approved_audio`：仅包装修订时指定`path`与`timeline_sha256`。先运行validate得到指纹，确认它对应被批准旧成片实际段落，不是将任意旧音轨填上当前指纹。旧AAC至少要核验起止、时长及段落；最终逐包比对，不再次编码。初次导出则按源段裁声、concat并编码AAC一次。

输入与脚本/工程模板/字体/视频字节绑定；修改后export/verify拒绝旧绑定，不自动跳过。Studio改动先同步到manifest/模板，再在新输出目录prepare。输出声明是否采用approved_audio，技术报告把听审/观点/遮盖留pending，人工完成后另写验收，不能直接把pending改成脚本自动通过。

## 交付核验补充

脚本自动：源规格、映射区间、透明层尺寸/非空、全片解码、帧数、音频起止/长度与AAC包一致。生成MP4、mapping、顺读稿、工程、播放页和技术报告。播放器通过本地HTTP服务可打开；不要改外网发布。

人工或另写核验工具：每秒源帧/成片对照、标题退场前后、遮盖边界/移动轨迹、口型与切点、所有片段听审、论述独立性、实际保留原话。需要动态字幕/动画/裁切/变速时更新所有映射与验收，静态PNG快路径不适用。长源按段寻址解码；内存不足减并发而不降低原片或偷换代理。无字幕要求时本工具不生成字幕。

行为测试：`python -B scripts/test_slicer.py --ffmpeg ffmpeg --ffprobe ffprobe`。传`--node`和`--modules`复用已兼容Remotion依赖，运行透明层与真实小视频导出测试。测试输出保存在系统临时目录，合成媒体只检验算法和工具行为，不证明真人素材质量。

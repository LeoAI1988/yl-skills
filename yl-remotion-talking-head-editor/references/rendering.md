# 从原片直接合成与静态层快路径

## 画质决策

本节“一次有损编码”指阶段 2 从原片生成剪辑版的本地合成；阶段 4 开拍模型另有服务端编码，须如实记录。API 回片已合格时，最终只无损封装原音轨，不再叠加一次本地调色编码。

先用 ffprobe 检查旋转后的有效尺寸、像素格式、色彩原色/传递函数/矩阵、帧率和时间戳。**默认保留原片有效分辨率与合理的原始帧率**：1080×1920 保留该尺寸，1440×2560 或更高原片不能因为模板/省时缩成1080。只有用户明确指定更低交付规格时才降尺寸/降帧，记录该要求。VFR以实际PTS和合理CFR处理，不把名义高帧率当作真实帧率。提升分辨率不等于恢复细节。

最终默认兼容 H.264 / yuv420p、AAC、SDR BT.709，原片直接剪切、处理和叠加文字，每个最终版本一次有损视频编码。`libx264 -crf 14 -preset medium` 是高质量起点，不是自动通过标准；记录实际参数。不能仅为导出快就切换较弱压缩参数/编码器。采用 QSV 等硬件编码前，必须用同源运动与静态小样比对细节，通过后再批量；ICQ与CRF不是同一种刻度，禁止声称ICQ16等于CRF14。不要先输出有损底片再压一次加字幕，也不要把提高码率称作修复运动模糊。

**清晰度验收目标是“相同观看条件下不弱于原片”**。有损编码不能保证数学上每个像素无损，不得用参数代替实际对照：通过EDL找同一源时刻，统一方向、显示尺寸和色彩处理，比较100%局部与正常观看尺寸的眼镜/眼睛、发丝、皮肤自然纹理、衣纹、背景字、暗部及运动边缘。若有新增模糊、涂抹、色块、细节损失或锐化白边，画质失败，回原片调参数重导出；不能只挂“高清”标签放行。增强仅在对照确实改善且不损自然细节时使用。

布局预览可以使用小代理或旧底片，正式导出必须重新指向原片。若中间件不可避免，用无损素材并记录过程；仅复制音轨或改封装不会增加视频编码代数。

**高分辨率原片要连工程一起改尺寸**：模板工程的 Composition（`Root.tsx` 的 `width/height` 与 `calculateMetadata` 返回值）、透明层 manifest 的 `width/height`，都必须跟随本条 EDL 的画布；只在 FFmpeg 侧改输出尺寸会得到尺寸不符的层。字幕与标题的字号、`maxWidth`、`strokeWidth`、容器 `bottomY/containerHeight`、`lineHeight`、标题 `centerYs` 一律按画布比例同比换算（例如 1440×2560 相对 1080×1920 为 4/3，字幕 128px 的等效字号是 170.67px、最大宽 1280px），并在渲染前用真实字体实测每行宽度，不要按比例推算。若模板把尺寸写死在组件或渲染脚本里，在本条工作目录内改正并记录，不要为迁就模板去缩小交付分辨率。

## 源片缺少色彩标签

设备有时不写 `color_primaries/color_transfer/color_space`。此时**先核实、再解释，不要盲贴标签**：

1. 先判是否 HDR：以原始色彩元数据、设备/转换记录和实际图像为依据。位深仅作线索，不能凭 8-bit 判为 SDR；错误转码会留下 8-bit HLG 或混合色彩标记。HLG/PQ/未知与混杂状态分别处理，查不到源信息时不能猜作 BT.709。
2. SDR 且分辨率在 HD 以上时，按 BT.709 矩阵、TV 范围解释是合理默认；低分辨率老素材才考虑 BT.601。把判断依据（分辨率、位深、同批次对照）写进 EDL。
3. `render-static-overlays.py` 在非 `--tone-map-hlg` 路径下会拒绝色彩标签不是 BT.709 的源片，这是保护机制，不要绕过它去直接给输出贴 `-color_primaries`。
4. 落地方式是**给元数据、不给像素**：用流复制生成带标签副本，避免为打标签先做一次有损转码。

```text
ffmpeg -i source.mp4 -c copy \
  -bsf:v hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0 \
  -tag:v hvc1 labeled_source.mp4
```

然后把 EDL 的 `source` 指向副本并重算 `sourceSha256`，原片路径与哈希另存（如 `originalSource` / `originalSourceSha256`）保持可追溯。像素未变，导出链仍只有一次有损编码。

**画质对照要看真的同帧**：对源片取样时，若结果与成片差异异常大，先排除两类假失败——一是取到了剪辑边界（playhead 与 keep 归属存在浮点歧义），二是对照脚本按「说明文字里出现 HLG」之类过宽的规则误给 SDR 源片套了色调映射。判定色调映射应匹配其确切标记（如 `arib-std-b67`），不要匹配说明文字。

HDR 必须实际转换，不能给 SDR 片子套 HLG 滤镜。导出器根据源片探测自动选择 HLG 转换或干净 SDR 通路；混杂、未知及尚未实现的 PQ 拒绝导出，不依赖总控传入的 `hdr=false`。无论普通剪切还是 hook 重排，转换都必须发生在字幕叠加前。已验证的 HLG/BT.2020 → SDR 链如下（其他 HDR 格式重新判断）：

```text
zscale=t=linear:npl=100,format=gbrpf32le,
tonemap=tonemap=hable:desat=0,
zscale=p=bt709:t=bt709:m=bt709:r=tv,format=yuv420p
```

只给输出加 BT.709 标签不等于完成 HDR 转换。检查原片与成片同一帧的肤色、天空、高光与暗部。原片走动拖影、失焦或镜头本身偏软不能靠高码率恢复。

轻增强可作为可选小样起点：

```text
eq=contrast=1.04:brightness=0.003:saturation=1.015,
unsharp=5:5:0.28:3:3:0
```

在文字叠加之前应用；不一律套用，先看对照是否自然、是否出现白边/噪声。它是画面增强，不是美颜。美颜另按视觉标准做可选小样。

## Remotion 静态层 → FFmpeg

字幕、标题和卡片无需运动时，每个不同的视觉状态仅渲染一张全画布透明 PNG，通过时段重复使用。避免为同一张静态字幕进行几十次浏览器渲染。

1. 组件使用当前项目的 config/captions；字号、字体、颜色和位置按视觉标准。字幕固定字号并预先完成一/两行排版，禁止 `fitFontSize(caption.text, ...)` 或按每页宽度缩放；少量位置例外需合并为连续镜头段。渲染前等待字体载入，实际字体文件必须支持 700/900。先核对 `cardsRequested`：未要求则cards为空，明确加卡片则全片1–3处。
2. 以所有字幕开始/结束、标题退场、卡片边界和局部字幕避让边界组成状态切分。毫秒到帧使用 `ceil(ms * fps / 1000)`，明确左闭右开，逐帧验证组件的可见性条件。
3. 每状态用 Remotion `renderStill` 渲染透明 PNG。检查 alpha 不是全不透明、尺寸与 Composition 相同、背景视频关闭。字体/组件修改后重新渲染相关图，不只看 config/captions 哈希。
4. 每版生成 manifest，覆盖 `[0, durationInFrames)` 无重叠无空洞；记录config、captions、组件代码、字体文件和PNG的hash及实际字幕布局审核。共享状态可引用同一 PNG；卡片叠在不重叠区域时可以按 RGBA 精确合并，先验证两层像素区域无冲突。通用导出器只检查PNG结构和时间线，不代替这些渲染前检查。
5. FFconcat 每张 PNG 显式 `option framerate FPS`，duration 为该状态帧数/FPS，末尾重复最后一张 file，避免默认 25fps 导致时序漂移。
6. 原片按 EDL 处理后，与文字层叠加并直接编码；固定 `-frames:v` 为 EDL 计算值。多个对照版可在同一处理链 split 后各叠一套层，每个最终版仍只编码一次。

7. 最终无损封装后核对方向和完整音轨：已旋正像素不应再带非零 Display Matrix；`-map_metadata -1`/`rotate=0` 命令存在并不证明已清除。必要时用已验证 FFmpeg 的输入覆盖 `-display_rotation:v:0 0` 对已旋正编码文件 stream-copy，再以ffprobe与实际帧验证。`-frames:v` 可能提前终止AAC复制，音轨PCM不一致时从完整edited AAC无损重新封装（不再次限帧或 `-shortest` 截断），再核查精确时长、PCM及音画同步。色彩标签缺失的修复必须建立在真实转换完成的证据上，不能给未知或HDR像素盲贴BT.709。

manifest 最小字段示意（数值只是格式示例，不是下一条的默认时长）：

```json
{
  "width": 1080, "height": 1920, "fps": 30, "durationInFrames": 60,
  "states": [
    {"startFrame": 0, "endFrame": 30, "image": "./work/overlays/state_000.png"},
    {"startFrame": 30, "endFrame": 60, "image": "./work/overlays/state_001.png"}
  ]
}
```

透明层的 PC → TV 色彩范围处理示例：

```text
[ov_input:v]scale=iw:ih:in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuva420p[ov];
[base][ov]overlay=format=yuv420:eof_action=repeat[out]
```

## 可复用导出器

`scripts/render-static-overlays.py --help` 给出实际 CLI。输入是已完成剪辑决策的 EDL、已剪好且时长匹配的 AAC 音轨（也可指向含该音轨的已批准 MP4），以及一份或多份透明层 manifest。输出路径必须是不存在的新文件。

```powershell
python scripts/render-static-overlays.py --edl "./work/EDL.json" --audio "./work/edited_audio.m4a" --variant "./work/overlays/manifest.json" "./output/video_v1.mp4" --work-dir "./work/export_v1" --ffmpeg "ffmpeg" --ffprobe "ffprobe"
```

默认由源片探测选择 HLG/SDR；`--tone-map-hlg` 保留为显式声明，仍需与真实源片相符。经小样确认需要轻增强时才增加 `--enhance-mild`。对照版再增加一个 `--variant MANIFEST OUTPUT`。不能默认开启额外画面增强。

导出器默认拒绝缩小原片有效尺寸。只有用户明确指定更低交付尺寸时才传 `--allow-downscale` 并在EDL记录该规格；该标志不是画质豁免。脚本的导出成功及技术验证只覆盖编码结构，不会认证内容精剪、原声听感、固定字幕或主观清晰度。

脚本支持 EDL 的 `source`、`width`、`height`、`fps`、`playbackRate`、`outputFrames`、`keeps[].sourceStartFrame/sourceEndFrame` 字段，keeps 必须升序且不重叠。帧坐标属于按输出fps归一化后的网格；若 `sourceFps` 与输出fps不同，显式声明 `frameGridFps=fps`，保证坐标实际匹配 `fps=frameGridFps:start_time=0`。普通SDR路径须已是BT.709；其他/未知色彩先核实并使用专用转换，不静默重贴标签。复杂重排、前置、画中画或全屏插入使用专用 trim/concat/overlay 时间线，继续遵守一次编码原则，不把不支持的数据硬塞给脚本。

预览代理、转写和字体缓存可以复用；源片、EDL、文字、字体文件或视觉组件改动都会影响渲染正确性。除非缓存键覆盖这些依赖并验证时间轴，否则不要 `--resume` 旧 PNG。安装与参考准备见 [环境与参考](approved-example.md)。

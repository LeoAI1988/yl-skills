# 科技大字封面（黄白描边、电路底纹，默认个人头像）

Create a finished 1080x1440 PNG with a source-grounded headline, an oversized dynamic text composition, and the personal portrait from the user profile or available reference assets. Use the configured default portrait directly without a separate authorization step. Omit it only when the user requests no avatar.

## Choose one input mode

### Screenshot mode

1. Inspect every supplied screenshot with the image viewer.
2. If the screenshot is narrower than 800 px or any character is uncertain, run `scripts/prepare_title_crop.py` and inspect the enlarged crop.
3. Transcribe only the intended headline. Ignore playback controls, captions, account names, counts, and app UI.
4. Preserve the wording and punctuation. Normalize product letter case only when unambiguous, such as `deepseek` to `DeepSeek`.

### Script mode

1. Read the complete supplied narration or copy.
2. If the user already specifies a title, preserve it as the primary title.
3. Otherwise extract one concise hook containing the core object plus the strongest source-backed conflict, result, or mechanism.
4. Use few words and large, contrasting sizes. Prefer three semantic lines; use four when the phrasing and composition benefit. Short copy may use one or two lines. Never add words merely to reach a line count. Count every supplement in the four-line total limit.

### Video mode

1. Run `scripts/prepare_video_input.py` to create a local transcript, metadata manifest, and representative frames.
2. Read the complete transcript and inspect at least three frames, even when the video already displays a headline. Check whether that headline expresses the core point; short wording alone is not a reason to add text. Correct obvious transcription errors in proper nouns by cross-checking speech, captions, and context.
3. Extract the primary hook with the same rules as Script mode. Treat the transcript as evidence, not publication-ready wording.
4. Before rendering, record the single core judgment and its exact transcript evidence. Record evidence for a supplement only if it is needed to understand that judgment.
5. Prefer three semantic lines, using four when needed for good phrasing and composition. The goal is few words set large, not a particular line count; one or two short lines remain valid. Use around 3–6 Chinese characters per line only as a soft guide. Do not force a mechanism/result/consequence onto the cover, add filler, or shrink key words to keep two lines. Keep all lines left aligned and vary sizes meaningfully. Preserve explicitly supplied wording unless the user authorizes its reduction.
6. Keep video, transcript, and frames as private inputs or intermediate evidence. Deliver only the requested PNG; keep the process manifest in the external private working directory unless requested.

Prepare one video with:

```powershell
python -X utf8 scripts/prepare_video_input.py `
  --video "../cover-work/source.mp4" `
  --out-dir "../cover-work/video-name" `
  --model small
```

Use `--reuse-transcript` when the same-name TXT transcript already exists in the output directory.

## Plan, render and verify

先读 [通用构图规范](style-spec.md)。本模式总是电路纹理、黄白外描边、水平共左边。三行为主，按断句和构图可用四行；少字、大字、大小组合比行数更重要；独立字号、完整头脸与清晰字形保留，根据文案调整人像。不设文字必须占满画面一定比例的要求，留白不靠补字填满。黄色仅选1—3个核心词，约不超过总字数三分之一。不加黄底块，不旋转，不回退纯黑。

除包内固定母版外，所有用户输入和输出放在Skill目录外。示例文字只示范参数，不能代替本次原文：

```powershell
python -X utf8 scripts/render_bold_cover.py `
  --title "从想法|到作品" `
  --yellow-terms "作品" `
  --line-gap 40 `
  --out "../cover-work/final/cover.png" `
  --manifest-out "../cover-work/private/cover.json"
```

默认背景直接读取本包成熟电路母版并校验文件哈希，默认黄色强调模式、水平左对齐、9px黑色外描边。`--background`只接受成熟母版的字节相同副本；不能传入另一张看起来相似的电路图。`--line-widths`用于逐行宽度；`--line-gap`用于避免字面相碰。`--line-angles`和`--boxed-terms`属于旧参数，本模式会拒绝非空值。用户明确只要白字时可用`--accent none`，仍保留科技纹理、外描边、水平左对齐；记录这项用户例外。

必要的补充文字仍单独传 `--supplement`，并计入总行数；主标题已表达清楚就不传。短标题正常校验，不需要额外豁免参数；`--allow-sparse-headline`仅兼容旧命令，不再触发凑字或四行门槛。

默认读取个人配置的头像，传入 `--avatar` 和 `--portrait-label`，不再单独询问授权。人像明显偏右下、可见范围约占右下四分之一多一点；默认 `--avatar-scale 0.52 --avatar-x-shift 0.14 --avatar-y-shift 0.02`，按实际抠图微调，不能居中或满版大头。文字少而大、字号层次明显，长句语义拆行而非缩小；`--title-top`默认190px，让顶端留白。默认不附任何人的身份素材。

```powershell
python -X utf8 scripts/validate_bold_cover.py `
  --image "../cover-work/final/cover.png" `
  --manifest "../cover-work/private/cover.json" `
  --source-mode script --check-line-overlap `
  --expected-primary-title "从想法到作品" `
  --expected-supplement ""
```

上例两行共六字也可独立交付，不额外添加说明行。通常按自然断句排成三行，构图更适合时四行也可；不为增加行数添加副标题。

叠加人像时再运行 `scripts/check_portrait_overlap.py --manifest "../cover-work/private/cover.json" --per-char`。逐字目标遮挡≤25%，≥50%失败。全部几何检测之后，必须查看全尺寸与270×360缩略图，按通用规范的六项验收检查背景、配色、描边、对齐、人像和原文；不以脚本PASS代替实际看图。每次修订使用新文件名，保留旧交付。

## Asset refresh

The approved text-free circuit master is bundled and hash-locked. Use that exact asset for normal runs. Do not regenerate it for a new task or conversation. Portraits and fonts remain external. If the user asks for a new portrait, a relevant public figure, or a new background:

1. Use an available image-generation tool when the user requests an asset generation or edit. For the user, use approved identity references; for a public figure, generate a recognizable editorial portrait only when the person is source-relevant.
2. Generate the portrait on a flat removable chroma-key background and remove it to real alpha. Require no shadow, halo, text, logo, or watermark.
   - Always verify the chroma background programmatically before cutting (corner pixels + greenness `g - max(r,b)` histogram). Generations frequently return a dark olive-gradient background instead of flat chroma; fix that with one image-to-image pass that keeps the person unchanged and forces a flat uniform `#00FF00` background, then verify corners again.
   - Before flooding, diagnose where dark pixels live (band histogram). If dark pixels cluster in the center/bottom-center bands while all non-bottom borders are pure green, the dark mass IS the person's clothing — skip luminance flood entirely. Use pure greenness removal (`gn > 34` transparent, `16-34` partial with despill), then keep only the largest alpha connected component (drop stray speckles), crop, and feather. Luminance-based border floods are only safe when dark pixels hug the borders as vignette while the person stays bright-edged; they will eat a dark-sweater subject that touches the bottom border.
3. Generate portrait and background separately. Preserve identity and inspect the portrait edge before selecting it.
4. Save a versioned portrait and pass it through `--avatar`. A requested background redesign requires an explicitly named new template version and matching validation; do not pass an unreviewed substitute through `--background`. do not overwrite any previously approved asset silently. Public-figure portrait frames hug the person tightly, so the head can clip at the canvas edge — the checker's automatic head-clip scan flags it (a clipped NARROW band in the top half of the person = head cut; wide shoulder bands overflowing is intended corner anchoring).
5. Exaggerated gesture poses (raised arm, outstretched hand) are much wider than chest-up portraits and overlap far more headline area. Expect to drop `--avatar-scale` to roughly 0.62 and raise `--avatar-x-shift`; inspect each character instead of relying on a per-line average; use the approximate report to locate issues and target at most 25% coverage.

Use [asset-prompts.md](asset-prompts.md) as the starting prompt set for an approved asset refresh.



Run the commands from the Skill directory, but place all inputs, manifests and output folders outside that directory. The examples use ../cover-work only as a placeholder for an external working directory. Only when the user explicitly requests white-only text, pass --accent none and omit --yellow-terms; the circuit background and outward outline remain mandatory. Use --manifest-out to keep process metadata outside the final PNG delivery folder; pass the same file via --manifest to validators/checkers.


## 指定断句与大字构图

用户指定分行时保持原字序与标点，不为默认三行改写；短字、单字或AI可成为独立大行。三行为主、四行允许，实际语义及构图优先；少字不等于留一片未利用的标题区，也不能每行强行拉成等宽。长上行可接近可用全宽，短下行可以在人物左侧撑大，所有行可见左边对齐。字形按字体自然比例，不横向拉伸。

自动排版是起点，不能让整组缩小抵消有意的字号层次。需要精确控制时传`--line-layout`，指向核心外JSON数组，每行一项，例如`[{"fontSize":240,"top":170},{"fontSize":320,"top":490},{"fontSize":200,"top":900}]`。fontSize为102–640，top为含外描边与阴影的裁后可见上沿；数量必须对应实际分行。此模式不做整组缩小，过宽、越界或行框重叠直接失败，调整断句、字号与位置后重试。参数只是示意，不自动套用这些字号。

清单逐行记录actualBounds和人像实际visibleBounds、按文字墨迹统计portraitOverlapRatio；行级检查不能代替逐字检查及完整头脸目视。人像维持右下偏右、适当小，必要时小幅左移。大字优先使用人物之外的可用区域，不扩大人物填空。

背景核验排除这些实际文字/人像边界，检查剩余至少12%画布与成熟背景母版相符。不能固定要求左下角永远空白；不能放宽成只核背景文件名或整图色彩数。真实擦掉露出背景仍须失败。边界、字形、错别字、人物遮挡仍需看完整图及缩略图，脚本通过不等于好看。

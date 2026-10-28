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
4. Add a short supporting hook only when the primary title is too sparse to create a strong composition. Do not introduce facts absent from the script.

### Video mode

1. Run `scripts/prepare_video_input.py` to create a local transcript, metadata manifest, and representative frames.
2. Read the complete transcript and inspect at least three frames. Do this even when the video already displays a headline; the visible headline may be only the primary hook and may be too sparse for the finished cover. Correct obvious transcription errors in proper nouns by cross-checking speech, captions, and context.
3. Extract the primary hook with the same rules as Script mode. Treat the transcript as evidence, not publication-ready wording.
4. Before rendering, write a compact content brief containing the preserved primary hook, one source-grounded mechanism/result/consequence, and the exact transcript evidence for that supplement.
5. Apply the short-title gate: when the primary hook has 12 or fewer visible alphanumeric/CJK characters, or cannot support at least four meaningful lines, add a source-grounded supplement by default. Target roughly 16-26 total visible characters across 4-5 lines. Never compensate for missing information only by enlarging or repeatedly splitting a sparse title. Skip the supplement only when the user explicitly requests the short wording alone or the source contains no defensible additional claim.
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

先读 [通用构图规范](style-spec.md)。本模式总是电路纹理、黄白外描边、水平共左边。保留3—5行、独立字号、完整头脸与文字轮廓；根据文案调整人像，不能机械固定人物大小。黄色仅选1—3个核心词，约不超过总字数三分之一。不加黄底块，不旋转，不回退纯黑。

除包内固定母版外，所有用户输入和输出放在Skill目录外。示例文字只示范参数，不能代替本次原文：

```powershell
python -X utf8 scripts/render_bold_cover.py `
  --title "从想法|到作品" `
  --supplement "清晰表达|立即行动" `
  --yellow-terms "到作品" `
  --line-gap 40 `
  --out "../cover-work/final/cover.png" `
  --manifest-out "../cover-work/private/cover.json"
```

默认背景直接读取本包成熟电路母版并校验文件哈希，默认黄色强调模式、水平左对齐、9px黑色外描边。`--background`只接受成熟母版的字节相同副本；不能传入另一张看起来相似的电路图。`--line-widths`用于逐行宽度；`--line-gap`用于避免字面相碰。`--line-angles`和`--boxed-terms`属于旧参数，本模式会拒绝非空值。用户明确只要白字时可用`--accent none`，仍保留科技纹理、外描边、水平左对齐；记录这项用户例外。

补充文字必须单独传 `--supplement`。用户提供短句或明确删字时不强加补充；校验器相应使用 `--allow-sparse-headline` 并记录用户依据。

默认读取个人配置的头像，传入 `--avatar` 和 `--portrait-label`，不再单独询问授权，可按构图调 `--avatar-scale`、`--avatar-x-shift`、`--avatar-y-shift`。默认不附任何人的身份素材。

```powershell
python -X utf8 scripts/validate_bold_cover.py `
  --image "../cover-work/final/cover.png" `
  --manifest "../cover-work/private/cover.json" `
  --source-mode script --allow-sparse-headline --check-line-overlap `
  --expected-primary-title "从想法到作品" `
  --expected-supplement "清晰表达立即行动"
```

`--allow-sparse-headline`仅对用户明确短句有效，上述示例是假定用户已指定这四行。正常视频输入仍执行前述补充门槛。

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


# 半透明原帧封面（不叠加头像）

Create a finished 1080x1440 PNG from a real source frame. Keep the style quiet: recognizable footage, one uniform dark veil, and a few forceful words in centered white serif type.

## Prepare video evidence

For a video input, create private working evidence:

```powershell
python -X utf8 scripts/prepare_video_input.py `
  --video "../cover-work/video.mp4" `
  --out-dir "../cover-work/private-work" `
  --model small
```

Read the complete transcript and inspect the opening frame plus at least three representative frames. Correct proper nouns by cross-checking speech, burned-in captions, and context. Treat any existing on-video title as evidence, not automatically as the final cover title.

When a transcript already exists in the work directory, pass `--reuse-transcript`.

## Choose the title

1. Express one decisive, source-grounded judgment. Do not summarize the whole video.
2. Target 6-10 visible Chinese/alphanumeric characters and keep the default maximum at 12.
3. Use two lines by default, normally 3-6 visible characters per line. Use a third line only when a proper noun or semantic unit cannot stay intact otherwise.
4. Prefer a compact setup-and-verdict or object-and-conflict structure, such as `跟风做内容|死路一条` or `观众是人|不是数据`.
5. Preserve the wording of a user-supplied title. When punctuation only marks the place of a line break, let the line break replace it visually.
6. Use `|` to mark deliberate line breaks.
7. Do not add an explanatory supplement merely to fill space. Do not transfer the dense black-yellow-cover habit of using extra words as layout blocks; the empty space is part of this style.
8. Do not add unsupported claims, decorative English, episode numbers, quotation marks, or a subtitle.

## Choose the frame

1. Prefer an open-eyed, recognizable expression with low motion blur and enough facial context to read at thumbnail size.
2. Prefer frames without source-app UI, subtitles, stickers, or an existing headline. Inspect the exact first frame and frames around edit boundaries; animated overlays often leave a brief clean frame there.
3. If graphics are genuinely permanent, crop away the busiest band. For a 9:16 source going to 3:4, use `--crop-y 1` to favor the lower part of the source. Add a restrained `--zoom 1.05` to `1.12` only when the bottom crop still leaves a thin strip of the old top graphic.
4. Let a close talking-head crop remain natural. Do not synthesize a replacement face or background for this style.

## Apply the style

- Canvas: 1080x1440 PNG.
- Image: source frame cover-cropped to the canvas; never stretch it.
- Overlay: uniform black over the full canvas at 0.48-0.62 opacity; start at 0.54.
- Type: Source Han Serif SC Heavy, centered, white `#F7F7F5`.
- Layout: 2 lines by default, 3 only when semantically necessary; large and evenly spaced, centered near the visual middle.
- Safe area: at least 70 px left/right and 80 px top/bottom.
- Prohibit colored highlights, boxes, cutout portraits, drop-in backgrounds, borders, logos, like counts, play controls, platform UI, and decorative marks.

If old burned-in text remains visually competitive, first change the crop, then choose another frame, then raise opacity slightly. Do not exceed 0.68 merely to hide source graphics; choose a better source frame instead.

## Render

Use either an image or a video. For a video, specify the chosen timestamp:

```powershell
python -X utf8 scripts/render_translucent_cover.py `
  --source "../cover-work/video.mp4" `
  --source-time 42.6 `
  --title "跟风做内容|死路一条" `
  --crop-y 1 `
  --zoom 1.08 `
  --opacity 0.56 `
  --out "../cover-work/最终封面.png" `
  --manifest-out "../cover-work/private-work/最终封面.json"
```

`--crop-x` and `--crop-y` accept values from `0` to `1`: `0` favors the left/top, `0.5` centers, and `1` favors the right/bottom. `--zoom` must stay between `1` and `1.25`; keep it at `1` unless a persistent edge graphic must be cropped away. Use `--font-size` or `--title-y` only for a targeted visual correction. Use `--allow-long-title` only when the user explicitly requires wording longer than this style's 12-character default gate.

The final public/output folder should contain only the requested PNG unless the user explicitly asks for process files. Keep transcript, frames, thumbnails, and the JSON manifest in the private work directory.

## Validate and inspect

```powershell
python -X utf8 scripts/validate_translucent_cover.py `
  --image "../cover-work/最终封面.png" `
  --manifest "../cover-work/private-work/最终封面.json" `
  --expected-title "跟风做内容死路一条" `
  --thumbnail "../cover-work/private-work/最终封面-thumb.png"
```

Inspect both the full-size image and the 270x360 thumbnail. Verify exact title text, readable white type, a recognizable face, sufficient darkening, no stretching, and no competing burned-in title. Make one targeted adjustment at a time and keep earlier delivered versions unchanged.

No additional portrait/cutout avatar is allowed in this mode. A person naturally present in the original video frame may remain. Keep all working data outside the installed Skill directory. Paths shown above stand for the installer-selected external working directory.

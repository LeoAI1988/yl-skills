# 黑底白字大字封面（可选黄字与头像）

Create a finished 1080x1440 PNG with a source-grounded headline, an oversized dynamic text composition, and, only when requested and supplied, a relevant recognizable portrait.

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

## Plan the headline

1. Keep the primary hook punchy and readable. Use a source-backed supplement when it adds a missing mechanism, result, or consequence; require one for a sparse script/video hook under the short-title gate above.
2. Choose 3-5 compact lines with `|`. Keep semantic phrases together, but favor short lines that can become large graphic blocks.
3. Let the text occupy about 65%-75% of the canvas height. Use deliberately varied line sizes, typically 180-320 px.
4. Default to white text without boxed or yellow terms. If the user chooses yellow accents, pick one short boxed term and up to two yellow terms. Prefer the core product, person, organization, or conflict phrase.
5. Apply subtle per-line rotations, normally within 0.5-2.5 degrees. Do not tilt every line in the same direction.
6. Fill the top as part of the composition. If the first line is short or narrow, rebreak the hook or use a wide boxed warning phrase instead of leaving a detached empty band.
7. Size the portrait after arranging the headline. Use a larger portrait for sparse or four-line layouts and a smaller portrait for dense five-line layouts; never reuse one fixed portrait size mechanically.
8. Let the foreground portrait overlap the lower-right edge of one or two lines, but keep the full head readable by default and do not solve crowding by pushing the face out of frame. Target no more than about 25% portrait coverage of any single character and never cover 50% or more of a character's visible glyph area. If overlap is too heavy, rebreak the headline first, then move the portrait, then reduce its scale. Keep the eyes, core noun, and decisive claim readable, and judge text plus portrait as one visual silhouette rather than two separate columns.
9. Choose the portrait subject deliberately. Only add a portrait when the user asks for one and supplies an approved asset; use a clearly relevant public figure when that person is central to the source or hook. Do not insert an unrelated celebrity merely for attention.
10. Check the title silhouette before rendering. Prefer a filled rectangle, stepped block, or balanced top-heavy shape; reject an accidental narrow triangle, isolated short line, or large dead zone. If the content is too sparse to form a complete silhouette, return to the source and strengthen the supplement instead of stretching the typography.

Read [style-spec.md](style-spec.md) before changing the layout, palette, assets, or output ratio.

## Render

The renderer generates a plain dark background and uses white text by default. No portraits or backgrounds are bundled. Pass --background for a licensed background and --avatar only for a user-supplied approved portrait. Portrait rules below apply only when an avatar is used.

```powershell
python -X utf8 scripts/render_bold_cover.py `
  --title "开源工具|人人可用" `
  --supplement "先做出一个|能用的版本" `
  --line-gap 40 `
  --out "../cover-work/final/cover.png" `
  --manifest-out "../cover-work/private/cover.json"
```

The example text above is only a layout demonstration; use claims from the active source. For optional yellow emphasis, add `--accent yellow --boxed-terms "开源工具" --yellow-terms "人人可用"`.

The renderer varies sizes and angles automatically. Use `--line-widths` or `--line-angles` only for a deliberate composition adjustment:

```powershell
--line-widths "0.96,0.90,0.82,0.92,0.58" `
--line-angles "-1.0,0.7,-1.5,0.8,-0.9"
```

A source-grounded supplement must always go through `--supplement`, never merged into `--title`. Every `--title` line becomes the manifest's `primaryTitle`, so a merged supplement makes `validate_bold_cover.py --expected-primary-title` fail even though the artwork is correct.

Five-line layouts shrink every line to fit the height budget; if the last line ends up too small, lower the earlier ratios rather than letting the closer read like a footnote.

When the user explicitly requests one shared left edge, use `--left-align`. It aligns the visible bounds of every line and disables rotation, so do not combine it with `--line-angles`. Reduce an over-wide line through its `--line-widths` ratio instead of allowing automatic horizontal fallback.

If adjacent visible glyphs collide, add deliberate breathing room instead of shrinking all text. Start with `--line-gap 24`; use roughly 40-64 px for four-line headlines with large type. Shadows may approach, but major glyph strokes from neighboring lines must not overlap.

The renderer also derives portrait scale from headline density. Override it only when visual inspection calls for a targeted adjustment:

```powershell
--avatar-scale 0.80 `
--avatar-x-shift 0.12 `
--avatar-y-shift 0.15
```

When using a public figure or alternate portrait, pass a versioned asset and record the subject:

```powershell
--avatar "../cover-work/portrait-liang-wenfeng.png" `
--portrait-label "梁文锋"
```

`render_bold_cover.py` writes a private JSON manifest (pass --manifest-out); without that option it writes a sibling manifest containing the primary title, supplement, line styles, assets, dimensions, and image hash.

## Validate and inspect

```powershell
python -X utf8 scripts/validate_bold_cover.py `
  --image "../cover-work/final/cover.png" `
  --manifest "../cover-work/private/cover.json" `
  --source-mode video `
  --check-line-overlap `
  --expected-primary-title "开源工具人人可用" `
  --expected-supplement "先做出一个能用的版本"
```

For script and video inputs, always pass `--source-mode script` or `--source-mode video`. The validator rejects a short primary hook without a supplement and rejects an underfilled combined headline. Use `--allow-sparse-headline` only when the user explicitly requires the short wording alone.

When image viewing is unavailable, use the pixel-level checker for a geometric overlap estimate, and record that final visual review is still pending:

```powershell
python -X utf8 scripts/check_portrait_overlap.py --manifest "../cover-work/private/cover.json" --per-char
```

This checker reports geometric estimates; its per-character splits are approximate for rotated and boxed text. It does not replace full-size character inspection. Then inspect the PNG visually at full size and as a feed thumbnail. Verify:

- Every title character matches the active source.
- For script/video mode, a short visible or extracted primary hook has been strengthened with a traceable supplement; the cover is not merely the sparse hook split into more lines.
- The text footprint is large, varied, and visually intentional rather than a regular stack.
- Adjacent lines retain clear glyph boundaries. Do not let one line cover another line's major horizontal, vertical, or enclosing strokes; use `--line-gap` when needed.
- The portrait overlaps type slightly without hiding the eyes or the decisive phrase.
- Inspect every overlapped character at full size and at 270x360. Treat 50% or greater portrait coverage of any one character as a hard failure; target 25% or less so each character remains immediately recognizable rather than merely guessable from context.
- Keep the complete head and face visible unless the user explicitly requests an intentional close crop; do not park the portrait in the extreme lower-right to recover text space.
- The portrait size fits this headline instead of looking pasted at a fixed template size.
- Text and portrait form one connected composition with no accidental dead zone at the top.
- The portrait edge has no black halo, backdrop patch, cast shadow, or glow.
- A public figure is genuinely relevant to the source and remains recognizable without implying an endorsement.
- The background remains subordinate to the headline; plain black is the default.
- No source-app UI, unsupported fact, watermark, or accidental logo enters the cover.

Make one targeted adjustment at a time. Keep every delivered earlier version unchanged and write revisions to a versioned output folder.

## Asset refresh

No assets are bundled. Use the built-in dark background for normal runs. If the user asks for a new portrait, a relevant public figure, or a new background:

1. Use an available image-generation tool when the user requests an asset generation or edit. For the user, use approved identity references; for a public figure, generate a recognizable editorial portrait only when the person is source-relevant.
2. Generate the portrait on a flat removable chroma-key background and remove it to real alpha. Require no shadow, halo, text, logo, or watermark.
   - Always verify the chroma background programmatically before cutting (corner pixels + greenness `g - max(r,b)` histogram). Generations frequently return a dark olive-gradient background instead of flat chroma; fix that with one image-to-image pass that keeps the person unchanged and forces a flat uniform `#00FF00` background, then verify corners again.
   - Before flooding, diagnose where dark pixels live (band histogram). If dark pixels cluster in the center/bottom-center bands while all non-bottom borders are pure green, the dark mass IS the person's clothing — skip luminance flood entirely. Use pure greenness removal (`gn > 34` transparent, `16-34` partial with despill), then keep only the largest alpha connected component (drop stray speckles), crop, and feather. Luminance-based border floods are only safe when dark pixels hug the borders as vignette while the person stays bright-edged; they will eat a dark-sweater subject that touches the bottom border.
3. Generate portrait and background separately. Preserve identity and inspect the portrait edge before selecting it.
4. Save a versioned asset and pass it through `--avatar` or `--background`; do not overwrite any previously approved asset silently. Public-figure portrait frames hug the person tightly, so the head can clip at the canvas edge — the checker's automatic head-clip scan flags it (a clipped NARROW band in the top half of the person = head cut; wide shoulder bands overflowing is intended corner anchoring).
5. Exaggerated gesture poses (raised arm, outstretched hand) are much wider than chest-up portraits and overlap far more headline area. Expect to drop `--avatar-scale` to roughly 0.62 and raise `--avatar-x-shift`; inspect each character instead of relying on a per-line average; use the approximate report to locate issues and target at most 25% coverage.

Use [asset-prompts.md](asset-prompts.md) as the starting prompt set for an approved asset refresh.



Run the commands from the Skill directory, but place all inputs, manifests and output folders outside that directory. The examples use ../cover-work only as a placeholder for an external working directory. For pure black-white output, omit --accent yellow, --boxed-terms and --yellow-terms. Use --manifest-out to keep process metadata outside the final PNG delivery folder; pass the same file via --manifest to validators/checkers.

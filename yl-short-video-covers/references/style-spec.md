# Bold Black-White Cover Style with Optional Yellow Accents

## Format

- Canvas: 1080x1440 PNG, RGB or RGBA.
- Safe area: at least 56 px on every edge.
- Headline: 3-5 compact lines occupying about 65%-75% of the canvas height.
- Optional user-supplied portrait: chest-up in the lower-right, recognizable at thumbnail size; normally 70%-84% of canvas height depending on headline density. Use the user or a source-relevant public figure.

## Palette

- Background: `#05070A` and `#111820`.
- Optional accent yellow (only when selected): `#FFC400`.
- Main text: `#F7F7F5`.
- Secondary technical marks: steel gray below 45% luminance.

## Typography

- Prefer Noto Sans SC Bold, Microsoft YaHei Bold, then SimHei.
- Target 180-320 px heavy type for compact lines. Size lines independently so short hooks can become dramatically larger than long lines.
- Use Noto Sans SC Bold with a same-color inner stroke to create an extra-heavy visual weight.
- Apply a small dark stroke or shadow to white and yellow text.
- Pure black-white mode uses no colored box. Optional yellow mode: a boxed term uses black text on a yellow rectangle with tight padding.
- Highlight no more than roughly one third of the headline.
- Rotate selected line blocks by roughly 0.5-2.5 degrees and vary their left offsets. Keep the overall reading order obvious.
- Keep neighboring glyph bodies visually separate. Shadows may nearly touch, but major strokes from one line must not cover the next line; add 24-64 px of explicit line gap when large four-line layouts collide.

## Composition

- Preserve dark contrast behind the title while retaining low-contrast circuit and grid detail.
- Default to a plain black background. An explicitly requested technology background may use layered subdued marks across the canvas, brighter near the edges and lower-right.
- Blend the portrait's black background into the template with a soft top-left mask.
- Treat headline and portrait as one connected silhouette. Avoid a narrow text column beside an isolated fixed-size person.
- Fill the top intentionally: begin visible type near the top safe area, or use a wide boxed warning line when the wording would otherwise leave a dead band.
- Choose portrait scale after headline layout. Increase it for sparse or four-line titles; reduce it for dense five-line titles.
- Composite the portrait after the headline. Keep the full head and face inside the canvas by default, then let the head or shoulder overlap a small lower-right portion of one or two lines without covering the eyes, core noun, or decisive claim.
- Use 25% of a character's visible glyph area as the normal portrait-overlap target and 50% as a hard maximum. If any character would be half-covered or more, rebreak the headline to create a portrait corridor, then adjust portrait position, then reduce scale. Never rely on surrounding words to make an obscured character guessable.
- Require a true transparent edge around the portrait. Do not leave a black cutout patch, halo, cast shadow, or glow behind hair and shoulders.
- Add only abstract linework and corner marks; do not add unverified data, logos, UI, or decorative English words.

## Quality gate

- For source screenshots below 800 px wide, inspect an enlarged top crop and verify each low-resolution character by its strokes.
- Title manifest matches the screenshot transcription exactly after removing line-break markers.
- For script or video mode, every primary and supporting hook is traceable to the active source.
- The title reaches at least 55% of canvas height and normally reaches 65%-75%; three or more lines show deliberate size variation.
- Portrait placement is recorded in the manifest and visibly responds to headline density rather than repeating a fixed scale.
- At both full size and 270x360, every overlapped character remains immediately recognizable; no individual character is 50% or more covered by the portrait, and normal overlap stays near or below 25%.
- The full head and face remain visible unless an intentional close crop was explicitly requested.
- Portrait subject is recorded in the manifest and is either the user or a person directly relevant to the source.
- No source-app UI, playback icon, timecode, likes, or subtitles enter the finished cover.
- If a portrait is used, preserve its supplied identity and plausible facial/hand anatomy.
- At 270x360 preview size, every title character remains readable.
- At full size and 270x360, adjacent headline lines do not merge into one ambiguous glyph mass.
- Original screenshots, photos, training assets, and reference grids remain private inputs and are never delivered as part of the cover.

All portrait requirements are conditional on the user supplying and requesting an avatar. Without an avatar, keep a balanced title silhouette and do not reserve an empty portrait column. No font, photograph or identity asset is distributed with this Skill.

# Asset Generation Prompts

Use these prompts only when the user asks to refresh the approved text-free assets. Keep the final title in the deterministic renderer.

## Portrait

```text
Use case: identity-preserve
Asset type: reusable portrait layer for Chinese short-video covers
Primary request: Create one high-impact editorial chest-up portrait of the same person shown in the user-supplied identity references. Preserve the actual face proportions, age, hairstyle and other distinguishing features. Use only the expression and pose requested by the user.
Input images: user-supplied identity references approved for this task.
Scene/backdrop: perfectly flat solid #00ff00 chroma-key background for local removal; no visible room or studio.
Style/medium: photorealistic editorial portrait with natural skin, glasses, and hands.
Composition/framing: vertical-friendly chest-up portrait, slightly right of center, complete hair and hand, generous chroma-key padding.
Lighting/mood: clean studio key light with a subtle warm rim light.
Constraints: identity must remain recognizable; one person; preserve the user-approved clothing; background is one uniform color with no shadow, gradient, texture, floor plane, or reflection; no microphone, desk, text, logo, or watermark.
Avoid: beautified or younger face, unrequested accessory or clothing changes, extra fingers, cropped fingers, plastic skin, black halo, cast shadow, contact shadow, glow.
```

## Source-relevant public figure portrait

```text
Use case: photorealistic-natural
Asset type: foreground portrait layer for a Chinese short-video cover
Primary request: Create a recognizable editorial chest-up portrait of the named public figure who is central to the source topic.
Scene/backdrop: perfectly flat solid #00ff00 chroma-key background for local removal.
Style/medium: photorealistic editorial press portrait with natural facial texture.
Composition/framing: complete head and shoulders, relaxed neutral expression, slight three-quarter pose, generous padding, no cropped hair.
Lighting/mood: clean soft studio key light with no cast shadow on the background.
Constraints: one relevant public figure only; preserve recognizable age and facial structure; no text, logo, watermark, prop, badge, or invented event context; uniform background with no gradient, texture, reflection, floor plane, or shadow.
Avoid: beauty retouching, celebrity caricature, altered age, extra people, halo, glow, cast shadow, contact shadow, busy background.
```

## Background

```text
Use case: ads-marketing
Asset type: reusable 3:4 portrait background layer for Chinese short-video covers
Primary request: Extract only the recurring visual language of the reference thumbnails and create one clean single-cover background, not a grid or screenshot. Use a dense, multi-layer technology texture with significantly more fine-grained detail than a minimal template.
Input images: the user's reference grid is style reference only; do not reproduce people, titles, interface chrome, counts, or account identity.
Scene/backdrop: deep matte black and midnight navy technology backdrop with layered circuit traces, chip diagrams, thin HUD rings, micro grids, schematic nodes, data-panel frames, dotted matrices, calibration ticks, angular brackets, and restrained AI-interface motifs.
Composition/framing: 3:4 portrait; low-contrast charcoal detail remains visible in the dark headline zone; brighter technical graphics cluster near the edges and lower-right; thin yellow corner marks and diagonal accents.
Color palette: #05070A, #111820, #FFC400, and muted steel gray.
Constraints: one image; no person, face, text, letters, numbers, logo, watermark, phone UI, social UI, or thumbnail grid.
Avoid: large empty black areas, rainbow cyberpunk, blue-purple gradients, photorealistic rooms, or detail so bright that it harms headline readability.
```

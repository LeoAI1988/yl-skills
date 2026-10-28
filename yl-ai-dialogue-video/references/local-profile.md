# 个人配置字段

按工具箱约定读取外部profile。优先复用已有字段：`video.covers.identity_reference`或用户当前指定的形象，`video.visual_style_file`、`video.font_file`以及`tools.ffmpeg`、`tools.ffprobe`、`tools.python_media`。

需要长期复用本人的剧情制作选择时，`video.dialogue.config_file`可指向核心外JSON。字段均可选，实际任务优先：

```json
{
  "schema_version": 1,
  "identity_reference": "installer-supplied identity file",
  "approved_scene_reference": "installer-supplied approved scene file",
  "approved_video": "installer-supplied approved sample",
  "approved_cover": "installer-supplied cover",
  "preferred_provider": "user-selected provider",
  "cost_policy": "free-only unless explicitly approved",
  "target_seconds": 30,
  "subtitle_scale_relative_to_talking_head": 0.8,
  "title_scale_relative_to_talking_head": 0.8,
  "scene_preference": "installer-supplied preference",
  "cover_preference": "source frame, calm expression, existing title",
  "speaker_gap_seconds": [0.30, 0.38],
  "notes": "Sample timing is a reference, not a universal speed multiplier."
}
```

没有配置时使用本次素材，不复制作者路径，不猜账号或声线。已确认的样片可作为画面、语速和表演参考，但不保证平台能继续生成相同声线。精确倍速、任务ID、额度和生成台账属于项目记录；免费次数不能固化成全局真值。

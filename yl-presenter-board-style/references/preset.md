# 个人预设

运行 `python scripts/layout.py --style my-style --width 2560 --height 1440`。名称从个人 profile 的 `video.presenter_board_styles` 解析，也可传入 `--style path/to/preset.json`。注册的相对路径从 profile 目录解析。

```json
{
  "schema": 1,
  "name": "my-style",
  "windows": {
    "split": [0.65, 0.10, 0.94, 0.86],
    "hero": [0.46, 0, 1, 1],
    "demo": [0.88, 0.04, 0.965, 0.19]
  },
  "caption_centres": [0.91, 0.96],
  "opening": {"mode": "fullscreen_to_split", "transition_seconds": 0.8, "land_on": "first_analysis_clause", "ease": "smoothstep"},
  "palette": {
    "background": "#141216", "panel": "#242125", "white": "#F8F6F2",
    "muted": "#BEB9B2", "accent": "#F3BD50", "secondary": "#75CED5"
  }
}
```

矩形按有效画布的左、上、右、下边界记录。两行字幕分别记录字形中心。演示圆窗取目标矩形内的最大正圆。项目可额外保存连续取样时码、可选色、字体、半径和进退场时间。

有全屏缩窗开场时，起始矩形覆盖整个画布，终止矩形取 `windows.split`。每条按第一段完整观点结束的时刻设置落点，用预设时长倒推运动起点。人物、声音与字幕共享剪后帧时钟，左图从落点淡入。

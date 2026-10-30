# 多源计划格式与执行产物

运行数据放在安装者的工作目录，路径均由该计划或个人 profile 提供，核心不包含真人素材、模型、字体或私人数据。依赖：Python 3.10+、Pillow、fontTools，支持 libx264/zscale/tonemap 的 FFmpeg 和 ffprobe。语音识别与声学工具由当前环境提供，不是渲染器运行依赖。

执行 `python scripts/render_mix.py <plan.json>`。输出、work 必须是未用过的新路径；输入为经人工/执行者裁决的保留区间，不从 ASR 自动猜测剪点。示意字段如下，路径占位值由安装者替换：

```json
{
  "schemaVersion": 1,
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "ffmpeg": "ffmpeg",
  "ffprobe": "ffprobe",
  "fontFile": "./runtime/static-900.ttf",
  "styleFile": "./runtime/style.json",
  "output": "./runtime/new-version.mp4",
  "work": "./runtime/new-run",
  "titleLines": ["已有口播支持的标题", "同一主题的第二行"],
  "titleEndFrame": 300,
  "titleAlreadyBaked": false,
  "blocks": [
    {
      "takeId": "take-a",
      "path": "./runtime/take-a.mp4",
      "sha256": "replace-with-source-digest",
      "role": "mother",
      "rate": 1.1,
      "keeps": [[0.1, 2.4], [2.8, 5.0]],
      "transfer": "bt709",
      "gainDb": 0
    },
    {
      "takeId": "take-b",
      "path": "./runtime/take-b.mp4",
      "sha256": "replace-with-source-digest",
      "role": "existing",
      "historicalRate": "unknown",
      "rate": 1,
      "keeps": [[11.0, 16.0]],
      "transfer": "bt709",
      "bakedStyleReviewed": true,
      "visualEvidence": "./runtime/source-style-contact.jpg"
    }
  ],
  "captions": [{"startFrame": 0, "endFrame": 30, "text": "实际保留的口播"}],
  "pauseReviews": [{"block": 0, "sourceStart": 2.4, "sourceEnd": 2.8, "decision": "cut", "reason": "已核实的无信息迟疑"}]
}
```

路径在执行前宜解析为绝对路径，避免工作目录改变。`takeId` 由素材归并阶段确认，渲染器不能凭字符串证明两次拍摄。`keeps` 是源秒、左闭右开，同块升序；块可以跨源、回跳。实现会落到归一化 `fps` 网格，输出块帧数为 `round(keptSourceFrames / rate)`；调用方应先 resolve 再映射字幕，保存实际落点和一帧误差范围。不要把源相机的60fps帧号按30fps解释。

`mother` 的 rate 来自本轮要求，`existing` 的新 rate 必须为1；历史速度单独记录。SDR 标签未知时须提供核实依据 `sdrEvidence`，不能只以位深猜测。渲染器支持已知 BT.709 与 HLG/PQ 的显式转换；未知混合色彩须先独立诊断，不能用该字段绕过检查。画布与输出fps必须依据实际素材及本轮规格确定，不由此示例固定。

style 为外置 JSON，包含 canvas、weight、titleSize/titleScaleX/titleBaselines/titleColor、subtitleSize/subtitleScaleX/subtitleBaseline/subtitleColor、outline、shadow(x/y/blur/alpha)、可选 underline(y/height/inset)。尺寸和基线以 style.canvas 为基准；本实现支持相同比例画布。长句由调用方分页；渲染器只测真实字体宽度并拒绝超宽，不偷偷缩字。

烧录字幕存在时，不能再生成该区间的字幕 PNG。`titleAlreadyBaked` 仅用于当前方案的片头确实已有合规标题；必须检查标题实际退场，不能用这个字段跳过后段新标题。若需要部分标题覆盖，先调整方案或使用能表达各区间显隐的等效图层实现，不在文字冲突处放行。

`bakedStyleReviewed` 是编辑者的审核声明，不是程序测出的排版成绩。`visualEvidence` 应覆盖全部保留区间的各种文字状态，包含中途强调/动画和结尾，不能只给片头稳定帧。固定排版要求与原烧录字冲突时，优先选同稿清洁母带；单凭历史表现最好不能放行不合格文字，也不能将旧数据移记到替换拍摄。证据和限制保存在运行目录，不进入通用核心。

工作目录保存 executed_plan.json、字体/样式/PNG哈希与真实字形框的 graphics.json、透明层无损 MOV、FFmpeg命令/日志、单次编码中间件、技术检查JSON。最后只作流复制清除已旋正像素可能继承的错误显示矩阵，不再有损编码。技术报告明确不包含实际听审；编辑者仍须完成 Skill 的语义、音频、视觉及源质量对照。

仅视觉修订可指定 `audioCopyFrom`、`audioCopySha256`、`audioCopyPlan`（该已核验版本的 executed_plan.json）。导出器核对每块源哈希、keeps、rate、gainDb、输出起点/帧数完全相同才允许流复制该 AAC；最终不采用临时新编码音轨，不再叠加倍速。HLG/PQ 块可按同源对照指定 `toneMap` 为 hable（默认）、mobius 或 reinhard；先选定自然肤色和高光细节，再冻结批次参数，不用重新贴色彩标签冒充转换。

可选分页辅助另需外置 jieba，不随核心分发。`paginate.pages` 返回 text 与规范化字符偏移，供调用方映射到已核对的词时；固定字号超宽报错，不能擅自缩字。protected 输入当前素材中的专名与不可拆词，分词结果和所有页面边界仍须回读。分页测试从外部 `--font` 和可选 `--tokenizer-dir` 接收运行依赖。

预设 CRF14/medium 是质量起点，不能用提高码率替代同源细节对照。修改后不能覆盖旧 work 或旧输出。运行目录大小和旧版清理由用户任务另行授权，渲染器不主动删除文件。

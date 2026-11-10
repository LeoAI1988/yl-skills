# 项目合同与工具

## 方案审计

`plan.json` 的数据由执行者根据全文和原声填写，放在项目目录。工具不自动判断论述完整、词音是否剪净或标题是否兑现。

```json
{
  "fps": "30/1",
  "max_duration_seconds": 180,
  "shared_ratio_warning": 0.15,
  "sources": [{"id": "source-a", "duration_us": 7200000000}],
  "clips": [
    {
      "id": "clip-a", "title": "主题甲", "question": "本条回答什么问题",
      "thesis": "本条核心判断", "logic": ["问题", "原因", "证据", "落点"],
      "opening": "源内完整开头", "ending": "源内完整收尾",
      "segments": [
        {"source": "source-a", "start_us": 120000000, "end_us": 156000000,
         "rate": "6/5", "text": "这一段实际保留的完整原话", "purpose": "解释原因"}
      ]
    }
  ]
}
```

时间是整数微秒，区间半开；倍速与 fps 用正有理数。支持多个源、跨段调序、同源重复使用与逐段速度；每段可提供已校准的 `output_frames`，与理论长度的差不得超过一输出帧。未提供时按累计有理数时长分配帧，避免逐段取整漂移。审计只是时间账，不代替音频采样执行及 PTS 对照。

输出包括各片总帧数/时长、映射、源去重时长及两两源交集：`shared/min(unique_a, unique_b)` 与 Jaccard。重复引用同一源段不重复扩大分母；不同源 ID 的同一底层素材要在策划前归一，否则会低估重叠。阈值是提醒而非平台规则，可以不设。开头/问题/判断等字段的完全相同另提醒；语义近似仍须人工审阅。

## 交付快照

`delivery.json` 按批次收齐所有片目。每个阶段资产写实际路径；路径相对该文件。未改片引用已有文件，不复制一份补版本号。`timeline_sha256` 是已确认本片时间轴指纹，`audio_sha256` 是该阶段应使用的原剪辑音轨指纹；增强阶段声明必须与未增强阶段相同，但声明本身不证明媒体内容已经验证。

```json
{
  "batch": "B0006",
  "edit_status": "feedback_applied",
  "clips": [
    {
      "id": "clip-a", "title": "主题甲", "content_revision": "c03",
      "duration_seconds": 90,
      "timeline_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audio_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "edited": {
        "path": "outputs/clip-a-edited.mp4",
        "timeline_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "audio_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      "enhanced": null,
      "cover": "outputs/clip-a-cover.png"
    }
  ]
}
```

示例哈希均为占位说明，真实项目必须由实际资产计算。两个阶段可各写 `duration_seconds`、`sha256` 和 `points`（包含 `time`、`label`），没有增强资产就填 null。源 ID、片 ID 使用字母/数字/横线/下划线，标题与原话允许自然语言。

`snapshot` 检查实际文件、流式计算媒体哈希、核对给定哈希与阶段绑定，并创建包含 `index.html`、白名单资产索引 `assets.json` 的项目快照；**不移动/复制/剪改媒体，不调用增强**。已有输出目录拒绝覆盖，每轮另建目录。它不能从 MP4 反推出删词是否落实、实际听审是否完成或已申明音轨是否真实复制，需另有媒体核验记录。

`serve` 默认仅监听本机，端口 0 自动选空闲端口；只读返回快照登记的文件及当前页面，支持 MP4 的 Range 请求。不会开放目录浏览、任意路径或云端访问。未增强与增强可明确切换，缺少阶段资产时显示未生成，不使用另一阶段兜底。当前阶段的下载和复核定位与播放器绑定。

## 意见和验收记录

项目另存反馈账本，至少含 `mode`（record_only/apply_authorized）、`items[].id/clip/baseline_batch/baseline_stage/user_text/source_anchor/action/status/supersedes/evidence`。机器检查、听审、视觉检查与用户批准分开；不能只把状态改为通过。

最终证据同时绑定实际视频、字幕、时间轴、原声音轨、封面和增强输入/回片。源文件不因片名、阶段或批次变动而换 ID。当前快照是可用资产目录，技术/主观验收缺项在回执中明确保存。

# 数据口径与最小输入

原始证据只追加，规范化结果可重建。每次采集有 collection_id，作品有字符串 publication_id，可用 work_id 关联同内容派生物，快照有 capture_id。标题不是主键。

各记录保存来源文件／截图位置、采集时间、平台原指标名、单位、窗口和归一化公式。时间为含时区 ISO 8601；比例为 0–1，金额统一币种且保留原单位；空值代表未知，不补零。总量、增量、累计到当前和区间内统计必须分开。

## 离线统计 CSV

每行是一个作品的一次同口径快照，必需列：

| 列 | 含义 |
|---|---|
| publication_id | 在输入所属账号内唯一的字符串作品 ID |
| captured_at | 含时区 ISO 时间，例如 `2026-01-02T12:00:00+08:00` |
| views | 非负整数；确实未知时留空 |
| data_maturity | `early` / `mature` / `unknown`，阈值由本次观察计划定义 |
| content_origin | `original_short_video` / `live_clip` / `unknown` |
| metric_scope | 同一账号、同一口径及窗口的标识，例如 `account-demo:lifetime` |

可另有 title、published_at、evidence_path、duration_seconds。不同账号或窗口分文件分析。`metric_scope` 一致只是标签约定，执行者仍须核对底层采集。

脚本先筛选成熟度／作品类型，再选每条最新合格快照；同 ID 同时间但指标不同视为冲突并报错。同条最新快照缺值时保留缺值，不悄悄回退旧播放数。只有数值已知的作品进入播放分布，同时报告缺失与排除数量。不要把筛掉或缺失的作品当作不存在。

## 其他分表

- 覆盖表：collection_id、layer、expected_count、checked_count、available_count、status、reason、evidence_path。status 为 complete / partial / not_available / not_requested；未知 expected_count 不能自称 complete。
- 留存表：publication_id、capture_id、原标签、ratio、denominator、window；平台 3 秒指标不能改称 5 秒。
- 账号表：日期窗口、总粉丝、新增、流失、净增和各受众维度；不得复制到每条作品伪装单篇指标。
- 成交表：订单／明细 ID、已付／取消／退款状态、币种、金额、商品、渠道、可核实的 publication_id、归因层级、时间口径。公开分析只用去标识汇总；客户联系方式默认不收集。
- 内容表：publication_id、原片／原稿位置、音频哈希、raw_asr、cleaned_transcript、封面／标题和核验状态。

独立完整复盘交付这些表或等价结构；小脚本只承担播放分布统计，不代替整套台账。

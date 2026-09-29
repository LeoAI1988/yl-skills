# 复盘大屏 JSON 合同

顶层字段：meta、posts、products、orders、attribution、transcripts、analysis、coverage。文件在安装者工作目录；时间保留时区，ID 为字符串，缺值为 null。

- meta：account、from、to、captured_at、generated_at、refresh_note、maturity_hours、hit_threshold、segments（日期起止二元数组）、account_views、account_followers、account_captured_at、attribution_note。不同来源不同时点时在 refresh_note 和 coverage 分别列明。
- posts：publication_id、title、date、published_at、public、mature、content_type（video/image/unknown）、views、completion_pct、three_sec_pct、watch_seconds、duration_seconds、follows、shares、topic。百分比为 0–100，图文视频指标必须 null；类型不明不进入视频统计。可附来源与采集时刻。
- products：product_id、label。标签是用户产品名；不在核心预设售价。
- orders：唯一 order_id、product_id、product、time、amount、paid、status、channel 及授权的 buyer、phone、address。一订单一行；多商品订单须在适配器建立明细及金额分摊校验，不能只取第一个商品。退款与已付原额分别保留，不混成净收入。
- attribution：publication_id、product_id、orders、amount、evidence。只收有商品与内容对应证据的记录；用户确认单独注明，推测不伪装为平台字段。归因窗口与全店支付窗口分开。
- transcripts：以 publication_id 为键，值含 status（校订稿/raw_asr/missing/not_applicable）、full、source_label、source_path、source_sha256、match_evidence、note、reason；opening 含 text、start、end、exact、label。每个显示作品必须有一条。
- analysis：证据支持的分析文字数组，统计数字从本轮统计对象生成。
- coverage：item、status、reason；区分 complete/partial/not_available/not_applicable，记录采集、稿件、业务、交互的真实状态。

生成命令不代表完成采集、补稿、产品归因或现场验收。保存输入及其哈希，使本轮统计可复现。

可选扩展：

- `meta.calendar_missing_dates`：未覆盖日期数组。这些日期显示待核；仅已核实覆盖日期允许零发布。适配器须先核验分页、可见性和区间覆盖。
- `orders.province`、`orders.city`：来源中可验证的省市，缺失留空；`address` 保留给授权 Excel，不写入 HTML。
- `posts.topic_evidence`：归类证据。`topic` 根据完整正文的主要价值归类，类别粒度一致；缺稿件列为待归类，不能用标题替代。
- `attribution_audit`：`summary`、`comparisons`、`routes`。对照行含 title、before/after_clicks、before/after_orders、before/after_amount、match；确认作品身份后补 publication_id 以打开全文。路径行含 route、status、finding。证据源和精确采集时间另存；未知不可用筛选日期替代。

`meta.include_customer_details` 默认为 false；仅在本次任务或安装者个人配置明确授权时为 true。连续发布节奏使用区间内全部公开作品，包含未满成熟期的作品；效果统计仍只使用成熟样本，不能把最近发布日画成零发布。

- `meta.sales_chart_product_ids`：恰好两个有效商品 ID；默认前两项产品。`orders_from/to` 可指定成交日期轴，`orders_missing_dates` 中的日期显示缺失并断线。
- `orders.paid_at`：带时区的付款时间；展示按适配器规范化后的当地日期统计。缺失时退回 time，适配器须说明时间口径。
- `posts.watch_seconds` 为平均播放时长（秒），参与五项评分，不得误用总视频时长；缺失不排名。

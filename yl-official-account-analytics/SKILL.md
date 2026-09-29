---
name: yl-official-account-analytics
description: 采集和复盘微信公众号账号、文章、分发通知、阅读来源及转化，保留全文与历史数据，并将新增本人文稿自动交给知识管理。
---

# 公众号采集与复盘

先读同级 `yl-media/references/handoff.md`。只处理已授权账号和日期窗口；已有信息复用，缺关键窗口才问。使用宿主已授权浏览器并先读该工具规范；登录/扫码由用户完成，不索取凭据、Cookie。无浏览器使用导出 CSV/XLSX、截图与原文，明示无法完成的层。

## 逐层采集

1. 记录账号总用户、任务请求的新增/流失/净增窗口，及可见受众/来源。账号窗口不能当逐篇数据。
2. 分页列出窗口全部发表记录，保留发表、通知、私密、删除/受限状态；移动“近30天”不能证明日历起点覆盖。
3. 打开每篇适用文章的详情，取实际可见的送达/曝光、阅读、独立读者、读完/平均阅读、分享、点赞/推荐、新增关注、来源、链接行动与业务结果。原始字段、单位和证据留存，不造缺值。
4. **已发表不等于已通知。** 零阅读或低阅读先查是否群发/通知、实际送达及分发范围，不能直接归咎文案、限流或重复。
5. 保存完整正文、标题、封面及发布时间关联；贴图文章仍是公众号 publication，可与原朋友圈内容共用 work_id，不能凭平台名推断创作方向。
6. 保存原始快照、规范化分表、覆盖表；每篇未打开是 partial，到达但未提供指标才是 not_available。

## 已实测接口（2026-09-25）

登录后从地址栏取 `token`，在同一已登录页面用同源 `fetch` 调只读接口，比点 DOM 稳得多：

- **发表记录**：`GET /cgi-bin/appmsgpublish?sub=list&begin=N&count=20&token=<TOKEN>&lang=zh_CN&f=json&ajax=1`
  - `publish_page` 是**嵌套 JSON 字符串**，需二次 `JSON.parse`
  - `publish_list[]` → 每项的 `publish_info` 仍是 JSON 字符串 → `sent_info.time`、`sent_status.{total,succ,fail}`、`appmsg_info[]`
  - `appmsg_info[]`：`appmsgid`、`title`、`content_url`、`read_num`、`like_num`、`comment_num`、`share_num`、`moment_like_num`、`old_like_num`、`is_deleted`、`copyright_status`、`item_show_type`、`share_type`
  - `count=20` 有效；按 `begin` 递增翻页至 `total_count`
- **文章列表**（另一口径）：`/cgi-bin/appmsg?...&action=list_ex&begin=N&count=20&type=9&sub_action=list_ex` → `app_msg_list[]`
- **正文**：抓 `content_url` 公开页，取 `#js_content` 的 innerText。兜底顺序 `#js_content` → `.rich_media_content` → `#page-content` → `.rich_media_area_primary`；**不要退到 `body`**（会拿到 2MB 脚本）。
  - `item_show_type=10`（贴图/分享型）正文在 **title 字段**里
  - `share_type=8`（视频分享型）页面无正文，只有 `js_article` 描述 → 如实标为视频分享版
- **登录后不得再导航或刷新**，否则 oauth 回调被打断需重扫。
- 正文抓取结果必须按 `#js_content` 命中率抽查；出现 `len` 异常大（>10 万）即为误取脚本，该篇标 partial 重取。

## 分析和回流

对照完整正文的首屏、读者收益、结构、事实/个人案例、互动与 CTA，结合账号自身可比组中位数和反例。没有点击分母不造点击率，没有消费详情不诊断具体流失段。业务区分平台归因、本人确认私域、仅时间相关，防止重复累计。

交付范围、覆盖、证据、正文、数据、观察/假设/实验。跨平台进入 `yl-media` 按共同 work_id 比较，不把公众号阅读数和视频播放数直接当同一漏斗，不使用视频选题评分。

新增本人正文→`yl-knowledge` 完整归档蒸馏；数据→`yl-knowledge-review-sync`。分析报告不是本人原话。现有本地台账可使用配置的 `platform_validate`/`platform_report` 引擎；新库按共享分表规范维护，不依赖作者私有目录。

不发布、修改、删除文章，不自动创建定时采集，不默认访问其他平台。

# 配置与协议

配置 JSON：`root` 是真源绝对路径；`roots` 为相对路径与类型组成的列表（`path`, `category`；类型 thoughts/works/topics/expressions/atoms）；`exclude_patterns` 为相对路径正则；`deny_ids` 为明确不上传的来源 ID；`credentials_file` 外置 JSON 包含 HTTPS `base` 和 `admin_token`；`state_dir` 为核心之外的报告目录。

默认只读 Markdown，不上传图片、课程媒体、压缩包、历史、隐藏目录、备份、私人目录、符号链接。作品要求正文侧车 `原文件名.md.asset.yml` 归属为 user_owned，且为已发表、确认定稿、核对的本人课程文字或校验副本。原子排除 retired、research_only、reference_only、P2/P3/private，以及未内化的外部和归属不明内容。表达聚合不自动引入其链接所指外部原文。明显凭证、证件号或私人电话模式命中则整篇留在本地，报告人工复核，不截断原文冒称完整。

服务端由安装者提供：

- `GET /admin/manifest`：Bearer 管理凭证；返回 `revision` 和 `documents:[{id,hash}]`。
- `POST /admin/sync`：`base_revision`、完整 `manifest` 和 `changed` 正文数组。服务端校验每篇 UTF-8 正文 SHA-256，原子事务更新；冲突返回 409。`changed` 文档含 `id, hash, title, source, category, text, meta`。
- 同步后再次读取清单，精确比较 id/hash 集合。

客户端自动重试仅限读取；写入错误须重新核对清单。HTTPS 必须验证证书，不允许把管理令牌放进 URL 或产品安装包。服务不可把管理接口公开成匿名下载端点。

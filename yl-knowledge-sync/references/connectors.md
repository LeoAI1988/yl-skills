# 来源连接器

Get 基址 `https://openapi.biji.com`。只用 GET：
- `/open/api/v1/resource/knowledge/list?page=N`
- `/open/api/v1/resource/knowledge/notes?topic_id=STRING&page=N`
- `/open/api/v1/resource/note/detail?id=STRING&image_quality=original`

请求头 `Authorization: GETNOTE_API_KEY`、`X-Client-ID: GETNOTE_CLIENT_ID`，绝不写入日志。`data.note.audio.original` 优先，其次 `web_page.content`、`content`、最后 `audio.transcript`；最后一种明确标为转写，不能假称音频已核验。保存使用字段与正文哈希。

分页以 `has_more` 为准，列表响应结构不符则停止而非当成空库。限流遵循服务端 retry_after；过长等待、配额用尽、权限不足记录未完成并退出。网络错误有限次重试，不无限循环。所有 ID 使用字符串。

原文和版本保留，云端删除或移库不删除本地原件。完整清点成功后才更新成员关系；部分失败不得把没读到的条目判为删除。元数据改变不代表正文改变。

其他来源统一交接：provider、source_id、revision/updated_at、title、primary_text、primary_field、authorship_evidence、attachments、original_url；缺失项留空。附件链接不是已经取得正文。第三方文件、客户资料与本人片段分别归属。

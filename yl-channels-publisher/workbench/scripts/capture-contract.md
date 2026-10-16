# WorkBuddy 采集交接合同 v1

调用：`await ingestCapture(workbenchRoot, absoluteJobDirectory)`。

本地导入只验证和保存本轮实际采集结果，不执行平台请求，不把导入时间当作采集时间。所有文件保留在本机；客户姓名、联系方式、地址、备注、Cookie、令牌及会话标识不得写入此合同。

## result.json

```json
{
  "kind": "capture",
  "account": "配置中的预期账号",
  "capturedAt": "本轮结束的含时区 ISO 8601 时间",
  "status": "partial",
  "files": {"posts": "posts.json"},
  "coverage": [{
    "layer": "posts", "status": "partial",
    "checkedCount": 1, "expectedCount": null,
    "reason": "说明实际检查的页数、作品范围和未完成部分"
  }],
  "evidence": {
    "source": "实际使用的 WorkBuddy 只读连接或工具名称",
    "readOnly": true,
    "completedAt": "本轮结束的含时区 ISO 8601 时间",
    "paginationExhausted": false,
    "includesHidden": false
  }
}
```

- `files` 只能使用任务目录内部的相对路径，不允许绝对路径、`..`、符号链接或指向其他任务目录。
- `posts` 必填且非空；失败、空响应或登录页面不能作为成功采集。
- `complete` 需要平台明确总数、检查数量、去重作品数量一致，已检查隐藏作品并确认分页结束。包含的其他层也必须完整；否则保留 `partial`。
- 部分采集会保存已核实的记录。未返回作品保留旧观察，不能据此标删除。未知指标使用 `null`。
- 每个文件必须有 `account`、真实的 `captured_at`，且与本轮结束时间在同一采集周期（24小时内）。不要复制旧文件后改时间。

## posts.json（必填）

```json
{
  "account": "配置中的预期账号",
  "captured_at": "实际读取时间，含时区",
  "total": null,
  "posts": [{
    "objectId": "平台返回的十进制字符串 ID",
    "createTime": 0,
    "visibleType": 1,
    "status": 1,
    "shortTitle": "短标题",
    "title": "完整描述",
    "len": null,
    "mediaType": 4,
    "readCount": null,
    "likeCount": null,
    "commentCount": null,
    "forwardCount": null,
    "favCount": null,
    "fullPlayRate": null,
    "avgPlayTimeSec": null,
    "fastFlipRate": null,
    "followCount": null
  }]
}
```

示例中的占位时间和 ID 必须换成平台真实值。`createTime` 为真实发布 Unix 秒；ID 绝不能先经过 JavaScript Number。`visibleType`：1公开、3隐藏、未知null；`mediaType`：4视频、2图文、未知null。两个比例字段为0–1；长度和平均观看为秒。`favCount` 沿用本项目视频号“推荐”口径，不同时伪造一个收藏数。

## 可选层

每个可选文件也需在 `files` 中登记，并提供同名 `coverage.layer`、实际 `checkedCount`、平台预计数或null、覆盖状态及原因。未更新的层完全省略，导入后保留它自己的旧采集时刻。

- `accountDaily`：使用逐日结构。顶层为 `account,captured_at,range:{start,end}`；`fans_trend:{errCode:0,data:{add,reduce,netAdd,total}}` 和 `new_post_total_data:{errCode:0,data:{totalData:{browse,like,comment,forward,fav,follow,ringset,snscover,statusref,forwardAggregation}}}`。指标均为按日期顺序的数组，缺值null；`total`和`browse`数组必须与自然日范围等长。检查数量为自然日数。
- `orders`：`{account,captured_at,total_orders,orders:[{order_id,status_str,is_pay_done,create_time,pay_ts,pay_price_fen,refund_fen,products:[{product_id,title,cnt,sale_channel}]}]}`。订单及商品ID为字符串；付款状态布尔；金额分、时间Unix秒。未知退款保留null，不作零退款。多商品订单未核对金额分摊前只保留证据，不能重复计入全额。
- `attribution`：`{account,captured_at,rows:[{publication_id,product_id,product,orders,amount,scope:"platform_window_reference",evidence}]}`。金额为人民币元；必须有可核实的平台作品及商品字符串ID。没有归因不能将全店成交分摊给视频。此层保持窗口参考口径，不冒充视频累计成交。

## 保存与重建

- 每批已核验文件与哈希存入 `data/captures/<capture-id>/`，不可覆盖。
- `data/capture-index.json` 只登记成功生成后的批次；重复同一批次幂等。
- 每次重建均回放已登记批次，按字符串作品ID、订单ID和日报日期关联，作品保留所有观察快照。
- 来源文件不改。更新失败保留原分析数据和大屏；损坏或哈希不一致的已登记证据拒绝重建。
- 新任务和旧任务串行导入。仅重新导入本地历史资料的操作可以合并执行。
- 归档成功与平台覆盖完整是不同状态；界面仍展示实际采集日期和partial缺口。

# 保存一篇公众号草稿

从确认过的 Markdown、排版 HTML 和独立封面开始。批量任务按作者指定的篇数逐篇执行，同一篇始终沿用同一份本地回执。只在用户要求保存微信草稿时使用 `--save`。

## 从本地成品开始

在本 Skill 目录调用[草稿工具](../scripts/wechat_draft.py)。本地排版用 Node.js 18+。草稿工具另需 Python 3.10+ 和 `requests`、`beautifulsoup4`、`Pillow>=9.1`、`filelock`。以下第一条只读本地文件，第二条保存一篇草稿并回读。

```powershell
python -B scripts/wechat_draft.py --md ARTICLE.md --html ARTICLE.html --cover assets/cover.png
python -B scripts/wechat_draft.py --md ARTICLE.md --html ARTICLE.html --cover assets/cover.png --save
```

正文插图使用微信支持的 PNG 或 JPEG。工具先校验本地文字、正文图片的顺序和字节、封面预览和下载文件。标题送入微信标题字段；正文保留内联样式及已确认的结尾。需要单独核验固定结尾时追加 `--cta-file`。完整个人结尾和视觉样稿由安装者维护。

## 写入与核验

1. 通过宿主安全存储或本次进程环境提供 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。凭据及 access token 只在运行时使用。默认回执和并发锁位于 Markdown 旁边，可用 `--receipt` 指定项目内的固定私有路径。回执记录素材与草稿标识，用于续办。
2. 在 `api.weixin.qq.com` 的 `cgi-bin` 下调用 `stable_token`。收到错误码 `40164` 时，把**本次微信错误回包实际给出的出口 IP** 发给用户。用户确认添加白名单后，用相同输入和回执重试。其他错误报告接口和错误码。
3. 正文图按定稿顺序逐张走 `media/uploadimg`，用微信返回的 URL 替换 HTML 内嵌图片。独立封面走 `material/add_material?type=image`，其标识填入 `thumb_media_id`。每篇单独执行 `draft/add` 并立即记录返回的 `media_id`。
4. 用 `draft/get` 按 UTF-8 回读，核对标题、全文及结尾、封面标识、插图内容和位置。微信有时会改写 CDN 地址；工具比对素材路径，必要时从微信图片域取回图片与本地原图比较。逐篇报告“已保存并回读”或明确的差异；微信编辑器目视预览单独记录。

## 中断或重试

重跑相同命令。已取得草稿标识时直接回读，已有素材沿用此前回执。提交后断线时，先用 `draft/batchget` 找同题草稿，并核对回执中的封面、正文与配图再认领。遇到多条同题、无法确认上一次结果或定稿指纹改变，把已有回执与后台草稿核清后再继续。已有项目用旧工具入库时，先读它的旧回执并用其中的草稿标识回读。草稿保存完成即交付；群发、定时或公开发布各自按用户要求处理。

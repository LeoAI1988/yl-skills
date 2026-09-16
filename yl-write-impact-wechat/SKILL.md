---
name: yl-write-impact-wechat
description: Use when drafting, revising, or packaging Chinese WeChat Official Account opinion, trend, or marketing articles from recordings, transcripts, notes, or the author's prior writing, especially when the user asks to preserve original phrases, remove generic AI prose, strengthen rapid-fire rhythm, create a high-impact opening, or use a 暴击风格.
---

# 暴击风格公众号写作

## 共同写作约束（每次必读）

起稿前读取并执行 [写作公共约束](references/writing-foundation.md) 及其完整规则；直接调用本 Skill 也必须执行写前、写后和交付检查。它约束所有框架与风格，保护用户原话和有效修辞。下文或旧参考中的绝对词句禁令与它冲突时，以公共规则的语义裁决为准；脚本命中不能替代审稿。


公开版保留高冲击判断、事实推进和作者原话的方法。用户也可能将这一方向称为“咪蒙风格”；这里提供高层叙事机制，不复制具体作者的身份、签名或独特受保护表达。

运行要求：Node.js 18 或更新版本，仅使用内置模块。先读取 [SOURCE.md](SOURCE.md) 了解来源与许可范围。用户稿件、CTA 文件、图像和生成结果放在安装者自己的项目中，不写入 Skill 目录。图片生成和笔记连接器是可选能力；没有这些工具仍可完成正文与本地 HTML。

## 核心合同

把作者的真实语言组织成有冲击力的文章，不把作者改造成“标准 AI 文案作者”。

“有冲击力”不等于短视频口号密集轰炸。公众号要保留原稿能传播的核心判断，同时把措辞、事件交代和留白提升到长文阅读需要的层次。

## 安装者表达校准

- 用户交回手调稿时，先与上一版逐处对照，学习修改的功能；不要把明显笔误或单篇题材词固化。
- 开头可以前置最高能量判断，但紧接着必须讲清事件。不要写“我昨天发过视频”“上一篇文章”“播放量多少”等幕后元叙述。
- 科技产品稿优先按“发生什么 → 新东西是什么 → 与主流有何不同 → 第一性原理 → 人话解释 → 动作背后的意义”推进，不把顺序机械变成六个小标题。
- 技术解释到普通人能懂原理和差异就停。把剩余篇幅留给组织力量、生态和局面。
- 历史暗示、商业案例和典故融在同一条主线上，点到为止；不逐项对标，不把寓意解释干。
- 不替读者说“谁是脊梁”或“让人后背发凉”。用事实、力量对比和停顿形成共鸣。
- 少分节，一气呵成；只有进入安装教程等阅读任务切换时才使用小标题。
- 公众号默认1800个中文非空白字符以内，2000为硬上限；用户明确要求长篇时例外。

交付必须分两阶段：

1. **阶段A：文字定稿。** 只创建和维护一份正文 Markdown。
2. **阶段B：完整包装。** 仅在用户明确确认文字定稿后，制作配图、完整排版 HTML、发布说明和事实说明。

违反阶段门槛，就是违反本 Skill。赶时间、节省步骤、用户最终肯定会同意，都不是提前做图或 HTML 的理由。

## 阶段A：只做文字 Markdown

1. 从任务中提取主题、读者、篇幅、核心判断、必须保留内容、禁用内容和结尾。
2. 素材来自 Get笔记时，使用安装者已配置并授权的笔记连接器，或读取安装者导出的原始 Markdown/逐字稿。搜索后读取笔记详情；Get笔记录音以 `data.note.audio.original` 为第一证据，不用摘要代替逐字稿。没有连接器时使用导出文件，不要求安装未列明的私人 Skill。
3. 阅读 [references/sourcing-and-claims.md](references/sourcing-and-claims.md)，建立来源边界、原话金句库和主张台账。
4. 阅读 [references/style-contract.md](references/style-contract.md)，先用原话搭结构，再写正文。
5. 输出或保存唯一一份 `.md`。不加入 Markdown 图片、不调用图片工具、不创建或更新 HTML。
6. 结尾使用安装者本轮提供或确认的署名与 CTA。未提供时自然收束，不添加原作者的固定结尾、赠品入口或联系方式。需要逐字校验结尾时，把确认的结尾单独保存到项目里的 `CTA.txt`，给校验器和 HTML 构建器追加 `--cta-file CTA.txt`。

7. 执行文字校验：

   ```powershell
   node scripts/validate-wechat-article.mjs --phase text --md ARTICLE.md --max-chars 1800
   ```

   按任务篇幅修改 `--max-chars`。校验失败则继续修改同一份 Markdown。
8. 等待明确放行。可接受信号包括“文字定稿”“文案没问题，开始排版”“可以做图和 HTML”。“继续”“先这样”“我看看”不构成放行。

## 阶段B：定稿后完整包装

先阅读 [references/staged-delivery.md](references/staged-delivery.md)，然后：

1. 冻结已确认正文；只从这一份 Markdown 派生其他交付物。
2. 封面涉及真实人物时，优先寻找有公开来源的真人照片并记录原始链接；只做裁切、色调、明暗、背景和标题排版，不伪造人物、篡改面部或用AI生成图冒充真人照片。需要生成或编辑位图时，使用当前环境已提供的图片工具；没有工具时交付可复用设计规格并如实说明图片状态，不假装已生成图片。
3. 正文默认不插装饰性AI配图。只有必要的真实聊天截图、公开资料图、数据图或用户明确要求的视觉证据才插入正文；否则只保留封面，优先保证阅读流畅。
4. 将最终图片引用加入 Markdown，再生成离线一键复制 HTML：

   ```powershell
   node scripts/build-wechat-html.mjs --input ARTICLE.md --output ARTICLE.html
   ```

5. 执行成品校验：

   ```powershell
   node scripts/validate-wechat-article.mjs --phase package --md ARTICLE.md --html ARTICLE.html --max-chars 1800
   ```

6. 实际打开 HTML，点击复制，粘贴检查标题、段落、加粗、图片、顺序和固定结尾。

默认排版合同：

- 二级小标题使用约22px、900字重；三级小标题也必须明显加粗；
- 提供 `--cta-file` 时，匹配末尾 CTA 段落并使用红色、加粗，与上文额外拉开约一行；未提供时保留普通段落样式；
- 这些样式必须进入复制到公众号的内联HTML，不能只存在于预览页CSS。

## 快速验收

| 维度 | 通过标准 |
|---|---|
| 原话 | 有辨识度的口语、动作和比喻仍然属于作者 |
| 标题 | 核心事件/对象＋明确判断，必要时带读者后果 |
| 开头 | 前约100字立住判断并交代具体事件 |
| 节奏 | 事件推进 → 人话解释 → 短句停顿 → 意义自然浮现 |
| 结构 | 事件 → 差异 → 第一性原理 → 力量与局面 → 必要行动 |
| 主张 | 事实、亲历、判断、营销口径和第三方信息已分层 |
| 交付 | 未定稿只有 Markdown；定稿后各版本从同一母版派生 |

## 红线自检

出现任一项，立即停在阶段A继续修改：

- 先按摘要写完，再找原话装饰。
- 用工整排比、抽象总结覆盖作者口语。
- 静默删除用户明确要求保留的营销判断。
- 用户还在改文字，却提前生成图片或 HTML。
- 为了“像暴击文”而编造数字、经历、对白或心理活动。
- 把另一篇文章的视觉模板机械套到本篇。

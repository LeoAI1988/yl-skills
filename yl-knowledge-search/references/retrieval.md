# 原文优先的本地混合检索

一个入口、一个正文库。文字与向量索引都是可重建投影，不是第二套知识正文。

## 运行配置

在核心外的个人 profile 中设 retrieval：manifest（来源清单JSON）、index_dir、python（独立运行环境可执行文件）、model、model_revision、model_path、model_cache、threads；个人术语 terms 与检索扩展 aliases 也在个人层。不得将本人路径、语料、模型权重、数据库或缓存打包到核心。

依赖为 PyYAML、jieba；本地语义检索另用 fastembed、numpy、ONNX Runtime。提供完整Skill，不按成员拆装；环境暂缺语义依赖时可用文字检索，但必须明确语义未启用，不能冒充完整混合检索。

模型优先免费、许可清楚的本地开源方案；可用 BAAI/bge-small-zh-v1.5 作为中文轻量基线。实际模型由真实问题命中质量和本机延时决定。仅 model-download 可以下载公共模型；embed/search 默认离线，不将正文发往外部。升级模型使用新 revision，旧向量不可混用。

下载后固定 model_path 与 model_revision，将已验证文件哈希登记为 model_files（相对文件名→SHA-256）；推理前核对，文件改变则停止语义调用，重新核对版本后才能重建向量。模型文件、依赖版本及许可证据留安装者本地。

## 来源清单

JSON包含 schema_version 和 sources 数组。每份源记录：source_id、path、title、kind（source/clean_source/work；派生导航使用其他类型）、authorship、review_status、aliases、index。可配置 include_sections、exclude_sections、allowed_spans、raw_source、related_ids。allowed_spans 是原文件物理行号，过滤后不可重新编号。清单由来源登记或已核库适配器生成，不能盲扫工程资料。

已知排除ID适用于所有入口和旧索引。未知说话者、未校对OCR/ASR保留明确状态；“可搜索”不等于“可直接作为本人引文”。校对后的 clean_verified 或明确确认的 final_confirmed 正文仍需识别内嵌他人引句。完整正文与未提原子的段落均可检索。

## 命令

从个人配置选择 Python，脚本是本Skill `scripts/retrieval.py`：

- `--profile PROFILE model-download`：获用户安装授权后获取公共模型；不上传语料。
- `--profile PROFILE index`：按清单增量建立文字索引，来源版本变化则替换受影响窗口。
- `--profile PROFILE embed`：离线补齐当前源窗口向量；可中断续跑。
- `--profile PROFILE status`：检查索引覆盖、版本变化、语义待处理数，不代替全文语义复核。
- `--profile PROFILE search --query "问题" --mode hybrid --limit 8`：默认两路召回。
- `--mode text`：精确表达/全文检索；`--mode semantic`：仅按意思召回，供对照测试。
- `--also-query "等义问法"`：最多3个，由当前Agent保留原问含义后提供；多问法合并去重，不在后台调用云模型。适合隐喻与跨领域问题。
- `--include-views`：需要找导航/原子视图时启用；视图不冒充原话。

读取型请求只能 search/status，不自动下载、建索引或入库。同步/导入完整流程结束须更新来源清单，再 index、embed、status；登记源而没有新原子仍然更新全文索引。

## 使用结果

中文分词和短语匹配打底，语义补措辞不同的材料；采用排名融合，不相加不可比较的原始分数。分段窗口只为寻找材料，命中后返回完整父段与准确位置，不以短摘要替代。原话匹配优先，不让多个副本挤占结果。

返回的 authorship 是来源登记，不证明每个内嵌引语的作者。只有清单 passage_reviews 中覆盖命中完整段落、确认本人且校对完成的记录，才令 quote_ready=true；其格式为 lines:[起行,止行]、authorship、review_status。没有逐段记录并不禁止阅读，而是需要使用者回读、核对后再引用。

返回 context 包含同一来源、同一已批准章节的前后段，保留原物理行号；不能跨到另一张卡片充当上下文。全部结果都是候选，不是已证明相关的答案，特别要检查否定、反问、引用他人、历史观点变化。semantic_similarity 是相似度而非正确率。无结果不证明不存在，向量总能返回近邻也不证明有答案。索引过期应报告缺口，不能继续使用过期行号。

## 验收

测试至少覆盖记得原话、只记得意思、未形成原子、长段尾部、相似但相反观点、跨领域类比、明确排除、源文改版、错误/待核转写。分别报告纯文字与混合的命中率、排序、延迟与失败案例。不得用索引条数证明提炼充分，也不预先承诺零遗漏。

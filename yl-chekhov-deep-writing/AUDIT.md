# 公开分享审核 · 2026-09-15

## 范围与结论

本次审核对象是本目录中的 35 个文件。上游来源为 Chekhov Deep Writing v1.0.0；12 个原运行文件完整保留其方法与参数，42 个发行包来源文件用于许可、原文和来源信息提取；该额外来源以 `tracking_scope: listed_files` 只跟踪所列公开文件，不扫描未分发研究实验树。原文件指纹保存在 `references/source-snapshot.json`。

本版只需此目录即可工作；无私人 Skill、私人路径、凭证、账户、用户图片或真实业务案例。运行脚本仅使用 Python 标准库；参数加载、校验和检索是本地只读操作。便携测试只修改它自己创建的临时副本。

## 逐文件语义复核

| 文件 | 内容与处理结论 |
|---|---|
| `SKILL.md` | 完整任务步骤、事实约束、原稿优先和停用条件；安装名已统一 `yl-`。 |
| `README.md` | 通用安装和使用说明；区分方法、全文、研究快照和能力边界。 |
| `NOTICE.md` | 上游署名、多许可、改动声明；不包含作者身份或机器地址。 |
| `LICENSE` | 原多许可声明原样保留；第 4 项研究快照不适用于本版，已在 NOTICE 说明。 |
| `references/source-snapshot.json` | 通用来源名、公开相对文件名和 SHA-256；无绝对来源路径或实际账户。 |
| `agents/openai.yaml` | 仅展示信息和 `$yl-chekhov-deep-writing` 调用提示。 |
| `assets/runtime-profile.json` | 3 个完整机制和 3 个外壳参数；来源哈希只作上游指纹，不依赖研究路径。 |
| `references/workflow.md` | 完整任务契约、内容内核、母版与素材不足处理；无私人材料。 |
| `references/mechanisms.md` | 3 个机制的适用、动作、效果、代价和停用条件完整。 |
| `references/language-shell.md` | 3 个语言参数、优先级、密度和原创性限制完整。 |
| `references/media.md` | 公众号、短视频、朋友圈共用同一内容内核；不自动发布。 |
| `references/corpus.md` | 内置/显式语料位置、中文权利边界、外部合法导入和检索限制。 |
| `scripts/corpus_utils.py` | 仅从显式位置或内置相对目录发现语料；相对成员防止路径越界。 |
| `scripts/load_runtime_profile.py` | 只读运行参数，校验机制代码、外壳模式、去身份化和数量约束。 |
| `scripts/search_corpus.py` | 本地逐字匹配，返回作品、来源、行号和固定根修订；无网络与写操作。 |
| `scripts/verify_install.py` | 校验运行配置、语料字节/哈希和公共包中文全文为 0。 |
| `scripts/test_portable_install.py` | 系统临时副本中运行验证，显式检查错误根和篡改；不修改日常安装。 |
| `corpus/corpus-manifest.json` | 12 部作品、公开署名、来源、版本限制、13 个载荷文件的哈希；删除上游内部流程字段。 |
| `corpus/source-registry.csv` | 12 条公开书目和权利信息；已删除原研究路径、隔离和实验记录。 |
| `corpus/originals/ru/clean/SRC-CHE-001_body.txt` | 《第六病室》俄文正文，保留上游字节、830 行；中文字符仅为脚注标记“注”。 |
| `corpus/originals/ru/clean/SRC-CHE-002_body.txt` | 《小公务员之死》俄文正文及公开编者脚注，64 行；无现代中文译文。 |
| `corpus/originals/ru/clean/SRC-CHE-003_body.txt` | 《变色龙》俄文正文及公开版本条目，66 行；无私人材料。 |
| `corpus/originals/ru/clean/SRC-CHE-004_body.txt` | 《草原》俄文正文及公开脚注，1629 行；中文字符仅为“注”。 |
| `corpus/originals/ru/clean/SRC-CHE-005_body.txt` | 《黑修士》俄文正文及公开脚注，464 行；中文字符仅为“注”。 |
| `corpus/originals/ru/clean/SRC-CHE-006_body.txt` | 《带小狗的女人》俄文正文及公开脚注，285 行；无中文或私人资料。 |
| `corpus/originals/ru/clean/SRC-CHE-007_body.txt` | 《三姐妹》俄文剧本、原版图注文字和公开脚注，2155 行；未携带图像。 |
| `corpus/originals/ru/clean/SRC-CHE-008_body.txt` | 《樱桃园》俄文剧本及公开脚注，1747 行；中文字符仅为“注”。 |
| `corpus/originals/ru/clean/SRC-CHE-009_body.txt` | 《伊奥尼奇》俄文正文及公开脚注，347 行；保留来源尚需校勘的限制。 |
| `corpus/originals/ru/clean/SRC-CHE-010_body.txt` | 《万尼亚舅舅》俄文剧本，1225 行；保留来源尚需校勘的限制。 |
| `corpus/originals/ru/clean/SRC-CHE-011_body.txt` | 《醋栗》俄文正文及公开脚注，119 行；来源说明保留转录质量和未校勘限制。 |
| `corpus/originals/ru/clean/SRC-CHE-013_body.txt` | 《戏剧》俄文正文及公开脚注，101 行；来源说明保留未校勘限制。 |
| `LICENSES/Apache-2.0.txt` | 标准许可证全文，原字节保留。 |
| `LICENSES/CC-BY-4.0.txt` | 标准许可证全文，原字节保留。 |
| `LICENSES/CC-BY-SA-4.0.txt` | 标准许可证全文，原字节保留。 |
| `AUDIT.md` | 本次公开版文件审核与可复现测试结果；无私人环境信息。 |

运行文档和代码逐文件阅读全文复核。12 部文学语料逐文件核对作品与许可、原文件 SHA-256、开篇结尾及异常字符/URL/可执行指令扫描；这不等于重新逐句校勘文学全文。原文中公开脚注纳入转录许可，不把其内容误称为契诃夫本人撰写。

## 自动扫描与可复现验证

- 私人姓名、已知联系方式、Windows 私有绝对路径、常见 API/令牌模式、上游研究内部路径：未发现需要保留的敏感项；已剔除来源表的内部路径与实验记录。
- 所有 12 部俄文 clean 正文 SHA-256 与上游逐一相等。检测到的汉字均为上游脚注标签“注”；不含中文出版译文。
- 相对 Markdown 引用全部存在；仅顶层存在 1 个 `SKILL.md`；无嵌套可安装 Skill。
- `python -B -X utf8 scripts/test_portable_install.py`：7 个验证组全部通过，涵盖空白安装上下文、运行参数、13 个载荷文件哈希、12 部原著列表、俄文来源/行号检索、中文缺失提示、错误根不回退和篡改检测。

## 发布边界

本目录审核通过可以进入集群构建。外部发布仍由集群维护者处理，本次没有推送 GitHub 或发布到其他平台。没有重新开展文学质量实验或评估传播效果。研究全文及实验树不在本版；上游运行参数的稳定状态作为来源状态保留。


## 集群 1.1.0 公共写作层审核（2026-09-15）

新增公共执行约束、完整提取规则、来源提取账、20 个来源文件的指纹/章节定位、只读候选检查脚本和分文件许可声明。逐文件复核后未发现私人身份、联系方式、私人路径、凭据、真实案例或隐性网络调用。合法作者署名与许可原文保留。

公共内容在 `yl-writing` 维护并复制给各写作成员；逐稿需语义裁决，不能用关键词/统计代替“无 AI 味”。新入口合同明确保护原话与文体，受影响旧规则服从共同冲突条款。脚本只读稿件，处理代码/URL 屏蔽、BOM/换行哈希、零候选仍须语义复核；返回值不表示文章质量通过。

新增 8 项公共集成回归通过，包含六个写作成员在各自独立临时目录运行、原稿不被修改、无材料不通过检查、副本漂移与缺失直调入口拒绝、风格依赖存在。10 个集群成员的官方结构校验和相对引用检查通过。字节未变的旧方法/语料/资源继承原审核；这次没有重新制作真实文章验证效果，也没有改动日常 Skill。

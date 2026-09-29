# 最小对象与完成记录

混合来源使用 `ownership: mixed` 时，完成收据还必须有 `owned_spans: [[本人片段起始行, 结束行], ...]`；逐字证据只能来自这些已判断为本人说话的段落。范围由 Agent 依据原文/说话人核实，不是脚本自动识别。

沿用已有库的格式优先，不能另造一套正文。新对象 Markdown 可用 YAML frontmatter：`id,type,title,version,source_id,source_sha256,authorship,confirmation_state,domain`；正文分“原话”“解释/方法”“语境与边界”“来源”“关联”。类型可为观点、概念、问题、方法、案例、表达或完整论述链，不以类别硬拆同一语义。

每个引文记录来源 ID、该版本 SHA-256、逐字片段、定位；多来源逐条对应。确认状态：原话已核、解释待本人确认；来自本人定稿；本人明确确认对象。外部引文保留真实作者，不填 user_owned。

对已有同义对象追加来源和表达变体，不替换原有来源数组。关联至少有目标 ID/路径、关系（同义、延展、应用、冲突、解释、证明）、原因与确认状态。正文用相对链接或双链，不能只有不可点击的 ID。

通用登记命令：`knowledge.py --profile PROFILE record --id SOURCE_ID --receipt RECEIPT.json`。该 JSON 位于本地系统资料，不随 Skill 发布。

```json
{
  "source_sha256": "SHA256_OF_REGISTERED_SOURCE",
  "ownership": "user_owned",
  "coverage": [[1, 10]],
  "classification_reason": "依据本人确认或逐段判断的证据",
  "dedup_reason": "实际比较过哪些既有对象，如何处理同义或差异",
  "atoms": [{"path": "05_知识原子/条目/OPI-unique.md", "quotes": ["原文中的完整片段"]}],
  "expressions": [],
  "expression_reason": "已检查表达，本次没有独立新增的理由",
  "links": ["01_我的思想体系/相关分支.md"],
  "organization_reason": "归到哪个观点分支、作品关系如何维护",
  "disposition": "distilled",
  "note": "完整阅读及边界说明"
}
```

coverage 是该版本全文的连续行号范围，必须覆盖全文；只是自报覆盖并不替代 Agent 实际阅读。每个产物 path 必须已经存在；quotes 必须同时存在于源和产物中。合并既有对象也登记其实际路径和本次逐字证据。无原子时 disposition 为 `no_new_atoms` 并说明原因；外部/明确排除分别用 `external_reference` / `excluded`，不生成本人原子。未决材料不提交假完成收据。

## 原子 YAML 硬约束（2026-09-26 实测补录，违反会被校验拦下）

写原子前先对照本节，别等校验报错再回头改。

- **`derivation.mode` 与类型绑定**：`QUO` 类型**必须**是 `verbatim`；`OPI / CAS / CON / SOL` 用 `source_grounded_abstraction`，纯亲历案例可用 `firsthand_case_extraction`。
  ⚠️ 注意：`QUO` 写错这一条 **`knowledge_atoms.py rebuild` 查不出来**，只有独立的 `verify_v2_atoms.py` 会报 `QUO derivation.mode must be verbatim`。两个校验都要跑。
- **`expression_roles` 允许值**：`hook / conflict / contrast / pain_point / judgment / method / proof / case / metaphor / escalation / rhythm / gold_line / closing`。
  **没有 `viewpoint`**，写 `viewpoint` 直接报 `unsupported expression role`。
- **`relationships[].type` 只允许四种**：`回应 / 解释 / 证明 / 冲突`。**没有 `支撑`、`举例`**；关系必须有 `target_id`、`evidence`、`confidence`、`status`。
- **正文必需小节**（缺一个就报 `missing body section`）：`## 原子内容`、`## 使用语境`、`## 不适用边界`、`## 来源定位`、`## 适用平台或内容类型`、`## 关联原子`。最后两节最容易被漏。
- **三处必须一一对齐**：`source_documents`、`source_hashes`、`source_locator` 三个列表**长度必须相等**且逐位对应；`verbatim_source` 必须同时出现在 `source_documents` 中，且其哈希等于文件实际哈希。
  删改来源时**必须三处同步删改**——只删路径会留下孤立哈希/定位行，报 `source paths and hashes must be non-empty and aligned`。
- **来源必须落在可引用白名单目录内**。新建子目录（例如在 `02_素材库/01_我的原始思考/` 下另开一个分类目录）会被判 `source is outside the eligible user-owned source set`，此时该文件只能作归档，不能列为任何原子的 `source_document`；在完成收据里用文字说明它与哪些既有原子同源。
- `relationship_schema_version` 必须为 `2.1`；`confirmation_state` 取 `source_verified_pending_user_confirmation / confirmed_via_user_final_source / user_confirmed_atom`。

## 常见校验错的处置顺序

1. `knowledge_atoms.py rebuild` → 结构与逐字源一致性（**先跑这个**）
2. `verify_v2_atoms.py` → 类型专属规则（QUO 的 derivation 等）与逐字在源中存在性
3. `knowledge_network.py verify` → 跨来源策展与共同概念
任一步报错都先修再进下一步；只修到不报错就宣布完成是假完成。

## 状态锁与重入

`knowledge.py` 的操作被中断（例如传错 `--receipt` 格式）会留下 `90_系统资料/YL知识管理/state.lock`，之后所有操作都报 `Another operation is active`。
确认没有进程在跑之后，直接删除这个空锁文件即可恢复；不要改 `state.json` 绕过。
另外 `record --receipt` 收的是 **JSON 文件路径**，不是 Markdown；Markdown 会报 `Expecting value: line 1 column 1`。

## 给原子挂来源前先查它的状态（2026-09-27 踩坑）

挂来源、补来源之前，**必须先读原子的 `v2_status` 与 `canonical`**：

- `v2_status: activated` + `canonical: true` 才是当前活跃实体，新来源挂这里。
- `v2_status: retired` / `canonical: false` 是**已归并的历史变体**，它的内容已经并入另一个实体（`aliases` 里有它的 ID）。**不要给它挂任何新来源或补充段**，否则：
  - 结构校验会报 `verbatim_source is not registered` 之类；
  - 统一网络会把把它判为 `removed_or_deactivated_existing_atom`，要求“核对旧关系及引用，禁止静默保留失效可写作状态”。
- 正确做法：用 `aliases` 或 `已核验原子归并.json` 找到 `target`，把来源挂到那个活跃实体上。

**另一条硬规矩**：`既有库策展基线.json` **只登记活跃原子**。把 retired 原子写进基线，会立刻触发 `removed_or_deactivated_existing_atom`（网络按 `baseline` 有、`current` 无来判定“被移除”）。发现误入就直接从基线里删掉该 ID。

## 清理来源引用时三处必须同步

删/改某个来源时，`source_documents`、`source_hashes`、`source_locator` **三个列表要一起动**。
只删路径行的典型后果：留下孤立的哈希行与定位行 → 报 `source paths and hashes must be non-empty and aligned` 和 `source_locator must be a non-empty list aligned with source_documents`。
清理时按“这个来源对应的路径行 + 哈希行 + 定位行”三件一起删，删完立刻跑 `rebuild` 确认。

## 原文原句必须可调用（2026-09-27 建原句库的教训）

**只提炼成原子是不够的。** 原子是骨架，原句是血肉；写文章时如果不给原句调用通道，
就是在"因为萃取而丢失信息量"。检索层必须同时覆盖**原文层**，不能只有总结卡可搜。

已建：`90_系统资料/系统导航/08_原句库/sentence_index.py`（`build` / `search` / `stats`），
`search --query "关键词"` 直接返回**命中那句本身 + 出处文件 + 行号**。

### 外部真源按「文件夹」判密级（2026-09-27 改定）

安装者已配置按目录分级的外部只读真源时，
**不要按登记表的 `privacy_level` 或内容哈希去判断，直接看路径**：

- `公开/` → 收录
- `P2/`、`P3/`、其它 → **跳过且不解析内容**（是“不读”，不是“读了再丢”）

理由：登记表里受限项的路径本来就是脱敏的（`[受限]`），且哈希存的是**规范化哈希**而非文件字节哈希，
按哈希匹配会全军覆没；文件夹才是不会漂移的物理权威。

```python
rel_top = os.path.relpath(dp, CONFIGURED_SOURCE_ROOT).split(os.sep)[0]
if rel_top != "公开":
    skipped += 1          # 不打开文件
    continue
```

### 建索引时必须守住的三条保真红线

**红线 1：分清谁在说话。**
Get笔记原文里 `🟣 我` 是本人原话，`🟢 说话人1` / `🔵 说话人3` 往往是**他人或环境音**
（车载导航"下一站…请提前做好下车准备"、路人），另有 AI 自动生成的标题与总结。
**不区分就会把他人的话和 AI 总结当成本人原话调出来。** 只保留标"我"的段落。

**红线 2：过滤不能一刀切。**
把所有文件都套"粘性过滤"会把本人正文一起删掉（实测 93,064 句 → 63,654 句）。
**要按文件类型分治**：只有真正的多人转写稿才启用粘性过滤；原子/作品正文/文章
只剔除显式的他人标记行。判断"是不是转写稿"不能只看有无时间戳——**原子和文章里
也会引用带时间戳的原话**；正确条件是「有 `getnote_note_id` 标记」或
「时间戳说话人标记 ≥3 个**且其中确实有非本人说话人**」。

**红线 3：别把原子的"头部"当引文切掉。**
原子文件往往 100+ 行，其中**大部分是头部（frontmatter）**，而
`verbatim_core`、`progression[].verbatim` 这些**原话就写在头部里**。
按处理转写稿的习惯切头部＝把最值钱的原句丢了（实测原子内容 41,327 → 13,192 句）。
**非转写稿一律保留完整内容（含头部）**，只在行清洗时剥掉字段键名（`xxx:`），保留值。

### 自检口径
建完索引必须抽查：① 原文独有的句子能否搜到；② 搜到的句子是否确实出自本人；
③ 总数不能明显低于上一版（明显下降通常意味着误删）。

## 新建原子的 ID 前缀（2026-09-27 踩坑）

现代方案**只认这几个前缀**：`OPI / SOL / QUO / CON / CAS / QST / KP`（外加 `KP*` 概念卡）。
**`CHAIN` 不是前缀**，它只是 legacy `GX-…-018-CHAIN` 这类 ID 的**后缀**。

造一个 `CHAIN-20260927-0001` 不会有任何报错提示，但后果是连锁的：

1. 网络 `load_ai()` **不加载该前缀** → 该原子根本不进 `records`；
2. 一旦在 `CROSS_EDGES` 里引用它，`refresh` 直接抛 `AssertionError: ('XXX', 'YYY')`；
3. **这个异常会让整个 `refresh` 中断**，`跨来源待复核队列.json`、`当前状态.json` 都停留在上一轮，看起来像“基线没同步”，极易误判。

**找机制类的卡用 `CON`，方法类用 `SOL`。**

## 跑状态类命令不要屏蔽输出（2026-09-27 教训）

`refresh` / `rebuild` / `scan` 这类会写状态文件的命令，**必须看 stdout/stderr**。
用 `>/dev/null` 会把 traceback 一起吞掉，只剩一个“队列没清”的表象，排查成本翻几倍。
写状态的操作失败时，**状态文件不会回滚**，留在旧值上，比直接报错更容易误导。

## legacy 原子不能作为正式关系目标（2026-09-27 踩坑）

库里 `GX-*` 那批（约 270 条）是 legacy 格式，**没有 `v2_status` 字段**，不参与 V2 关系表。

- 关系目标要写**完整 ID 含类型后缀**：不是 `GX-63D3A03F5C67-100`，而是 `GX-63D3A03F5C67-100-CHAIN`。
- 即使补全后缀，仍会报 `missing relationship target` —— 因为 legacy 原子不在 `valid_ids` 里。
- 正确做法：**在「关联原子」小节用文本说明关联**，写在关系表里会过不了校验。




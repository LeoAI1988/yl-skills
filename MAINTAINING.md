# 维护与发行

## 比对日常版本

```text
python tools/check_updates.py
python tools/check_updates.py --skills-root "日常 Skill 根目录"
python tools/check_updates.py --source "chekhov-deep-writing=该来源 Skill 目录"
```

默认在 `CODEX_HOME/skills` 或个人目录的 `.codex/skills` 查找快照中的来源。特殊来源可重复用 `--source 名称=目录`。路径只用于参数，不写入公开文件。输出仅表示来源变化，不能证明公开版已吸收变化；缺失来源单独报告。

成员 `references/source-snapshot.json` 保存审核时来源相对文件名与 SHA-256。私人文件名或无需分发的媒体可排除并注明。外置运行资产另命名登记。首次记录旧公开版来源时只建立当前比对起点，不声称它与日常版完全一致。

默认比较已登记文件并发现新增文本，未登记的新媒体不列入报告。`snapshot_ignored_patterns` 可排除运行缓存或 SDK。`tracking_scope: listed_files` 只检查明确登记文件的修改和删除，适合从较大发行工程提取的一部分资产；不会报告范围外的新增内容。

## 合并与审核

1. 阅读变化和公开适配，逐文件合并；不要整目录覆盖，不更新本机日常版。
2. 保留完整方法、有效通用案例、合法署名和必要脚本。私人案例改为安装者输入接口，不能替换成虚构事实。
3. 更新成员版本、快照、CHANGELOG、引用。新增成员登记到 `release.json`。
4. 运行 `python tools/audit.py` 自动初筛，再逐文件语义复核身份、经历、凭据、路径、外部请求、运行数据及许可。误报应逐项解释，不能全局忽略规则。
5. `reviews/skills.json` 记录各成员 `privacy_review`、`rights_review`、`method_review` 和相对文件 SHA-256 `files`。只在实际复核后更新；哈希脚本不等于人工审核。字节未变的文件可继承原审核并说明依据。
6. 工具箱 `references/catalog.json` 是生成文件，从审核哈希中排除；由成员 frontmatter 与发行配置派生。

项目文档、安装器和维护脚本也要审查。公开目录不得容纳私人“自用”文件。通用环境变量名可保留，真实凭据不可。

## 版本化构建

更新 `release.json` 中集群版本和实际变化成员的版本，再运行：

```text
python build.py
python tools/verify.py
```

构建检查登记成员、审核哈希、名称、相对链接和文件类型，生成目录、清单、固定名 ZIP、`releases/yl-toolbox-cluster-v版本.zip` 及 SHA-256。ZIP 固定时间戳与排序，同样输入可重现同样字节；已有发行号的不同内容会被拒绝，应增加版本再构建。

验证在系统临时目录解压和安装：预检不写入、完整安装、重复安装、旧版修改后拒绝覆盖、损坏包拒绝安装、ZIP 集合和字节一致。不触碰真实 Agent。

建议每月或分享前手动比对。这里没有后台任务，不默认联网拉取、推送或升级。

## 发布与扩充

本地、安装验证、打包、Git 提交、GitHub 推送和 Release 附件是不同状态。外部发布使用用户指定目标并检查可见性；不能只验证本地就声明已上线。

新类别先确认独立使用场景，再新增 `yl-分类` 入口。分类只负责选择交接，成员保留完整规则。文章只有一个主风格，组合须有不同贡献。

## 公共写作层更新

共同规则只先改 `yl-writing/references/writing-foundation.md`、`anti-ai-rules.md`、`anti-ai-extraction.md`、来源清单及 `scripts/check_writing.py`。来源比对范围见 `yl-writing/references/source-snapshot.json`；新来源先提取并复核，不复制私人校准或案例。

```text
python tools/sync_writing_foundation.py --apply
python tools/test_writing.py
```

同步器仅复制已定义公共文件到本发行目录中的写作成员，并生成 Human Writing 便携版；不改个人日常库，不自动标为已审核。不带 `--apply` 时只检查。构建再次拒绝副本漂移、遗漏直调公共入口或便携版不同步。

改动后检查受影响成员的调用合同、语义冲突、来源和许可，再更新各成员/项目审核哈希。已审核且字节未变的原文件继承旧记录；不能用批量生成哈希替代逐文件审核。运行检查器只证明可检测形状，新增规则需以实际稿件的误报和漏报持续改进。

# 文件计划与核验

这是本地文件工具，不调用剪辑器、开拍、云服务或发布平台。只按执行者已核对的清单操作，不扫描全盘决定删留。[通用去重收尾](completion-cleanup.md) 中本批临时副本和项目可再生缓存默认纳入完成流程，不要求额外清理口令；历史版本与正式资产不能按临时文件纳入。原声、内容与日期依据由执行者核对，工具只保障文件完整性、路径边界与可恢复进度。

用户已确认成果并说“归档”时，适用 [确认归档清场](completion-cleanup.md#用户确认成果并说归档时)：将本批对应的历轮工程与过程目录全部列为清理范围，只保留正式初始文件、最终成果与明确要求的交付。正式原始输入/成果若还在工程内先移至正式目录并核验，记录和工具自身必须在待清范围外；不能为了运行旧工程或保留付费增强中间件而默认留下整个工程归档。清理本批历史制作轮次属于归档收尾，未关联的历史项目仍不纳入。

## 输入

运行数据放在 Skill 核心外。清单 UTF-8 JSON，所有文件路径相对 `workspace_root` 或为其范围内绝对路径；工作区不能为磁盘根。一个 `item_id` 对应一条视频。

```json
{
  "workspace_root": "/work/video-project",
  "files": [
    {"item_id": "clip-a", "role": "final_video", "source": "review/clip-a-final.mp4", "target": "final/clip-a/clip-a-final.mp4"},
    {"item_id": "clip-a", "role": "cover", "source": "review/clip-a-cover.png", "target": "final/clip-a/clip-a-cover.png"},
    {"item_id": "clip-a", "role": "review", "source": "work/clip-a-review.md", "target": "final/clip-a/clip-a-review.md"},
    {"item_id": "clip-a", "role": "mother", "source": "input/clip-a.mp4", "target": "final/clip-a/素材原件/clip-a.mp4", "capture_date": "2026-01-01", "date_basis": "original media creation metadata in configured timezone"}
  ],
  "protected_paths": ["input/not-selected.mp4"],
  "cleanup_roots": ["review", "work/clip-a"],
  "status": {"actual_listening": "PENDING", "enhancement": "SKIPPED_USER_REQUEST", "published": false}
}
```

实际目录名以个人配置/项目规则为准。`mother.capture_date` 可以是 `unknown`，须说明依据。唯一增强源按母带角色保存，并在审查稿和清单的 `source_kind` 记作 `enhanced_recut_source`。角色还支持 `published_marker`，只有已有发布证据时才加入。

沿用已有成品根目录。用户指定的运营/分类映射目录只保存快捷方式，实体原片、文案与成品保留在既有正式原位置；不因目录名含“爆款”就认定其为实体真源。先按 [来源复用](../SKILL.md#来源复用优先) 只读解析快捷方式目标并核验完整SHA-256，再在自包含审查稿和工程中登记真实源路径与剪辑区间，不复制、硬链接或重复备份。使用现有脚本时只登记成果文件操作，不把外部正式原件登记为会移动/移除源文件的`mother`操作。替换映射侧已有副本前先创建并回读快捷方式、修复全部引用；只删除已核验副本，正式原件不动。其他未集中保存的常规母带才放在对应成品同目录或其“素材原件”子目录，不设独立母带根目录。课程切片归入“切片/课程编号或日期”，清单使用 `archive_type: "course_slices"`，不登记 `mother` 操作；在 `course_source_references` 数组中登记课程主文件夹的绝对源路径，工具只读核对路径和哈希，不复制或移动。浏览网页放在本轮成果目录并使用相对链接。上述 `records` 只是执行期间的示例，不是必交付目录。清单、计划和回执须在本批清理范围外临时保存，以保障重试；完成最后一次 `verify` 后，将必要依据合入审查稿，再清理临时记录。没有用户明确要求，不保留独立记录目录或隐藏副本。若用户要求移除既有记录目录，先核验成片、母带和自包含审查稿，再移除准确指定目录；之后以最终文件哈希和链接检查验收，不再调用已删除的回执。确认成果对应的历轮工程、已核验重复副本与可再生缓存按通用收尾规则直接移除，不以回收站或备份继续占空间；无关历史材料先核对本轮范围及用途。

每条须有一个成片和一个自包含审查稿；最多一个封面。无封面的条目必须带清单级 `no_cover_reason`，不自动生成封面。清单 `status` 原样写回，不因复制成功变更听审/增强/发布状态。

## 命令

```text
python -B scripts/archive_files.py plan --manifest /work/video-project/records/input.json --output /work/video-project/records/plan.json
python -B scripts/archive_files.py apply --plan /work/video-project/records/plan.json --receipt /work/video-project/records/receipt.json
python -B scripts/archive_files.py verify --receipt /work/video-project/records/receipt.json
python -B scripts/archive_files.py cleanup --receipt /work/video-project/records/receipt.json
python -B scripts/archive_files.py cleanup --receipt /work/video-project/records/receipt.json --apply
```

`plan` 校验范围、冲突、角色和保护清单，计算来源哈希，不移动媒体；课程切片拒绝母带复制并只读绑定已有课程源；常规母带目标须位于对应成品目录内；`apply` 先复制并核验成品，再保存/核验母带并移除相同已保存源文件，逐项更新回执。源和目标相同是只核验的原地保留。重复执行复用哈希一致的目标，冲突拒绝覆盖。

`cleanup` 默认只预检，在回执保存本次目录快照。带 `--apply` 才清理，且必须有相同目录快照；快照变了先重新预检。最终文件、母带、保护文件、计划、清单、回执和当前工具均不能落在清理目录中；符号链接/Junction 本身可拆除但不跟随其目标。根目录、越界目录或层层嵌套清理目录拒绝执行。

清理根目录清单必须由执行者核对，只包含本批默认收尾范围或另外明确授权的历史过程目录；工具不知道未登记的文件是否有业务价值。确认可再生且无占用的项目缓存可按完整缓存目录登记，不能扩展成整个依赖或工程目录。大目录预检后阅读清单与媒体候选，确认保留集完整。占用或权限失败会保存失败路径和未完成状态，不自动杀进程；解决确属本批的占用后重新预检再重试。已确认结果对应的本批历轮工程、可再生缓存及完整核验过的临时传输副本按通用规则直接移除，不另存隐藏备份；唯一原始输入、正式成果和无关项目继续保护。

跨工作区的课程来源仅通过 `course_source_references` 只读引用，不需要为归档先复制进剪辑工作区。其他确需归档的外部素材先按授权接入本项目，或沿用已有受控归档工具；不能为绕过边界把磁盘根当工作区。外部共享素材不能按“本批过程文件”移动或删除。

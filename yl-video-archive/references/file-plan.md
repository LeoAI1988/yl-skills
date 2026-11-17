# 文件计划与核验

工具按已核对清单完成本地归档、核验与清理。业务范围与依赖见 [去重收尾](completion-cleanup.md)，实际执行、受阻续做与结果回写见 [共享流程](../../yl-anti-entropy/references/workflow.md)。原声、内容与日期依据由执行者核对。

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

按 [来源复用](../SKILL.md#来源复用优先) 确定归档位置与真实源路径。外部正式原件只引用，清单只登记实际成果文件操作；会移动/移除源文件的 `mother` 操作仅用于确需归档的常规母带。

课程切片使用 `archive_type: "course_slices"`，不登记 `mother` 操作。在 `course_source_references` 数组中登记课程主文件夹的绝对源路径，工具只读核对路径和哈希。浏览网页放本轮成果目录，使用相对链接。

清单、计划、回执及工具须在待清范围外。完成最后一次 `verify` 后，将必要依据合入自包含审查稿，清理已无续做价值的临时记录。用户要求移除既有记录目录时，先核验保留集与说明，删除后依据最终文件哈希和链接验收。

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

清理根目录由执行者按业务范围登记。项目缓存须准确定位到已确认可再生且无占用的子目录，完整工程须满足确认归档条件。大目录预检后阅读清单与媒体候选，核对保留集完整。脚本保存实际失败路径与未完成状态，执行者按共享流程判断错误类型并续做；计划变化后重新预检。

跨工作区的课程来源仅通过 `course_source_references` 只读引用，不需要为归档先复制进剪辑工作区。其他确需归档的外部素材先按授权接入本项目，或沿用已有受控归档工具；不能为绕过边界把磁盘根当工作区。外部共享素材不能按“本批过程文件”移动或删除。

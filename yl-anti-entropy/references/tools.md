# 工具命令与清单

Python 3.10+，仅标准库。所有输出使用核心外的新目录；参数由本次任务提供，不把示例位置当真实授权。扫描/排重不删除媒体；清单不是用户指令，执行者必须核对本轮授权。

```text
python -B scripts/entropy.py scan --root <磁盘> --out <外部目录> --metadata-only
python -B scripts/entropy.py scan --root <磁盘或文件夹> --out <外部扫描目录>
python -B scripts/entropy.py scan --root <目录一> --root <目录二> --out <新的外部扫描目录>
python -B scripts/entropy.py scan --root <同范围> --out <新的外部目录> --baseline <旧扫描目录/scan.json>
python -B scripts/entropy.py scan --root <同范围> --out <新的外部目录> --resume-inventory <中断扫描目录/inventory.sqlite>
python -B scripts/entropy.py duplicates --inventory <扫描目录/inventory.sqlite> --out <外部重复清单.json> --minimum-mib 64
```

大盘先用 `--metadata-only`：按目录枚举的大小统计分布和最大文件，跳过重解析点，只输出Markdown及scan.json，不生成SQLite、不声明全盘独立文件实体或实际释放量。随后仅对选定候选目录运行下面的完整扫描/排重。元数据模式可比基线须同模式/根/排除项，不接受 `--resume-inventory`；完整哈希与保留集核验仍是执行前提。

`scan` 输出小型Markdown报告、目录/类型/近期分布与异常的scan.json及文件元数据SQLite。不读取正文或凭据，不跟随重解析点；记录真实文件身份，目录给逻辑大小，整体另给去除硬链接身份重复的字节数，后者仍不是NTFS实际分配。Linux等没有出生时间时不把ctime冒充创建时间。输出在被扫范围内时排除自身；对比要求根、排除项和模式一致。

超出数据库范围的异常时间戳记录为未知并报异常，文件仍计入大小。中断后可用 `--resume-inventory` 读取已提交的同范围清单，重新遍历目录并仅在大小/修改时间未变时复用已扫描记录，其他文件重新取元数据。来源清单必须在专用输出目录，续扫同时排除旧、新输出目录；结果标明复用数量，身份等字段仍属于首次采集时刻，不声称原子快照。归档或删除前始终重新核验真实文件与完整哈希，不能拿续扫元数据直接删。

`duplicates` 只分析指定阈值以上的同大小文件，计算完整SHA-256，检查扫描后是否变化，并将同实体硬链接的额外释放量记为0。输出是候选与上限，不是按名称/新旧自动选删的计划。想检查小文件可降低阈值；访问失败如实保留。

## 清单预检

工具支持字节重复、项目Webpack缓存、已确认结果的工程目录。其他系统/应用缓存先由执行者查明用途，再用适合的受控方法，不把它们伪装成这里的缓存类型。

清单格式如下，实际路径由执行者填写。`scope_roots` 是准确业务范围，不得为磁盘根；角色与关闭状态要来自本次已核对事实。

```json
{
  "scope_roots": ["/work/project"],
  "preserve": [
    {"path": "/work/project/original.mp4", "role": "original"},
    {"path": "/work/project/final.mp4", "role": "final"}
  ],
  "actions": [
    {"kind": "duplicate", "path": "/work/project/index/copy.mp4", "keep": "/work/project/original.mp4", "mode": "delete"},
    {"kind": "cache_tree", "path": "/work/project/node_modules/.cache/webpack", "inactive": true, "inactive_evidence": "project rendering and preview ended; no shared job uses this cache"},
    {"kind": "process_tree", "path": "/work/project/closed-work", "result_confirmed": true}
  ]
}
```

重复文件的 `mode` 可为 `delete` 或 Windows 的 `shortcut`；后者建立 `copy.mp4.lnk` 并回读真实目标，再删除副本。没有快捷方式需求时不增加别名。脚本只处理实体文件；原位置未知或内容不一致时拒绝。

`process_tree` 必须有已确认结果和 `original`、`final` 两种保留角色，正式文件不得在清理目录内；工具不猜某个视频是不是最终版本。目录内Junction/符号链接只拆链接，绝不进入目标。保留正式软件源码或用户要求的工程时不要把它列入目标。

`cache_tree` 当前只接受项目路径末尾 `.cache/webpack`；不活动证据由执行者在真实环境核查，字段不是自动检测证明。不让工具结束其他进程。

```text
python -B scripts/entropy.py plan --manifest <外部清单.json> --out <外部计划.json>
python -B scripts/entropy.py apply --plan <外部计划.json> --receipt <外部结果.json>
python -B scripts/entropy.py apply --plan <外部计划.json> --receipt <外部结果.json> --execute
```

`plan` 完整核验保留文件与重复文件，保存目录快照；不删除文件、不建媒体备份。`apply` 不带 `--execute` 不修改媒体；执行参数仅用于本轮已授权清理。真正执行前重新从原始清单校验边界、保留哈希和完整快照，计划/文件变化即拒绝。直接移除已核对目标，不创建回收站或备份副本。

结果记录实际完成与失败路径；发生部分删除或占用时保留结果，核对剩余文件后为剩余范围刷新计划，不盲目重跑旧目录快照。修复引用应在执行之前完成，脚本不会改写工程/网页/审查稿；完整哈希不能代替这项人工判断。工具只保障文件约束，不保证没有外部运行进程。

结束后将必要结论合入一份小型摘要，可清理已无续做价值的扫描数据库/计划，保留原件、确认成果和必要映射。不要把排查输出长期堆成另一套备份。

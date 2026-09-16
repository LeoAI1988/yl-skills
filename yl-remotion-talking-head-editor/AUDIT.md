# 公开版复核与防覆盖修复

复核日期：2026-09-15。逐文件完整读取原有 18 个文件，重点审查 6 个 scripts；本轮新增防覆盖测试及本审核文档。许可/NOTICE 文件由集群主流程另行核验并维护。

## 继承与本轮变化

复核开始时，对根 cluster.json 的旧字节基线核对：18 个原有文件中 16 个字节未变，只有 visual-style.md 与 acceptance.md 的封面路由适配发生变化。原隐私审核可继承；原审核记录并不证明视频端到端验收或第三方整包 MIT 权利。

本轮发现并修复验收报告路径可以覆盖媒体的缺口：Python 报告写入前未排除输入/别名，PowerShell 异常分支直接写 ReportPath。公开副本现在先验证路径，拒绝已有目标，以独占方式创建报告，隔离日志，启动器不再自行写报告。原日常版未修改。

## 逐文件语义结论

| 文件 | 复核结果 |
|---|---|
| `.gitignore` | 排除凭据、SDK、依赖、媒体、运行日志与检查点；未包含私人路径。忽略规则仅辅助，不能替代分发扫描。 |
| `SKILL.md` | 完整双模式剪辑入口、原声边界、逐项执行与五项验收；可选官方工具说明无私人依赖。 |
| `agents/openai.yaml` | yl- 调用提示与界面说明；无个人标识。 |
| `references/approved-example.md` | 安装者自行配置 Python/FFmpeg、NumPy/SciPy、Remotion、字体与开拍 SDK；明确 SDK 不随包分发、API 上传与额度行为。 |
| `references/content-analysis.md` | 完整三项 DBS 方法的源内剪辑适配；保留 dontbesilent 与来源模块归属，不动态调用外部 DBS，不含私人逐字稿。第三方许可范围须随根声明。 |
| `references/editing-workflow.md` | 通用逐字精修、停顿、EDL、原声和调序规则；示意名称和短语无个人身份、真实项目定位或媒体。 |
| `references/visual-style.md` | 通用视觉参数与人物避让方法；本轮仅将封面路由衔接到 yl-short-video-covers，单独安装有说明。 |
| `references/rendering.md` | 源片质量、HDR/SDR 与本地渲染说明；通用示例路径、来源质量保护与依赖条件齐全。 |
| `references/kaipai-enhance.md` | 公开 API 接入与色彩验收方法，凭据由安装者显式配置；动态能力带记录日期，无真实任务 ID 或签名 URL。 |
| `references/pause-policy.json` | 通用停顿参数，不携带用户录音或项目数据。 |
| `references/acceptance.md` | 五项验收、技术范围与归档边界；本轮更新 yl- 封面路由，并补新报告路径/独立日志与防覆盖合同。 |
| `references/final-transcript-archive.md` | 安装者指定目标后去重、写入及回读的通用闭环；没有私人知识库名称、ID 或目录。 |
| `scripts/kaipai_enhance.py` | 完整读取；仅从 MT_AK/MT_SK 或显式 env-file 读凭据，SDK 由显式目录提供；仅相应任务提交会上传素材/消耗额度，续查不重提。日志屏蔽原始 SDK 输出/签名 URL，原始回片独占落盘，不携带凭证。 |
| `scripts/pause-probe.py` | 完整读取；只读指定 WAV 并输出候选，无网络或写素材动作；NumPy/SciPy 已声明，16-bit 单声道 16kHz 是调用前提。 |
| `scripts/word-audit.py` | 完整读取；标准库读 ASR 与随包停顿策略，仅打印候选，无上传或自动剪切。 |
| `scripts/render-static-overlays.py` | 完整读取；本地 FFmpeg/FFprobe 通过参数数组调用，无 shell 拼接/网络下载；验证输入、EDL、透明层与尺寸，FFmpeg -n 拒绝覆盖，每次独立日志目录；开拍之外不会调用服务。 |
| `scripts/validate-video.py` | 完整读取；标准库与本地 FFmpeg/FFprobe，色彩检查仅导入随包本地探测函数，不触发开拍。修复 report 输入碰撞与已有文件覆盖；所有输出前预检、报告独占创建、日志独立目录。 |
| `scripts/validate-talking-head-video.ps1` | 完整读取；本地 Python 参数数组启动，无自动下载；移除 catch 分支 Set-Content 报告，启动失败只输出 JSON，不会覆盖输入。 |
| `tests/test_report_paths.py` | 新增隔离测试，仅临时虚构字节，不触发网络、真实视频、开拍或 FFmpeg；覆盖输入别名/已有文件/清单/保护路径及 PS 异常。 |
| `AUDIT.md` | 本轮逐文件复核与测试记录；只列公开安全相对路径。 |

## 实际验证

- `python -B -X utf8 tests/test_report_paths.py`：5 项测试通过，覆盖视频/相对别名、参考音轨、保护清单和受保护文件碰撞，硬链接与其他已有报告保护，未存在但列为保护对象的路径，失败报告正常创建及旧日志保留，PowerShell 启动失败不覆盖源。
- 本轮未提交开拍任务、未上传视频、未消耗 API 额度，也未声称重新完成视频端到端渲染。
- 原有 5 个 Python 脚本及新增测试通过 AST 解析；PowerShell 启动器通过语法解析。
- 原 18 文件的姓名、电话、邮箱、凭证形状、私有机器路径扫描零候选，相对文档链接零断链；本轮新增修改由集群最终扫描复核。

## 许可与发布边界

content-analysis.md 归属明确为 dontbesilent 的 dbs-script-flow、dbs-hook、dbs-content 适配。集群主流程已从上游 LICENSE 核实 CC BY-NC 4.0；按随包第三方声明保留归属与非商业范围，不能将这部分误标成 MIT 或无条件商业开源。Remotion、FFmpeg、字体与开拍 SDK 未打包，安装者按其各自许可获取。

技术与隐私方面可进入发布候选包；继续保留可核验的来源、独立版本与第三方许可。旧视频效果/听审不由本次代码审查重新认证。

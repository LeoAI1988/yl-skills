# yl 契诃夫深层写作 · 1.0.0

将用户自己的素材写成克制、具体、有观察力的中文文章、人物故事或连续口播。保留上游 Chekhov Deep Writing v1.0.0 的完整运行工作流：内容内核、母版、3 个机制、3 个语言外壳参数、媒介转译和停用条件。每次只用 1 个主机制，最多 2 个辅助机制，最多 2 个语言外壳参数。

## 使用

将整个 `yl-chekhov-deep-writing/` 放入支持 Skill 的工具目录，或用集群根安装器选择本项。不要只复制 `SKILL.md`。

```text
使用 $yl-chekhov-deep-writing，把以下原始素材写成一篇公众号文章。
保留我的原话和思路，篇幅约 1800 字，不虚构事实或对话。
```

先读 [SKILL.md](SKILL.md)。写作不需要账户、API Key、联网或其他私人 Skill。Python 3.10+ 仅用于可选参数加载、全文检索和安装校验。

## 交付与验收

默认给所需正文；内部完成事实/引语来源、段落新增信息、因果与反例、机制适配、外壳密度、原创性、字数和媒介格式检查。用户原稿优先，机制适用条件不齐时使用普通中文继续完成。

```powershell
python -B -X utf8 "<Skill>/scripts/load_runtime_profile.py"
python -B -X utf8 "<Skill>/scripts/verify_install.py"
python -B -X utf8 "<Skill>/scripts/test_portable_install.py"
```

`test_portable_install.py` 把整个 Skill 复制到系统临时目录，用空白 Codex 上下文检查载荷、检索和错误路径，再清理它自己创建的临时目录。不会安装到日常 Skill 目录。

## 包含与排除

| 部分 | 本版内容 |
|---|---|
| 写作方法与运行参数 | 上游全部 12 个运行文件，经命名与独立安装适配 |
| 原著 | 12 部俄文 clean 全文，逐文件保持上游 SHA-256；可定位到行 |
| 来源 | 作者、Wikisource 署名、固定根修订、版本限制、清单与哈希 |
| 中文出版译本 | 0；不含现代译者受版权保护的全文 |
| 研究快照、实验记录、原始 EPUB、重复阅读版 | 未包含；均不是本 Skill 普通运行依赖 |

程序校验验证安装与检索合同，不能证明文学质量、传播表现或现实素材的真实性。运行参数的 stable 状态继承上游发行版；本次没有重新进行上游文学实验。

详见 [NOTICE.md](NOTICE.md)、[语料说明](references/corpus.md) 与 [审核记录](AUDIT.md)。

---
name: yl-openai-api-credits
description: 通过 OpenAI API 额度处理文本分析、翻译、录音转写、绘图、封面编辑或可执行的媒体任务。也可查询赠额或首次关联组织。使用已授权项目的 API 或官方 Playground，取回结果，每次使用后核对并汇报可用余额。
---

# 用 OpenAI API 赠额跑任务

先按用户当次指令选择通道。个人配置已将 API 额度设为默认优先时，各类任务需要模型的步骤主动使用本技能。把实际所需的新模型工作交给目标 API 项目。已有授权项目凭据时可直接调用对应接口；已登录 Platform 时也可使用对应的 Playground，无需另建密钥。发起任务的宿主对话沿用原计费方式。用户指定“只用 API”时，模型步骤只提交到该组织，未获授权的其他模型通道不可代跑。

## 查额度

1. 打开官方账单页，核对当前组织。查看赠额明细中的可用余额、有效期和适用范围。组织总余额可能包含其他资金。用户只问余额时，回报查到的组织、金额、币种和有效期，到此完成。需要登录时，请用户在官方页面自行登录，随后接着处理。[组织账单](https://platform.openai.com/settings/organization/billing/overview) · [赠额明细](https://platform.openai.com/settings/organization/billing/credit-grants)
2. 已有适用赠额，直接执行下节。出现“已关联”但看不到赠额时，先核对组织和到账明细。首次领取才走文末的关联流程。资格、金额和周期均以该账户当时的官方结果为准。[官方赠额说明](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
3. 用户限定只用赠额时，按输入量、输出上限和所选模型价格估算本次用量。额度由组织共享，有并发用量或分批提交时复核余量。如果无法确认赠额足以覆盖这次请求，报告原因并保留待提交的任务。切换会员通道、自费或充值均需用户另行选择。[API 定价](https://openai.com/api/pricing/)

## 选择与产物匹配的 API

复用已经核实的逐字稿、时间码、素材和回图。先把需要模型的新工作与普通文件操作分开，按用户指定的通道完成各项。

| 交付需求 | 执行与核验 |
| --- | --- |
| 录音转写、字幕时码 | 从原片导出音频，走 Audio 的转写能力或 `POST /v1/audio/transcriptions`。需要逐词时间时选支持该粒度的模型与返回格式，按原片时间合并分段，抽听剪点并校正专名。只有文本返回时，另做音频对齐。[文件转写](https://developers.openai.com/api/docs/guides/speech-to-text) |
| 分镜、参考拆解、翻译 | 在 Responses 提供必要的抽帧、原稿或带编号字幕。要求按镜头或字幕 ID 返回，逐项核对覆盖、原意与顺序。 |
| 绘图、封面、局部返修 | 新图走 `/v1/images/generations`，有原图或参考图的编辑走 `/v1/images/edits`。免密钥时在目标项目的 Images Playground 附图，也可在 Responses 启用图像生成工具。取回可打开的图像文件，核对原字、尺寸、缩略图与参考。真人封面同时对照相机原帧的五官、镜片和肤色。[图像工作台](https://platform.openai.com/playground/images) · [图像 API](https://developers.openai.com/api/docs/guides/image-generation) |
| 可编辑图解、动效 | 让 Responses 输出 SVG、图层参数或渲染代码，检查文字与时码，再用交付环境渲染。只返回提示词或代码时，将回执记为方案或源码。 |
| 成片渲染 | 已获授权且托管环境具备输入文件、字体、编解码器、运行时长和可取回的文件输出时，可在 API 托管环境执行小样或合成。常规 FFmpeg／Remotion 也可在本机执行，使用本机算力。取回成片后检验分辨率、帧率、时长和音画同步；按实际执行环境登记。[API 赠额适用范围](https://developers.openai.com/api/docs/guides/chatgpt-api-credits) |

API 返回失败时，先查该项目的日志或 Images 历史。优先恢复已有输出，再处理明确失败的单项。可用的本机确定性操作可继续，需模型的步骤遵从当次额度限制。

## 提交任务并取回结果

1. 选定上述组织及其目标项目，按产物打开对应的 Playground 或使用已授权的同项目程序入口。文本、视觉分析与翻译可打开新的 Responses 对话。沿用本次指定的模型或个人配置中的分工，核对项目实际可用的完整型号。用户指定的型号不可用时，说明同一 API 通道中可选的替代项。[Responses Playground](https://platform.openai.com/chat/edit)
2. 把任务目标、必要材料和交付格式放进对话输入框（如 `Ask anything`），优先使用足以完成任务的脱敏摘录。模型需要本地文件中的信息时，提供相关正文。核对输入和输出上限后点击发送一次。左侧的提示词草稿可留作模板。
3. 取得实际回复，核对内容是否完成任务，将可用结果带回原项目。需要回执时，记录项目、模型、时间及页面显示的用量，从回复下方复制 `Log ID` 或保存可用的 Response ID。页面超时或失去焦点时，先查原对话和同项目日志，找到已完成的回复就接着用。只有确认请求未受理、或已明确失败且适合重试时才再提交。状态仍不明就报告待核对。[请求日志](https://platform.openai.com/logs)
4. 每次使用本技能，在最后一笔请求之后重新读取目标组织的官方赠额明细，在最终回复中主动报告当前可用余额、币种、组织和查询时间，页面列出到期日时一并报告。分批调用在本次任务结束时统一汇报。仅查询余额时直接报告此次读数。请求失败、用量延迟入账时仍核对余额，并说明已知状态。余额页无法访问时报告“本次余额未核实”及具体原因，禁止用旧余额或估算额填充。读取 Available 行的 Balance，区分赠额余额、已用金额与组织总余额。[赠额明细](https://platform.openai.com/settings/organization/billing/credit-grants)
5. 用户需要核对任务费用时，再按组织、项目及时间窗口查询可归属到请求的用量。组织共享余额的前后差额只能作为组织余额变化报告。[用量](https://platform.openai.com/usage)

在项目中记录实际调用的模型、可得的请求标识或生成记录、取回文件和本机完成的环节。已有凭据通过宿主安全存储或环境变量读取，避开聊天、日志与交付包。宿主无法访问相应 Playground，也没有已授权的程序化入口时，保留任务输入并说明“未提交”及所缺的访问条件。

## 首次关联接收组织

当用户要领取赠额，或明确要求首次关联时，使用宿主提供的 OpenAI 官方赠额工具。

1. 调用 `preview_api_credit_promo`。仅查询资格可在预览后结束。若返回 `already_linked`，回到账单核对。若 `eligible` 为真且有 `offer`，告知可领取的预估金额及到期日，再调用 `discover_api_orgs` 获取可选组织。
2. 把返回的 `destinations` 原样交给官方组织选择器 `confirm_api_credit_promo_org`，即使只有一个组织也由用户选择。仅在选择器返回 `approved` 与 `link_arguments` 时，将这组参数原样传给 `link_api_org`。选择器缺失、取消或没有可选组织时，说明当前状态，并提供上面的官方赠额说明。
3. 按 `delivery_result` 报告结果。`issued` 或 `already_issued` 用平台给出的金额与到期日，`no_credit` 表示此次未发放。对超时、结果不明或 `pending`，同一登录与工作区中至多重试一次，并复用相同的 `operation_id` 和 `destination_account_id`。切换账户或工作区后重新预览。回到账单核对可用赠额，再开始模型任务。

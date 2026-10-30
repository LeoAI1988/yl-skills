# 多轮反馈落实合同

用户说“只记录不修改”时只积累清单；之后明确开始则执行已授权范围。每条反馈使用稳定ID，记录截图或上下文、当前版本、操作类型、源区间、作用角色、预期文字变化及完成证据。重复提出的问题沿用ID并提高复查优先级，不能丢成一条新的模糊备注。

- `delete_audio_text`：词、残句、整句、咳嗽、停顿删除。明确“剪掉”必须改变原声音视频区间，字幕同步；不能改成字幕纠字或只验证该句完整。整句先查所有出现位置，再核定删一次还是全部；保留次数写清楚。
- `caption_correction`：发音正确而ASR误识，才只改文字。
- `copy_hook`：复制高能段到开头，主体原位置必须还在；逐角色核对源范围。`move`才允许删除原处。
- `speed`：保存用户精确十进制数，从原速一次应用。1.15与1.5不能互换；EDL、每段appliedRate、音频tempo、实际帧数/时长及网页元数据同时检查，禁止在已加速片上再次乘速。
- `cover`：仅改封面不改变正文、音轨或倍速。

## 原声边界与完成证据

残音、咳嗽、迟疑与失败起句经常不在ASR里，重复起句也可能被合并。旧字幕只用于定位候选；回原声小窗，结合无提示微转写、声学边界与实际听审确定起止，保护相邻完整字音。先查原声再改字幕，不能把字幕时间当准确切点。

每条删除核对：源区间已从指定role的keeps排除、最终字幕中预期次数吻合、对应新片切点复听。字幕不出现不证明原声已删除；幅度、微ASR不等于已听审。没有实际连续听审时分别记录用户确认、技术校验、执行者听审状态。停顿失败不得通过临时抬高阈值或无依据豁免转成PASS。

## 增强前后与网页绑定

无字底片在上传前核对实际解码帧数、音频时长与同版EDL；逐个hook核对源路径、seek偏移及全段覆盖。不能给不同来源统一套一个seek偏移，不能因为文件存在就跳过长度/哈希验证。底片不匹配先修本地拼接再上传。

有任务ID只续查；保留无字增强回片供后续剪切、字体与封面复用，音轨保留剪辑原声。已核验的hdvideoallinone路径为`/v1/hdvideoallinone_async`、空params；SDK路由task_type存在mtlab及speedup两种已核验形式。speedup是该接口的路由名，不表示用户视频应变速；以服务端实际预设取值，不强改成其中一种，不猜参数；路径、类型或参数超出核验集先停提交。

新版本以真实文件哈希绑定EDL、字幕与用户可见页面。回读页面实际video src及对应文件；标签写新版但链接仍旧不算完成。旧标签页不是最新交付依据。

## 可执行一致性检查

`scripts/verify_revision_contract.py --contract CONTRACT.json`检查上述结构证据；输入JSON含：

- requestedRate（建议十进制字符串）、audioTempo、previewRate；edl包含source、fps、playbackRate、outputFrames及keeps。
- keeps使用sourceStartFrame/sourceEndFrame半开源帧区间、role、existingRate和appliedRate；多源时每段明确source。
- operations各含id、kind、status；删除含role（all/hook/main）、sourceRanges（source/start/end）。有text时必须填expectedRemainingCount；无文字的咳嗽/停顿只核源区间。复制含完整要复制的sourceRanges。
- finalText，measured.frames/audioDuration来自实际媒体探测；enhancementInput.frames/audioDuration/hookCoverageChecked在上传前提供。
- finalVideo、videoSha256、previewVideo、previewSha256取自实际文件与网页，不靠手填PASS。

脚本只检证据一致性，不自动推断剪点、识别语义或授予听审通过。失败修正后重跑；清单逐项完成且所需感知验收通过再交付。

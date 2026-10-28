// Pure scheduling operations. A time belongs to a position; all other fields belong to a video card.
export const EXECUTION_MODELS = ['Space Bunny','GLM 5.3 Flash','DeepSeek v4.1 Flash'];

export function originalDecision(requested, durationSeconds) {
  const duration=typeof durationSeconds==='number'&&Number.isFinite(durationSeconds)&&durationSeconds>0?durationSeconds:null;
  if(!requested)return {original:false,originalRequested:false,durationSeconds:duration,originalReason:'按设置不声明原创'};
  if(duration!==null&&duration<5)return {original:false,originalRequested:true,durationSeconds:duration,originalReason:'不足 5 秒，不声明原创；执行时核对平台提示'};
  return {original:true,originalRequested:true,durationSeconds:duration,originalReason:duration===null?'时长未取得，执行时核对原创资格':'申请原创，仍需完成平台确认弹窗'};
}

export function workBuddyHandoff(saved, plan) {
  if(!saved?.markdown||!saved?.json||!saved?.id)throw new Error('清单尚未保存，不能生成启动指令');
  return [
    '请使用 yl-channels-publisher，按以下已保存清单在视频号助手执行本轮定时发布。本消息发送后，我授权你发布本批清单内的条目；不要超出本批范围。',
    '执行方式：当前 WorkBuddy 会话直接操作视频号页面。请重新读取磁盘上当前版 SKILL.md 及 references/workflow.md，不沿用旧对话中的网页 API 路径。',
    `清单文件：${saved.markdown}`,
    `结构化清单：${saved.json}`,
    `批次：${saved.id}`,
    `发布日期：${plan.date}（北京时间）；共 ${plan.rows.length} 条。`,
    `模型要求：${plan.execution?.model||'Space Bunny'}；思考强度极致；上下文窗口模型默认。请核对实际配置，不能仅声称已切换。`,
    '不要调用 /api/publish，不要把 /api/runtime 的 authorized=false 或 capabilities.publish=false 当作本流程的阻塞条件；这些只属于网页直连 API。不需要等待开放平台应用审核，也不得修改或绕过网页 API 的授权检查。',
    '读取清单后，下一步先用当前可用的浏览器／视频号页面工具打开视频号助手，检查真实登录状态。已登录则复用，按个人配置核对目标账号；只有页面实际要求登录时才展示二维码让我扫码，扫码后核对账号再继续。',
    '如果当前会话确实没有所需页面工具，请列出具体缺失能力；不要用尚未扫码、尚未核对账号或网页 OAuth 未完成代替实际检查。',
    '逐条保留清单中的视频顺序、时间、标题、封面、商品、标签、原创、位置和活动设置。不要另选素材或自行调整时间。',
    '定时必须读取关闭面板后的主表单完整日期和时间，与清单逐字比对；仅面板辅助框正确不算通过，不一致绝不点发表。提交后回到目标作品卡片核对平台时间，记录计划时间与实际时间。',
    '不足 5 秒且平台禁止原创时不声明并记录原因；其他视频仍须核对平台资格并完成原创确认弹窗。修改预约作品先定位目标卡片，再点其内部修改按钮，进入后再核对视频、标题、封面与商品。',
    '开始前核对平台已发布及已定时列表，避免重复发布；时间已过、素材缺失或设置有冲突时停止并说明，不擅自顺延。',
    '逐条完成上传和设置，回读核对后提交；提交结果不明时停止核对，不盲目重发。',
    '最后列出每条的实际状态、平台作品标识、定时时间及核验证据；保存清单不等于发布成功。',
  ].join('\n');
}

// An unavailable connection offers setup, never permission to submit a task.
export function publishAvailability(runtime, model, {publishing=false, awaitingStatus=false}={}) {
  const blocked=(label,reason,action='connect',disabled=false)=>({ready:false,label,reason,action,disabled});
  if(publishing)return blocked('正在提交…','正在提交本轮任务，请勿重复点击。','wait',true);
  if(runtime?.activeJob)return blocked('任务进行中','已有 WorkBuddy 任务，请先核对本轮结果。','wait',true);
  if(awaitingStatus)return blocked('正在核对状态…','正在核对最新任务状态，请稍候。','wait',true);
  if(!runtime)return blocked('检查连接后发布','尚未取得连接状态，点击检查 WorkBuddy 连接。');
  if(!runtime.configured)return blocked('连接后发布','尚未配置 WorkBuddy，点击连接后继续。');
  if(!runtime.authorized)return blocked('完成授权后发布','应用配置已保存，但尚未完成 WorkBuddy 授权。请先确认应用审核通过，再完成授权。');
  if(!runtime.online)return blocked('检查连接后发布','请打开 WorkBuddy 并保持本地助理在线，再检查连接。');
  if(!runtime.assistantModel||runtime.assistantModel!==model)return blocked('核对模型后发布','顶部发布模型须与 WorkBuddy 本地助理的实际模型一致。');
  if(!runtime.available)return blocked('检查连接后发布',runtime.message||'WorkBuddy 连接暂不可用，请检查连接。');
  if(!runtime.capabilities?.publish)return blocked('核验连接后发布',runtime.capabilities?.connectionCheck?'请先点击“检查视频号连接”，核对账号、模型和可用工具。':(runtime.message||'当前连接未开放发布权限，请检查授权范围。'));
  return {ready:true,label:'立即发布',reason:'连接已就绪；点击后核对本轮清单，再确认提交。',action:'publish',disabled:false};
}
export function moveSlot(slots, from, to) {
  if (![from, to].every(Number.isInteger) || from < 0 || to < 0 || from >= slots.length || to >= slots.length) return slots;
  const times = slots.map(s => s.time);
  const next = slots.slice();
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next.map((s, i) => ({ ...s, time: times[i] }));
}

// 路径归一化：Windows 大小写不敏感、斜杠方向不敏感，用于跨清单匹配同一条成片。
export function normPath(value) {
  return String(value ?? '').replace(/["']/g, '').replace(/\\/g, '/').trim().toLowerCase();
}

// 选片可用性：同一批次其他时间点已选用、或既往清单中已发布/已排期的视频不再提供选择，避免重复发布。
// 返回 null 可选；'taken' 本批已选；'published' 已发布或已排期。本行当前值始终可见，便于发现冲突后人工核对。
export function pickAvailability(full, { currentFull = null, takenFulls = [], publishedPaths = [] } = {}) {
  const key = normPath(full);
  if (!key) return null;
  if (currentFull && key === normPath(currentFull)) return null;
  const taken = new Set([...(takenFulls instanceof Set ? takenFulls : takenFulls)].map(normPath));
  const published = new Set([...(publishedPaths instanceof Set ? publishedPaths : publishedPaths)].map(normPath));
  if (taken.has(key)) return 'taken';
  if (published.has(key)) return 'published';
  return null;
}

export function localDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function validatePlan(plan, now = new Date()) {
  const errors = [];
  if(plan?.execution && (plan.execution.driver!=='WorkBuddy' || !EXECUTION_MODELS.includes(plan.execution.model) || plan.execution.thinking!=='极致' || plan.execution.contextWindow!=='模型默认')) errors.push('请选择有效的 WorkBuddy 模型设置');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(plan?.date || '')) errors.push('请选择发布日期');
  if (!Array.isArray(plan?.rows) || !plan.rows.length) return [...errors, '请设置有效的发布时间段'];
  if ('start' in plan || 'end' in plan) {
    const pattern = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!pattern.test(plan.start || '') || !pattern.test(plan.end || '') || plan.end <= plan.start) errors.push('请设置有效的起止时间');
    else if(plan.start<'06:00' || plan.end>'22:00' || Number(plan.start.slice(3))%10 || Number(plan.end.slice(3))%10) errors.push('起止时间限 06:00～22:00，分钟需为十分钟档位');
    else if (plan.rows[0].time !== plan.start || plan.rows.at(-1).time !== plan.end) errors.push('时间点与当前起止时间不一致，请重新设置时间段');
  }
  if (plan.rows.length !== plan.count) errors.push('时间点数量与发布条数不一致');
  let previous = '';
  for (const [i, row] of plan.rows.entries()) {
    const prefix = `第 ${i + 1} 条：`;
    if (!row.video) errors.push(prefix + '请选择视频');
    if (!row.cover) errors.push(prefix + '缺少封面');
    if (typeof row.title !== 'string' || [...row.title.trim()].length < 6) errors.push(prefix + '短标题至少需要 6 个字符');
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(row.time || '')) errors.push(prefix + '时间无效');
    if (previous && row.time <= previous) errors.push(prefix + '发布时间需依次递增');
    previous = row.time;
    const when = new Date(`${plan.date}T${row.time}:00+08:00`);
    if (!Number.isFinite(when.getTime()) || when <= now) errors.push(prefix + '发布时间必须晚于现在（北京时间）');
  }
  return errors;
}

const cell = value => String(value ?? '').replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>');
export function toMarkdown(plan) {
  const execution=plan.execution || {driver:'WorkBuddy',model:'Space Bunny',thinking:'极致',contextWindow:'模型默认'};
  const lines = [
    `# 视频号发布清单 · ${plan.date || '未定日期'}`,
    '', '状态：待发布；保存清单不代表平台已发布。',
    '时区：Asia/Shanghai（北京时间）。逐条设置以本清单为准。',
    '', '## 发布执行设置',
    `驱动：${execution.driver}`, `模型：${execution.model}`, `思考强度：${execution.thinking}`, `上下文窗口：${execution.contextWindow}`,
    '执行前在 WorkBuddy 中核对上述选择；保存清单不会自动切换 WorkBuddy 当前会话的模型。',
    '', '| 序号 | 时间 | 视频 | 短标题 | 商品 | 位置 | 原创 | 活动 |',
    '|---|---|---|---|---|---|---|---|',
  ];
  for (const row of plan.rows) {
    lines.push(`| ${[row.seq, row.time, row.videoRel, row.title, row.goods || '不挂商品', row.loc, row.original ? '是' : '否', row.activity].map(cell).join(' | ')} |`);
  }
  for (const row of plan.rows) {
    lines.push('', `## 第 ${row.seq} 条 · ${plan.date} ${row.time}`, '',
      '视频完整路径：', '```text', row.video || '未选', '```',
      '封面完整路径：', '```text', row.cover || '缺少', '```',
      `短标题：${row.title || '待定'}`, `商品：${row.goods || '不挂商品'}`,
      `位置：${row.loc}`, `原创：${row.original ? '声明原创' : '不声明原创'}`, `时长：${typeof row.durationSeconds==='number'?row.durationSeconds.toFixed(3)+' 秒':'待核对'}`, `原创说明：${row.originalReason||'按本条设置及平台实际资格核对'}`, `活动：${row.activity}`,
      '描述（原样填写）：', '```text', `${row.title || ''} ${row.tags || ''}`.trim(), '```');
  }
  lines.push('', '## 执行要求',
    '1. 本清单是排期草稿；执行前确认本次发布授权和目标账号。',
    '2. 使用每条完整视频及封面路径，核对文件与画面；封面必须手动上传。',
    '3. 逐条核对标题、描述、定时、位置、商品、原创、活动、封面；以上方逐条设置为准。',
    '4. 提交前读取平台当前限制与表单错误；不以可点击状态代替内容校验。',
    '5. 提交后核对目标作品及定时时间，记录平台作品标识。提交结果不明时先查列表，不直接重发。',
    '6. 保存计划、已提交定时、已公开发布分别记录，不混为完成。', '');
  lines.push('7. 定时面板关闭后回读主表单完整日期和时间；与清单不一致禁止提交，不能以辅助输入框显示代替主表单生效。',
    '8. 提交后记录平台实际时间，不得从计划复制实际值。修改预约只进入目标卡片的编辑入口，确认目标身份后修改，回列表核对旧时间已覆盖且无重复。',
    '9. 原创资格以实际时长和平台提示核对；不足 5 秒不声明，记录限制原因；其他符合资格的视频完成确认弹窗。');
  return lines.join('\n');
}

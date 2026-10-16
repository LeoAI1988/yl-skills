// Pure scheduling operations. A time belongs to a position; all other fields belong to a video card.
export const EXECUTION_MODELS = ['Space Bunny','GLM 5.3 Flash','DeepSeek v4.1 Flash'];
export function moveSlot(slots, from, to) {
  if (![from, to].every(Number.isInteger) || from < 0 || to < 0 || from >= slots.length || to >= slots.length) return slots;
  const times = slots.map(s => s.time);
  const next = slots.slice();
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next.map((s, i) => ({ ...s, time: times[i] }));
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
      `位置：${row.loc}`, `原创：${row.original ? '声明原创' : '不声明原创'}`, `活动：${row.activity}`,
      '描述（原样填写）：', '```text', `${row.title || ''} ${row.tags || ''}`.trim(), '```');
  }
  lines.push('', '## 执行要求',
    '1. 本清单是排期草稿；执行前确认本次发布授权和目标账号。',
    '2. 使用每条完整视频及封面路径，核对文件与画面；封面必须手动上传。',
    '3. 逐条核对标题、描述、定时、位置、商品、原创、活动、封面；以上方逐条设置为准。',
    '4. 提交前读取平台当前限制与表单错误；不以可点击状态代替内容校验。',
    '5. 提交后核对目标作品及定时时间，记录平台作品标识。提交结果不明时先查列表，不直接重发。',
    '6. 保存计划、已提交定时、已公开发布分别记录，不混为完成。', '');
  return lines.join('\n');
}

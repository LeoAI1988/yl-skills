// 通用名封面（封面.png / cover.png）与成片的自动匹配规则。
// 回归背景：切片/述品视频逐条目录里成片旁只放一张「封面.png」，
// 修复前 baseKey 配对永远失败，工作台报「⚠ 无封面」。
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {scanOne} from '../server.mjs';

async function makeTree(structure) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'yl-cover-test-'));
  for (const [file, content] of Object.entries(structure)) {
    const full = path.join(root, file);
    await fs.mkdir(path.dirname(full), {recursive: true});
    await fs.writeFile(full, content ?? 'x');
  }
  return root;
}
const video = name => Buffer.from([0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70]); // 最小占位，扫描只看扩展名
const cover = name => Buffer.from([0x89, 0x50, 0x4e, 0x47]);

test('通用名封面与唯一成片同目录时自动匹配（逐条目录）', async () => {
  const root = await makeTree({
    '08_单条口播/08_单条口播.mp4': video(),
    '08_单条口播/封面.png': cover(),
    '08_单条口播/审查稿.md': '# 审查稿',
  });
  const result = await scanOne(root);
  assert.equal(result.count, 1);
  assert.equal(result.missingCover.length, 0);
  assert.match(result.items[0].cover ?? '', /封面\.png$/);
});

test('一个目录多条不同成片时通用名封面不自动匹配，保持缺封面待人工确认', async () => {
  const root = await makeTree({
    'a_主题一.mp4': video(),
    'b_主题二.mp4': video(),
    '封面.png': cover(),
  });
  const result = await scanOne(root);
  assert.equal(result.count, 2);
  assert.equal(result.missingCover.length, 2);
  assert.equal(result.items.every(i => i.cover === null), true);
});

test('同一成片的多个版本算一条，通用名封面仍然匹配', async () => {
  const root = await makeTree({
    '切片/05_主题_v1.mp4': video(),
    '切片/05_主题_v2.mp4': video(),
    '切片/封面.png': cover(),
  });
  const result = await scanOne(root);
  assert.equal(result.count, 1);
  assert.match(result.items[0].cover ?? '', /封面\.png$/);
  assert.match(result.items[0].name, /_v2\.mp4$/); // 仍取高版本成片
});

test('能按名字配对的封面优先于通用名封面', async () => {
  const root = await makeTree({
    '04_主题/04_主题.mp4': video(),
    '04_主题/04_主题_封面-v2.png': cover(),
    '04_主题/封面.png': cover(),
  });
  const result = await scanOne(root);
  assert.match(result.items[0].cover ?? '', /04_主题_封面-v2\.png$/);
});

test('通用名识别覆盖 cover.png 与带版本号的 封面_v2.png', async () => {
  const rootA = await makeTree({'x/01_主题.mp4': video(), 'x/cover.png': cover()});
  assert.match((await scanOne(rootA)).items[0].cover ?? '', /cover\.png$/);
  const rootB = await makeTree({'y/01_主题.mp4': video(), 'y/封面_v2.png': cover()});
  assert.match((await scanOne(rootB)).items[0].cover ?? '', /封面_v2\.png$/);
});

test('二次剪辑批次命名：_剪辑版_vN 成片配同目录 _封面_vN（1019 批次回归）', async () => {
  const root = await makeTree({
    '1019/01_做容易的事/01_做容易的事_剪辑版_v1.mp4': video(),
    '1019/01_做容易的事/01_做容易的事_剪辑版_v8.mp4': video(),
    '1019/01_做容易的事/01_做容易的事_封面_v1.png': cover(),
    '1019/01_做容易的事/01_做容易的事_封面_v3.png': cover(),
    '1019/04_用别人的东西建设自己/04_用别人的东西建设自己_剪辑版_v8.mp4': video(),
    '1019/04_用别人的东西建设自己/04_用别人的东西建设自己_封面_v1.png': cover(),
  });
  const result = await scanOne(root);
  assert.equal(result.count, 2);
  assert.equal(result.missingCover.length, 0);
  const byName = Object.fromEntries(result.items.map(i => [i.name, i.cover]));
  assert.match(byName['01_做容易的事_剪辑版_v8.mp4'] ?? '', /封面_v3\.png$/); // 取最高版封面
  assert.match(byName['04_用别人的东西建设自己_剪辑版_v8.mp4'] ?? '', /封面_v1\.png$/);
});

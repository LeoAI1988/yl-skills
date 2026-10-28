import test from 'node:test';
import assert from 'node:assert/strict';
import {pickAvailability, normPath} from '../plan-core.mjs';

const drive = 'Q';
const p = (path) => `${drive}:${path}`;

test('路径归一化忽略大小写与斜杠方向', () => {
  assert.equal(normPath(p('\\A\\b.mp4')), p('/a/b.mp4'));
  assert.equal(normPath(`"${p('/A/b.mp4')}"`), p('/a/b.mp4'));
  assert.equal(normPath(''), '');
  assert.equal(normPath(null), '');
});

test('已发布/已排期与本批已选用的视频不再提供选择', () => {
  // 既往清单路径大小写、斜杠与扫描结果不一致时仍匹配
  assert.equal(pickAvailability(p('\\04\\x.mp4'), {publishedPaths:[p('/04/X.mp4')]}), 'published');
  assert.equal(pickAvailability(p('/04/x.mp4'), {takenFulls:[p('\\04\\X.mp4')]}), 'taken');
  // 本行当前值即使已发布也保持可见，便于人工核对后处理
  assert.equal(pickAvailability(p('/04/x.mp4'), {currentFull:p('\\04\\X.mp4'), publishedPaths:[p('/04/x.mp4')]}), null);
  // 未出现过的视频可选
  assert.equal(pickAvailability(p('/04/y.mp4'), {publishedPaths:[p('/04/x.mp4')], takenFulls:[p('/04/z.mp4')]}), null);
  // 空路径不参与判定
  assert.equal(pickAvailability('', {publishedPaths:[p('/04/x.mp4')]}), null);
  // Set 与数组入参一致
  assert.equal(pickAvailability(p('/04/x.mp4'), {publishedPaths:new Set([p('/04/x.mp4')])}), 'published');
  // 本批已选优先于已发布标注
  assert.equal(pickAvailability(p('/04/x.mp4'), {takenFulls:[p('/04/x.mp4')], publishedPaths:[p('/04/x.mp4')]}), 'taken');
});

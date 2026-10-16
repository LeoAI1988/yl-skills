import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
const core=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const inside=(base,target)=>{const rel=path.relative(base,target);return rel===''||(!rel.startsWith('..'+path.sep)&&rel!=='..'&&!path.isAbsolute(rel));};
export async function loadConfiguration({configFile,profileFile=process.env.YL_PROFILE||path.join(os.homedir(),'.config','yl-toolbox','profile.json')}={}) {
  if(!configFile){const profile=JSON.parse(await fs.readFile(profileFile,'utf8'));configFile=profile.publishing?.channels?.config_file;}
  if(typeof configFile!=='string'||!path.isAbsolute(configFile))throw new Error('请配置 publishing.channels.config_file 的完整路径');
  const value=JSON.parse(await fs.readFile(configFile,'utf8'));
  if(typeof value.workspace!=='string'||!path.isAbsolute(value.workspace))throw new Error('workspace 必须是完整路径');
  if(typeof value.expectedAccount!=='string'||!value.expectedAccount.trim())throw new Error('expectedAccount 不能为空');
  if(typeof value.python!=='string'||!value.python.trim())throw new Error('请配置 Python 3.10+');
  for(const key of ['products','tags'])if(!Array.isArray(value[key])||value[key].some(v=>typeof v!=='string'||!v.trim()))throw new Error(key+' 必须是字符串列表');
  // Resolve the nearest existing ancestor first, so a junction cannot place data in the core.
  let ancestor=path.resolve(value.workspace),tail=[];
  while(true){try{ancestor=await fs.realpath(ancestor);break;}catch(e){if(e.code!=='ENOENT')throw e;const parent=path.dirname(ancestor);if(parent===ancestor)throw e;tail.unshift(path.basename(ancestor));ancestor=parent;}}
  const workspace=path.join(ancestor,...tail),actualCore=await fs.realpath(core);
  if(inside(actualCore,workspace)||inside(workspace,actualCore))throw new Error('workspace 必须独立于共享核心');
  await fs.mkdir(workspace,{recursive:true});
  const analytics=path.join(workspace,'analytics-config.json');
  const initial={account:value.expectedAccount,python:value.python,dashboardScript:path.join(actualCore,'yl-channels-analytics','scripts','dashboard.py')};
  try{await fs.writeFile(analytics,JSON.stringify(initial,null,2),{flag:'wx'});}catch(e){if(e.code!=='EEXIST')throw e;const existing=JSON.parse(await fs.readFile(analytics,'utf8'));if(existing.account!==value.expectedAccount)throw new Error('工作目录已有其他账号资料');}
  return {...value,workspace};
}

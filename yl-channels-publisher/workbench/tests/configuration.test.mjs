import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadConfiguration} from '../configuration.mjs';
test('empty installation uses external data and preserves existing account config',async t=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-config-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const configFile=path.join(dir,'config.json');
  const config={workspace:path.join(dir,'data'),expectedAccount:'Test Account',python:'python',products:[],tags:[]};
  await fs.writeFile(configFile,JSON.stringify(config));
  const actual=await loadConfiguration({configFile});assert.equal(actual.workspace,await fs.realpath(config.workspace));
  const file=path.join(actual.workspace,'analytics-config.json'),before=await fs.readFile(file,'utf8');
  await loadConfiguration({configFile});assert.equal(await fs.readFile(file,'utf8'),before);
  await fs.writeFile(configFile,JSON.stringify({...config,expectedAccount:'Other Account'}));await assert.rejects(()=>loadConfiguration({configFile}),/其他账号/);
});
test('missing configuration and in-core data are rejected',async t=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'channels-config-'));t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const configFile=path.join(dir,'config.json');await fs.writeFile(configFile,'{}');
  await assert.rejects(()=>loadConfiguration({configFile}),/workspace/);
  await fs.writeFile(configFile,JSON.stringify({workspace:path.dirname(fileURLToPath(import.meta.url)),expectedAccount:'Test',python:'python',products:[],tags:[]}));
  await assert.rejects(()=>loadConfiguration({configFile}),/共享核心/);
});

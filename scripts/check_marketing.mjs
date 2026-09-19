// Browser QA with mocked analytics and SMTP: sends no external requests or email.
// PLAYWRIGHT_MODULE=/absolute/path/to/playwright node scripts/check_marketing.mjs
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {resolve, dirname, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
import {execFileSync} from 'node:child_process';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=resolve(dirname(fileURLToPath(import.meta.url)), '..');
const qa=resolve(root,'release/marketing-qa');
await mkdir(qa,{recursive:true});
const modes={preview:{},enabled:{INDEXING_ENABLED:'1',METRICA_ID:'123456'}};
const servers=[];
for (const [mode, flags] of Object.entries(modes)) {
 const env={...process.env,INDEXING_ENABLED:'0',METRICA_ID:'',SITE_URL:'https://ligus-msk.ru',BASE_PATH:'',FORM_PROVIDER:'smtp',OUTPUT_DIR:resolve(qa,mode),...flags};
 execFileSync('python3',['build.py'],{cwd:root,env});
 execFileSync('python3',['verify.py'],{cwd:root,env});
 const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let path=resolve(qa,mode,'.'+decodeURIComponent(url.pathname));
  if(!path.startsWith(resolve(qa,mode)+'/')&&path!==resolve(qa,mode)){res.writeHead(403).end();return;}
  if(url.pathname.endsWith('/'))path+='/index.html';
  try {const data=await readFile(path);res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'})[extname(path)]||'application/octet-stream');res.end(data);}catch{res.writeHead(404).end();}
 });
 await new Promise((r,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',r);});servers.push(server);modes[mode].url='http://127.0.0.1:'+server.address().port;
}
const browser=await chromium.launch({headless:true,...(process.env.CHROME_BIN ? {executablePath:process.env.CHROME_BIN} : {})});
const failures=[];let checks=0;
const stub=`window.metricCalls=[];window.ym=function(...a){window.metricCalls.push(a.slice(0,4));if(a[1]==='reachGoal')a[4]?.();};`;
async function context(mode, viewport={width:390,height:844}, slow=false){
 const ctx=await browser.newContext({viewport});const hits=[];
 await ctx.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.hostname==='127.0.0.1')return route.continue();
  hits.push(url.href);
  if(url.href==='https://mc.yandex.ru/metrika/tag.js'){
   if(slow)await new Promise(r=>setTimeout(r,350));
   return route.fulfill({contentType:'application/javascript',body:stub});
  }
  return route.abort();
 });
 const page=await ctx.newPage();page.on('pageerror',e=>failures.push(e.message));
 return {ctx,page,hits,url:modes[mode].url};
}
try{
 // Default builds must have no counter, banner or external SDK request.
 let t=await context('preview');
 await t.page.goto(t.url+'/');await t.page.waitForLoadState('networkidle');
 assert.equal(t.hits.length,0);assert.equal(await t.page.locator('.cookie-banner').count(),0);
 await t.page.locator('.cookie-settings').click();assert.equal(await t.page.locator('#cookie-dialog').isVisible(),true);
 await t.page.locator('#cookie-dialog .cookie-close').first().click();
 checks++;await t.ctx.close();
 // Enabled build waits for permission; refuse, reload, then grant in settings.
 t=await context('enabled');await t.page.goto(t.url+'/request/?category=laptops&intent=quote&utm_source=yandex&email=private%40example.test');
 assert.equal(t.hits.length,0);assert.match(await t.page.locator('[name=comment]').inputValue(),/есть спецификация/);
 await t.page.locator('.cookie-banner [data-analytics-consent=denied]').click();
 await t.page.reload();assert.equal(t.hits.length,0);assert.equal(await t.page.locator('.cookie-banner').isVisible(),false);
 await t.page.locator('.cookie-settings').click();
 await t.page.locator('#cookie-dialog [data-analytics-consent=granted]').click();
 await t.page.waitForFunction(()=>window.metricCalls?.some(a=>a[1]==='hit'));
 assert.equal(t.hits.length,1);
 let calls=await t.page.evaluate(()=>window.metricCalls);
 assert.equal(JSON.stringify(calls).includes('private'),false);
 assert.equal(calls.find(a=>a[1]==='init')[2].webvisor,false);
 checks++;
 // Mock failure, then success. Track only after the endpoint accepts the lead.
 let succeeds=false;let submissions=0;
 await t.page.route('**/api/contact.php',route=>{
  if(route.request().method()==='GET')return route.fulfill({json:{token:'test-token'}});
  submissions++;
  return route.fulfill({status:succeeds?200:503,json:succeeds?{ok:true,requestId:'local-test'}:{ok:false,message:'Тестовая ошибка отправки'}});
 });
 await t.page.locator('[name=name]').fill('Private Name');
 await t.page.locator('[name=phone]').fill('+7 977 000 00 00');
 await t.page.locator('[name=email]').fill('private@example.test');
 await t.page.locator('[name=attachment]').setInputFiles({name:'private-specification.txt',mimeType:'text/plain',buffer:Buffer.from('Local test only')});
 await t.page.locator('[name=consent]').check();
 await t.page.locator('.request-form button[type=submit]').click();
 await t.page.waitForFunction(()=>window.metricCalls?.some(a=>a[2]==='form_submit_error'));
 assert.equal((await t.page.evaluate(()=>window.metricCalls)).some(a=>a[2]==='form_submit_success'),false);
 assert.equal(await t.page.locator('[name=name]').inputValue(),'Private Name');checks++;
 succeeds=true;
 // Copy events immediately before navigation so the next document cannot clear the stub.
 await t.page.exposeFunction('saveMetricCalls',calls=>{globalThis.savedCalls=calls;});
 await t.page.evaluate(()=>window.addEventListener('beforeunload',()=>window.saveMetricCalls(window.metricCalls)));
 await t.page.locator('.request-form button[type=submit]').click();await t.page.waitForURL('**/thanks/');
 assert.equal(submissions,2);
 assert.equal(globalThis.savedCalls.filter(a=>a[2]==='form_submit_success').length,1);
 assert.equal(JSON.stringify(globalThis.savedCalls).includes('Private Name'),false);
 assert.equal(JSON.stringify(globalThis.savedCalls).includes('private-specification'),false);
 assert.equal(JSON.stringify(globalThis.savedCalls).includes('private@example'),false);
 await t.page.waitForFunction(()=>window.metricCalls?.some(a=>a[1]==='hit'));
 assert.equal((await t.page.evaluate(()=>window.metricCalls)).some(a=>a[2]==='form_submit_success'),false);checks++;
 await t.page.locator('.cookie-settings').click();await t.page.locator('#cookie-dialog [data-analytics-consent=denied]').click();
 await t.page.waitForFunction(()=>window.metricCalls?.some(a=>a[1]==='destruct'));
 const before=await t.page.evaluate(()=>window.metricCalls.length);
 await t.page.evaluate(()=>window.ligusAnalytics.track('phone_click'));
 assert.equal(await t.page.evaluate(()=>window.metricCalls.length),before);checks++;await t.ctx.close();
 // Withdrawal while the SDK is in flight must prevent later initialization.
 t=await context('enabled',{width:390,height:844},true);await t.page.goto(t.url+'/');
 await t.page.locator('.cookie-banner [data-analytics-consent=granted]').click();
 await t.page.locator('.cookie-settings').click();await t.page.locator('#cookie-dialog [data-analytics-consent=denied]').click();
 await t.page.waitForTimeout(450);assert.equal(await t.page.evaluate(()=>window.metricCalls?.length||0),0);checks++;await t.ctx.close();
 // Inspect responsive geometry and save real renders of the changed content.
 for(const width of [390,781,1440]){
  t=await context('preview',{width,height:900});
  for(const path of ['/','/production/laptops/','/services/']){
   await t.page.goto(t.url+path);await t.page.evaluate(()=>document.fonts.ready);
   const dimensions=await t.page.evaluate(()=>({w:innerWidth,body:document.documentElement.scrollWidth}));
   assert.ok(dimensions.body<=dimensions.w+1,JSON.stringify({path,width,...dimensions}));
   assert.equal(await t.page.locator('h1').count(),1);
   if(path.includes('laptops'))await t.page.screenshot({path:resolve(qa,`laptops-${width}.png`),fullPage:true});
   checks++;
  }
  await t.ctx.close();
 }
 assert.deepEqual(failures,[]);
 const report=JSON.stringify({checks,externalRequests:'mocked only',emailsSent:0,errors:failures},null,2);
 await writeFile(resolve(qa,'results.json'),report+'\n');console.log(report);
}finally{await browser.close();for(const s of servers)await new Promise(r=>s.close(r));}

const {chromium}=require('playwright');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
// Run with Playwright available to Node. The replay supplies the web directory.
const [webDirectory,evidenceDirectory,plotlyFile]=process.argv.slice(2);
if(!webDirectory||!evidenceDirectory) throw Error('Supply a preview directory and an evidence directory');
const root=path.resolve(webDirectory), output=path.resolve(evidenceDirectory);
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  const file=path.join(root,pathname==='/'?'index.html':pathname.slice(1));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return}
  res.setHeader('Content-Type',file.endsWith('json')?'application/json':'text/html; charset=utf-8');
  fs.createReadStream(file).pipe(res);
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.MORNING_CHROME_PATH||undefined,headless:true});
  try{
  const measurements=[];
  for(const [width,height] of [[390,844],[844,390],[768,1024],[1280,900]]){
    const ctx=await browser.newContext({viewport:{width,height},isMobile:true,deviceScaleFactor:1});
    if(plotlyFile) await ctx.route('https://cdn.plot.ly/plotly-2.27.0.min.js',r=>r.fulfill({path:plotlyFile,contentType:'text/javascript'}));
    const page=await ctx.newPage(), errors=[];page.on('pageerror',e=>errors.push(String(e)));
    await page.goto('http://127.0.0.1:'+server.address().port+'/',{waitUntil:'networkidle'});
    await page.waitForFunction(()=>typeof DS!=='undefined' && DS?.construction_risk);
    assert.equal(await page.evaluate(()=>document.documentElement.clientWidth),width);
    for(const tab of await page.evaluate(()=>TABS.map(t=>t[0]))){
      await page.evaluate(t=>setTab(t),tab);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+1),tab+' overflow');
    }
    await page.evaluate(()=>setTab('risk'));
    await page.evaluate(()=>document.fonts.ready);
    const panel=page.locator('#constructionRisk');
    assert.equal(await panel.locator('[data-worst]').innerText(),await page.evaluate(()=>pctSigned(DS.construction_risk.worst.total,2)));
    await panel.scrollIntoViewIfNeeded();
    if(width===390||width===1280) await panel.screenshot({path:path.join(output,'risk-'+width+'.png')});
    const sections=panel.locator(':scope > details');
    await sections.nth(0).locator(':scope > summary').click();
    const rows=sections.nth(0).locator('tbody > tr');
    assert.equal(await rows.count(),await page.evaluate(()=>DS.construction_risk.scenarios.length));
    assert.deepEqual(await rows.locator('[data-impact]').allInnerTexts(),await page.evaluate(()=>DS.construction_risk.scenarios.map(s=>isNum(s.total)?pctSigned(s.total,2):'Unavailable')));
    assert.deepEqual(await rows.locator('[data-coverage]').allInnerTexts(),await page.evaluate(()=>DS.construction_risk.scenarios.map(s=>['shocked','flat','unpriced'].map(k=>pct(s.coverage[k],2)).join(' / '))));
    assert.match(await panel.locator('[data-gated]').innerText(), /50% shift to SHY: \+3\.04%/);
    await rows.first().locator('summary').click();
    assert.ok((await rows.first().innerText()).includes('Unpriced holdings'));
    await rows.first().locator('summary').click();
    if(width===1280) await sections.nth(0).locator('table').screenshot({path:path.join(output,'scenarios-1280.png')});
    await sections.nth(0).locator(':scope > summary').click();
    await sections.nth(1).locator(':scope > summary').click();
    assert.equal(await sections.nth(1).locator('tbody > tr').count(),await page.evaluate(()=>DS.construction_risk.gaps.length));
    assert.match(await panel.locator('[data-proxy]').innerText(), /8\.79% of NAV.*NAV loss 0\.88%/);
    if(width===1280) await sections.nth(1).screenshot({path:path.join(output,'gap-sizing-1280.png')});
    const detail=await panel.evaluate(panel=>{
      const viewport=document.documentElement.clientWidth;
      const visible=[...panel.querySelectorAll('*')].filter(e=>e.checkVisibility()&&e.getBoundingClientRect().height);
      const texts=visible.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
      const overflow=visible.filter(e=>{const rect=e.getBoundingClientRect();return (rect.left< -1||rect.right>viewport+1)&&!e.closest('.stress-scroll')}).length;
      const p=panel.querySelector(':scope > p'),canvas=document.createElement('canvas').getContext('2d');
      const style=getComputedStyle(p);
      canvas.font=style.fontWeight+' '+style.fontSize+' '+style.fontFamily;
      return {width:viewport,scroll:document.documentElement.scrollWidth,minFont:Math.min(...texts.map(e=>parseFloat(getComputedStyle(e).fontSize))),overflow,charsPerLine:Math.round(p.clientWidth/(canvas.measureText('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').width/62))};
    });
    console.log(detail);
    assert.ok(detail.minFont>=11&&detail.overflow===0&&detail.scroll===width);
    assert.ok(detail.charsPerLine<=(width===390?55:80));
    assert.deepEqual(errors,[]);
    measurements.push(detail);
    await ctx.close();
  }
  fs.writeFileSync(path.join(output,'viewports.json'),JSON.stringify(measurements,null,2));
  }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});

const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const path=require('node:path');
const root=path.resolve(__dirname,'../docs');
const files={'/':'index.html','/data/combined-model.json':'data/combined-model.json',
  '/data/portfolio-multi-strategy-portfolio.json':'data/portfolio-multi-strategy-portfolio.json'};
const server=http.createServer((req,res)=>{
  const file=files[req.url];
  if(!file){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',file.endsWith('json')?'application/json':'text/html; charset=utf-8');
  fs.createReadStream(path.join(root,file)).pipe(res);
});
async function run(){
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'chrome'});
  try{
    for(const [width,height] of [[390,844],[844,390],[768,1024],[1280,900]]){
      const page=await browser.newPage({viewport:{width,height},isMobile:width<900});
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.goto(process.argv[2]||'http://127.0.0.1:'+server.address().port+'/',{waitUntil:'domcontentloaded'});
      await page.locator('.combined-value').first().waitFor();
      await page.evaluate(()=>document.fonts.ready);
      const metrics=await page.evaluate(()=>{
        const els=[...document.querySelectorAll('#tabContent *')],w=document.documentElement.clientWidth;
        const t=els.filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
        const p=document.querySelectorAll('.combined-note')[2],ctx=document.createElement('canvas').getContext('2d');
        ctx.font=getComputedStyle(p).font;
        return {width:w,overflow:els.filter(e=>e.getBoundingClientRect().right>w+1).length,
          extra:document.documentElement.scrollWidth-w,minimum:Math.min(...t.map(e=>parseFloat(getComputedStyle(e).fontSize))),
          chars:Math.round(p.clientWidth*62/ctx.measureText('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').width)};
      });
      assert.equal(metrics.width,width);assert.equal(metrics.extra,0);assert.equal(metrics.overflow,0);assert.ok(metrics.minimum>=11);
      assert.equal(await page.locator('.combined-table tbody tr').count(),8);
      assert.deepEqual(await page.locator('.combined-value').allTextContents(),await page.evaluate(()=>[combined.target_pct,combined.equity_pct].map(v=>v.toFixed(2)+'%')));
      await page.getByRole('button',{name:'Core return attribution →'}).click();
      assert.ok(await page.locator('#attrChart').count());
      assert.equal(await page.locator('#mhSub').textContent().then(s=>s.startsWith('Breadth ETF core')),true);
      await page.locator('[data-tab="combined"]').click();
      await page.evaluate(()=>{combined.expires_utc='2000-01-01T00:00:00Z';renderCombined();});
      assert.match(await page.locator('#tabContent').innerText(),/Historical snapshot/);
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify(metrics));
      await page.close();
    }
  }finally{await browser.close();}
}
run().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>server.close());

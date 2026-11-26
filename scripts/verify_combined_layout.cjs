const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const path=require('node:path');
const root=path.resolve(__dirname,'../docs');
const files={'/':'index.html','/data/combined-model.json':'data/combined-model.json',
  '/data/combined-backtest.json':'data/combined-backtest.json',
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
      await page.locator('[data-tab="backtest"]').click();
      await page.locator('#gapStudyPlot .main-svg').first().waitFor();
      const study=await page.evaluate(()=>{
        const p=document.querySelector('#studyPlot'),b=combinedStudy,w=document.documentElement.clientWidth;
        const tables=[...document.querySelectorAll('#tabContent table')];
        const els=[...document.querySelectorAll('#tabContent p,#tabContent td,#tabContent th,#tabContent h2,#tabContent .js-plotly-plot,#tabContent .xtick text,#tabContent .ytick text')];
        const daily=b.exhibit.daily,areas=document.querySelector('#overlayStudyPlot').data;
        const gap=document.querySelector('#gapStudyPlot').data.find(trace=>trace.name==='Drawdown gap');
        const reconciled=daily.dates.every((day,i)=>{
          const sentiment=daily.sentiment[i],breadth=daily.thrust[i];
          return areas[4].x[i]===day && areas[4].y[i]===sentiment+breadth &&
            areas[0].y[i]+areas[2].y[i]===sentiment && areas[1].y[i]+areas[3].y[i]===breadth &&
            gap.x[i]===day && gap.y[i]===daily.gap[i];
        });
        const prose=els.find(e=>e.tagName==='P'&&e.textContent.length>110);
        const ctx=document.createElement('canvas').getContext('2d');ctx.font=getComputedStyle(prose).font;
        return {reconciled,closes:daily.dates.length,lines:p.data.length,points:p.data[0].x.length,expected:b.curve.dates.length,
          finish:p.data[0].y.at(-1),end:b.stats.combined.end,rows:tables.map(t=>t.tBodies[0].rows.length),
          width:w,extra:document.documentElement.scrollWidth-w,over:els.filter(e=>e.getBoundingClientRect().right>w+1).length,
          minimum:Math.min(...els.map(e=>parseFloat(getComputedStyle(e).fontSize))),
          chars:Math.round(prose.clientWidth*62/ctx.measureText('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').width)};
      });
      assert.equal(study.lines,3);assert.equal(study.points,study.expected);assert.ok(Math.abs(study.finish-study.end)<.00001);
      assert.ok(study.reconciled);assert.equal(study.closes,2019);
      const copy=await page.locator('#tabContent').innerText();
      for(const label of ['8.1 basis points a year','0.58 pp','4 of 5','2 of 5','13.79 pp','3.96 pp'])assert.ok(copy.includes(label),label);
      assert.deepEqual(await page.locator('#tabContent table').first().locator('tbody tr').allTextContents(),[
        'Core alone78.73%16.49%95.22%','Core + Crowd Sentiment90.02%5.26%95.22%']);
      assert.ok(copy.includes('5.20% request at each rebalance produced 95.16%'));
      assert.deepEqual(study.rows,[2,5,4,2]);assert.equal(study.width,width);assert.equal(study.extra,0);assert.equal(study.over,0);
      assert.ok(study.minimum>=11);console.log('backtest',JSON.stringify(study));
      const nav=await page.locator('#tabBar').evaluate(bar=>{
        const box=bar.getBoundingClientRect(),tabs=[...bar.querySelectorAll('button')];
        return {clipped:tabs.filter(tab=>{
          const r=tab.getBoundingClientRect();
          return r.left<box.left-1||r.right>box.right+1||r.bottom>box.bottom+1||tab.scrollWidth>tab.clientWidth+1;
        }).length,rows:new Set(tabs.map(tab=>tab.offsetTop)).size};
      });
      assert.equal(nav.clipped,0);
      await page.getByRole('button',{name:'Methodology',exact:true}).click();
      assert.equal(await page.locator('.tab.active').innerText(),'Methodology');
      await page.locator('[data-tab="allocation"]').click();
      await page.locator('#allocHist .main-svg').first().waitFor();
      const allocation=await page.locator('#allocHist').evaluate(el=>{
        const h=DS.trades.alloc_history,vals=Object.values(h.sleeve_weights);
        const raw=el.data.every((t,j)=>!t.stackgroup&&t.line.shape==='hv'&&t.x.length===h.dates.length&&t.y.every((v,i)=>v===100*vals[j][i]));
        return {raw,sleeves:el.data.length,weeks:h.dates.length,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
      });
      assert.ok(allocation.raw);assert.equal(allocation.sleeves,6);assert.equal(allocation.overflow,0);
      await page.getByRole('button',{name:'By holding',exact:true}).click();
      await page.locator('#allocTicker').selectOption('SHY');
      await page.locator('#allocWinBtns').getByRole('button',{name:'1Y',exact:true}).click();
      assert.ok(await page.locator('#allocHist').evaluate(el=>{
        const t=el.data[0],h=DS.trades.alloc_history;
        return el.data.length===1&&t.name==='SHY'&&!t.stackgroup&&t.x.length<h.dates.length&&t.y.every((v,i)=>v===100*h.weights.SHY[h.dates.indexOf(t.x[i])]);
      }));
      console.log('allocation/navigation',JSON.stringify({width,...allocation,...nav}));
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify(metrics));
      await page.close();
    }
  }finally{await browser.close();}
}
run().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>server.close());

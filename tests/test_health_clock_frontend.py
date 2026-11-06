"""Execute the actual template health clock in Node, not a duplicate model.

Node is already present on the development host and GitHub-hosted runners.
All dates are ISO UTC; JavaScript numeric months are not constructed.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess

TEMPLATE = Path(__file__).resolve().parents[1] / "template.html"


def test_executable_frontend_expiry_and_lifecycle_contract():
    node = shutil.which("node")
    assert node, "Node.js is required to execute the frontend health-clock regressions"
    template = TEMPLATE.read_text(encoding="utf-8")
    block = re.search(r"/\* HEALTH_CLOCK_START[\s\S]*?/\* HEALTH_CLOCK_END \*/", template)
    assert block, "The executable health-clock block is missing"
    script = "const block = " + json.dumps(block.group()) + ";\n" + r"""
'use strict';
const assert=require('node:assert/strict');
const vm=require('node:vm');
let now=Date.parse('2026-11-06T02:30:00Z'), nextTimer=0;
const timers=new Map(), events={window:{},document:{}}, renders=[];
class ClockDate extends Date { static now(){return now;} }
const add=(scope,name,fn)=>{(events[scope][name]??=[]).push(fn);};
const context={Date:ClockDate,console,DS:null,state:{tab:'health'},
 window:{addEventListener:(name,fn)=>add('window',name,fn)},
 document:{hidden:false,addEventListener:(name,fn)=>add('document',name,fn)},
 setTimeout:(fn,delay)=>{const id=++nextTimer;timers.set(id,{fn,delay});return id;},
 clearTimeout:id=>timers.delete(id),
 renderMasthead:h=>renders.push(['masthead',h]),
 renderStaleBanner:h=>renders.push(['banner',h]),
 renderHealth:h=>renders.push(['health',h])};
vm.createContext(context);vm.runInContext(block,context);
const clone=x=>JSON.parse(JSON.stringify(x));
const base={meta:{live_asOf:'2026-11-04',built_at_utc:'2026-11-06T02:00:00Z',source_blobs:{live:'abc'}},
 equity:{live:{dates:['2026-11-04'],equity:[2.899593]}},health:{level:'ok',ok:true,
 checked_at:'2026-11-06',checked_at_utc:'2026-11-06T02:00:00Z',valid_until_utc:'2026-11-06T21:00:00Z',
 feeds:[{feed:'NAV',level:'ok',bday_lag:0,budget_bdays:0}],messages:[]}};
const effective=(d,at=now)=>context.effectiveHealth(d,at);
const expiry=Date.parse(base.health.valid_until_utc);
assert.equal(effective(base,expiry-1).level,'ok');
for(const at of [expiry,expiry+1]){
 const h=effective(base,at);assert.equal(h.level,'warn');assert.equal(h.ok,false);
 assert.equal(h.assessment_current,false);assert.equal(h.assessment_expired,true);
 assert.equal(h.feeds[0].status_label,'UNVERIFIED');assert.match(h.messages[0],/expired/);
 assert(!h.messages.some(m=>/NAV is stale/.test(m)));
}
for(const level of ['warn','stale']){
 const d=clone(base);d.health.level=level;d.health.ok=false;d.health.feeds[0].level=level;
 assert.equal(effective(d,expiry).level,level);
}
const malformed=[null,undefined,'','2026-02-30T02:00:00Z','2026-13-06T02:00:00Z',
 '2026-11-06T25:00:00Z','2026-11-06T02:00:00','2026-11-06','not a date',17];
for(const value of malformed){
 for(const field of ['checked_at_utc','valid_until_utc']){
  const d=clone(base);d.health[field]=value;assert.equal(effective(d).level,'warn');
 }
}
for(const end of ['2026-11-06T01:59:59Z','2026-11-06T02:00:00Z','2027-11-06T21:00:00Z']){
 const d=clone(base);d.health.valid_until_utc=end;assert.equal(effective(d).level,'warn');
}
const future=clone(base);future.health.checked_at_utc='2026-11-06T03:00:00Z';
assert.equal(effective(future).level,'warn');assert.match(effective(future).messages[0],/ahead/);
const mismatched=clone(base);mismatched.health.checked_at='2026-11-05';assert.equal(effective(mismatched).level,'warn');
const failed=clone(base);failed.health.validity_error='calendar unavailable';assert.equal(effective(failed).level,'warn');
assert.equal(effective(base,NaN).level,'warn');
const legacy=clone(base);delete legacy.health.checked_at_utc;delete legacy.health.valid_until_utc;
assert.equal(effective(legacy).level,'warn');assert.match(effective(legacy).messages[0],/no valid/);
const before=JSON.stringify(base);effective(base,expiry);effective(base,expiry+1000);assert.equal(JSON.stringify(base),before);
assert.equal(effective(base,expiry).feeds[0].bday_lag,0);

// An open tab must transition at the deadline and keep only one bounded timer.
context.DS=clone(base);now=expiry-1;context.startHealthClock();
assert.equal(timers.size,1);assert.equal([...timers.values()][0].delay,1);
assert.deepEqual(renders.slice(-3).map(x=>x[0]),['masthead','banner','health']);
assert(renders.slice(-3).every(x=>x[1].level==='ok'));
now=expiry;[...timers.values()][0].fn();assert.equal(timers.size,1);
assert(renders.slice(-3).every(x=>x[1].level==='warn'));
assert.equal([...timers.values()][0].delay,60000);
context.startHealthClock();assert.equal(events.window.focus.length,1);assert.equal(events.window.pageshow.length,1);
assert.equal(events.document.visibilitychange.length,1);

// Resume and back-forward restoration recheck immediately, without touching charts.
for(const [scope,event] of [['window','focus'],['window','pageshow'],['document','visibilitychange']]){
 now=expiry-1;context.DS=clone(base);context.refreshHealthSurfaces();
 now=expiry;events[scope][event][0]();assert(renders.slice(-3).every(x=>x[1].level==='warn'));
}
context.document.hidden=true;const count=renders.length;events.document.visibilitychange[0]();
assert.equal(renders.length,count);context.document.hidden=false;

// A callback scheduled for an old dataset must consult the replacement dataset.
const oldCallback=[...timers.values()][0].fn;
context.DS=clone(base);context.DS.health.checked_at_utc='2026-11-06T21:00:00Z';
context.DS.health.valid_until_utc='2026-11-07T00:00:00Z';now=expiry+1;
context.refreshHealthSurfaces();oldCallback();assert(renders.slice(-3).every(x=>x[1].level==='ok'));
context.state.tab='overview';const n=renders.length;context.refreshHealthSurfaces();
assert.deepEqual(renders.slice(n).map(x=>x[0]),['masthead','banner']);
assert.equal(timers.size,1);
console.log('PASS: executable health expiry, malformed metadata, preservation and lifecycle checks');
"""
    result = subprocess.run([node, "-"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout


def test_all_health_surfaces_use_the_effective_assessment():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "const hl = DS.health.level" not in template
    assert "const h=DS.health" not in template
    assert "function renderMasthead(h=effectiveHealth(DS))" in template
    assert "function renderStaleBanner(h=effectiveHealth(DS))" in template
    assert "function renderHealth(h=effectiveHealth(DS))" in template
    assert "f.status_label||f.level.toUpperCase()" in template
    assert "Feed lags below describe the last build-time check." in template
    assert "renderTab(); startHealthClock();" in template

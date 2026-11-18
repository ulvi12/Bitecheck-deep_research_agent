const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=readFileSync(require('node:path').join(__dirname,'..','index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(n=>n.textContent||'').join('');}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(key,value){this.attributes[key]=value;}
}
const document={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};
const helpers=script.slice(script.indexOf('function el('),script.indexOf('function a('));
const functions=script.slice(script.indexOf('const toolNames='),script.indexOf('try{const old='));
const context=vm.createContext({document});
vm.runInContext(helpers+functions,context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));

// Sending and restoring turns use the same entry function. Neither may hide
// the welcome section; research and answers follow suggested questions in the document.
const welcome=new Element('section'),conversation=new Element('div');welcome.hidden=false;
context.$=id=>({welcome,conversation}[id]);
vm.runInContext(script.slice(script.indexOf('function entry('),script.indexOf('function result(')),context);
context.entry('Compare US and EU food');context.entry('Follow-up question');
assert.equal(welcome.hidden,false);assert.equal(conversation.children.length,2);
assert.ok(html.indexOf('id="conversation"')>html.indexOf('</aside>'));
const plate=html.match(/<svg class="food-art"[\s\S]*?<\/svg>/)[0];
assert.ok(!plate.includes('href="#croissant"'));
assert.match(html,/<button id="send"[\s\S]*?href="#croissant"/);

(async()=>{
  let time=0,interval,resolvePoll,pendingTimeout,cancelledInterval=false,cancelledTimeout=false;
  const root=new Element('div');
  const stop=context.startResearchProgress(root,'request',{
    now:()=>time,every:fn=>(interval=fn,1),cancelEvery:()=>{cancelledInterval=true},
    after:fn=>(pendingTimeout=fn,2),cancelAfter:()=>{cancelledTimeout=true},
    getProgress:()=>new Promise(resolve=>{resolvePoll=resolve})
  });
  const phase=root.children[1],clock=root.children[2];
  const shown=[];
  // The first network response is held for 3.7 seconds. The clock must still
  // display every intervening second, without waiting for the progress poll.
  for(time=0;time<=3700;time+=100){interval();if(shown.at(-1)!==clock.textContent)shown.push(clock.textContent)}
  assert.deepEqual(shown,['0s','1s','2s','3s']);
  resolvePoll({active_agents:['Writer'],sources_read:4});await flush();
  assert.match(phase.textContent,/Writing and checking.*4 sources read/);
  assert.equal(clock.textContent,'3s');assert.equal(typeof pendingTimeout,'function');
  stop();assert.ok(cancelledInterval);assert.ok(cancelledTimeout);

  // A response arriving after completion must neither replace the status nor
  // schedule another poll against a removed progress node.
  let lateResolve,scheduled=0;
  const lateRoot=new Element('div');
  const stopLate=context.startResearchProgress(lateRoot,'late',{
    now:()=>0,every:()=>1,cancelEvery:()=>{},after:()=>{scheduled++},cancelAfter:()=>{},
    getProgress:()=>new Promise(resolve=>{lateResolve=resolve})
  });
  stopLate();lateResolve({active_agents:['Writer'],sources_read:99});await flush();
  assert.equal(lateRoot.children[1].textContent,'Starting research…');assert.equal(scheduled,0);

  // Failed progress requests must not stop the clock or prevent future polls.
  let errorTick,errorTime=0,retry=false;
  const errorRoot=new Element('div');
  const stopError=context.startResearchProgress(errorRoot,'error',{
    now:()=>errorTime,every:fn=>(errorTick=fn,1),cancelEvery:()=>{},after:()=>{retry=true;return 2},cancelAfter:()=>{},
    getProgress:async()=>{throw Error('offline')}
  });
  await flush();errorTime=2100;errorTick();
  assert.equal(errorRoot.children[2].textContent,'2s');assert.ok(retry);stopError();

  const activity=new Element('div');
  context.renderActivity([
    {agent:'Product Researcher',name:'search_sources',status:'complete',args:{q:'Fanta'},result:'{"source_ids":["s1"]}'},
    {agent:'Evidence Researcher',name:'read_source',status:'complete',args:{id:'s1'},result:'Evidence'},
    {agent:'Product Researcher',name:'normalize_label',status:'complete',args:{sugar:4},result:'{}'}
  ],activity);
  const trace=activity.children[0],groups=trace.children[1].children;
  assert.equal(trace.tag,'details');assert.equal(trace.children[0].textContent,'Research activity');
  assert.equal(groups.length,2);assert.equal(groups[0].tag,'section');
  assert.equal(groups[0].children[0].tag,'h3');assert.equal(groups[0].children.length,3);
  assert.equal(groups[0].children[1].className,'research-call');
  assert.match(groups[0].children[1].children[0].textContent,/Search for sources/);
  assert.match(groups[0].children[1].children[1].textContent,/"s1"/);
  console.log('Passed: persistent intro, starter placement, plate/send illustrations, independent clock, polling cleanup, nested research groups');
})().catch(e=>{console.error(e);process.exitCode=1});

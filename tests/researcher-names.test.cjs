const assert=require('node:assert/strict'),vm=require('node:vm');
const html=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0],context=vm.createContext({});
vm.runInContext(script.slice(script.indexOf('function activityGroups('),script.indexOf('function renderActivity(')),context);
const labels=calls=>Array.from(context.activityGroups(calls),g=>g.label);
assert.deepEqual(labels([
 {agent:'Evidence Researcher 3'},{agent:'Product Researcher 1'},{agent:'Regulation Researcher 2'},
 {agent:'Product Researcher 4'},{agent:'Product Researcher 5'},{agent:'Regulation Researcher 6'}
]),['Product Researcher','Regulation Researcher','Evidence Researcher','Product Researcher 2','Product Researcher 3','Regulation Researcher 2']);
assert.deepEqual(labels([
 {agent:'Evidence Researcher',task_order:3},{agent:'Product Researcher 2',task_order:4},
 {agent:'Product Researcher',task_order:1},{agent:'Regulation Researcher',task_order:2}
]),['Product Researcher','Regulation Researcher','Evidence Researcher','Product Researcher 2']);
const calls=[{agent:'Product Researcher 1',name:'search_sources'},{agent:'Product Researcher 1',name:'extract_label'}];
assert.deepEqual(labels([{agent:'Product Researcher 2',task_order:4}]),['Product Researcher 2']);
assert.equal(context.activityGroups(calls).length,1);assert.equal(context.activityGroups(calls)[0].calls.length,2);
assert.equal(calls[0].agent,'Product Researcher 1','Saved raw trace identifiers must stay intact');
assert.deepEqual(labels([{agent:'Writer'},{agent:'Lead'},{agent:'Clarifier'},{agent:'Product Researcher 7'},{agent:'Citation Reviewer'}]),['Clarifier','Lead','Product Researcher','Writer','Citation Reviewer']);
console.log('Passed: per-specialty display counts, task-creation order, legacy saved traces, and grouped steps');

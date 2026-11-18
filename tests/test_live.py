import asyncio, hashlib, json, unittest
from unittest.mock import patch
import httpx
from evidence import EvidenceStore, normalize_nutrients, checked_url, MARKETS
from agents import RunState, run_research, ids_in_result, GEOGRAPHY_POLICY
from app import app, progress_runs

PAGE='Official manufacturer label Germany. Per 100 g: sugars 20 g, sodium 10 mg. Ingredients sugar, cocoa. '*5
URL='https://example.com/label'
SID='web-'+hashlib.sha256(URL.encode()).hexdigest()[:12]

class EvidenceTests(unittest.TestCase):
 def test_empty_request_local_store(self):
  self.assertEqual(EvidenceStore().sources,{})
  self.assertEqual(set(MARKETS),{'US','FR','DE','IT','ES','NL','GB'})
 def test_live_search_fetch_and_isolation(self):
  with patch('evidence.grounded_search',return_value=([{'uri':URL,'title':'label'}],['query'],'')) as search, patch('evidence.fetch_page',return_value=(URL,PAGE)) as fetch:
   a,b=EvidenceStore(),EvidenceStore()
   r=a.search_sources('new question'); self.assertEqual(len(ids_in_result(r)),1)
   self.assertEqual(b.sources,{})
   b.search_sources('new question');self.assertEqual(search.call_count,2);self.assertEqual(fetch.call_count,2)
 def test_unread_candidates_cannot_be_cited(self):
  self.assertFalse(ids_in_result({'id':'a','url':URL,'content':''}))
 def test_italian_page_cannot_be_normalized_as_german(self):
  s=EvidenceStore()
  with patch('evidence.fetch_page',return_value=('https://example.com/it/it/product',PAGE)):
   page=s.read_source(url='https://example.com/it/it/product')
  with self.assertRaisesRegex(ValueError,'localized for Italy'):
   s.run_tool('normalize_label',{'name':'Food','market':'DE','source_id':page['id'],'basis_amount':100,'basis_unit':'g','nutrients':{'sugars_g':20}})
 def test_missing_values_and_salt_conversion(self):
  r=normalize_nutrients({'basis_amount':100,'basis_unit':'g','nutrients':{'salt_g':.1,'sugars_g':None}})
  self.assertEqual(r['sodium_mg'],40);self.assertIsNone(r['sugars_g'])
 def test_private_fetch_rejected(self):
  with self.assertRaises(ValueError):checked_url('http://localhost/test')
  with self.assertRaises(ValueError):checked_url('https://127.0.0.1/')
 def test_normalize_requires_fetched_source_and_present_numbers(self):
  s=EvidenceStore(); p={'name':'Test','market':'DE','source_id':SID,'basis_amount':100,'basis_unit':'g','nutrients':{'sugars_g':20}}
  with self.assertRaises(ValueError):s.run_tool('normalize_label',p)
  with patch('evidence.fetch_page',return_value=(URL,PAGE)):s.read_source(url=URL)
  r=s.run_tool('normalize_label',p); self.assertEqual(r['record']['normalized_nutrients']['sugars_g'],20)
  with self.assertRaises(ValueError):s.run_tool('normalize_label',{**p,'nutrients':{'sugars_g':99}})

def calls(*items):
 return {'role':'assistant','tool_calls':[{'id':str(i)+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(items)]}
class Fake:
 def __init__(self):self.active=0;self.peak=0;self.leads=0
 async def __call__(self,messages,tools=None,required=False,schema=None):
  system=messages[0]['content']
  if system.startswith('You clarify'):return {'role':'assistant','content':json.dumps({'needs_clarification':False,'question':'','brief':''})}
  if 'You are the Lead' in system:
   self.leads+=1
   return calls(*[('research',{'specialty':x,'question':x}) for x in ('product','regulation','evidence')]) if self.leads==1 else calls(('finish_research',{'reason':'done','gaps':[]}))
  if 'You are the Writer' in system:return {'role':'assistant','content':json.dumps({'verdict':'Comparison','answer':{'text':'The fetched label declares 20 g sugars per 100 g.','source_ids':[SID]},'findings':[],'limitations':['Only the retrieved market was verified.']})}
  if 'You are the Citation Reviewer' in system:return {'role':'assistant','content':'{"supported":true,"issues":[]}'}
  if len(messages)==2:
   self.active+=1;self.peak=max(self.peak,self.active);await asyncio.sleep(.03);self.active-=1
   return calls(('read_source',{'url':URL}))
  return {'role':'assistant','content':json.dumps({'findings':[{'text':'The page states sugar.','source_ids':[SID]}],'gaps':[]})}
class HarnessTests(unittest.IsolatedAsyncioTestCase):
 async def test_health_accepts_default_credentials_project_without_env(self):
  with patch.dict('os.environ', {'GOOGLE_CLOUD_PROJECT':'', 'VERTEXAI_PROJECT':''}), patch('agents.MODEL','vertex_ai/gemini-3.5-flash-lite'), patch('evidence.google.auth.default',return_value=(object(),'cloud-run-project')):
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
    self.assertIs((await client.get('/health')).json()['model_configured'],True)

 async def test_market_selection_policy_reaches_researchers_without_erasing_user_scope(self):
  for question in ('Compare Nutella in the US and EU', 'Compare Nutella only in the US and Italy'):
   with self.subTest(question=question):
    fake=Fake(); delegated=[]; writer=[]
    async def capture(messages,tools=None,required=False,schema=None):
     if 'your_subquestion' in messages[-1].get('content','') and len(messages)==2:
      delegated.append(json.loads(messages[-1]['content']))
     if 'You are the Writer' in messages[0]['content']:
      writer.append(json.loads(messages[-1]['content']))
     return await fake(messages,tools,required,schema)
    state=RunState(EvidenceStore(),completion=capture)
    with patch('evidence.fetch_page',return_value=(URL,PAGE)):
     result=await run_research(state,[{'role':'user','content':question}])
    self.assertEqual(result['status'],'complete');self.assertEqual(len(delegated),3)
    for task in delegated:
     scope=json.loads(task['research_brief'])
     self.assertEqual(scope['user_question'],question)
     self.assertEqual(scope['market_selection_policy'],GEOGRAPHY_POLICY)
     self.assertNotIn('Default product markets:',scope['clarified_scope'])
    self.assertEqual(writer[0]['user_question'],question)
 async def test_parallel_research_uses_request_time_pages(self):
  f=Fake();state=RunState(EvidenceStore(),completion=f)
  with patch('evidence.fetch_page',return_value=(URL,PAGE)):
   result=await run_research(state,[{'role':'user','content':'Compare this food in Germany and Italy'}])
  self.assertEqual(result['status'],'complete');self.assertGreaterEqual(f.peak,3)
  self.assertTrue(result['sources']);self.assertFalse(state.active_agents)
 async def test_global_corpus_routes_are_removed_and_progress_is_scoped(self):
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
   self.assertEqual((await c.get('/sources')).status_code,404)
   self.assertEqual((await c.get('/pairs')).status_code,404)
   self.assertEqual((await c.get('/health')).json()['mode'],'live')
   self.assertEqual((await c.get('/progress/00000000-0000-0000-0000-000000000000')).json()['sources_read'],0)
if __name__=='__main__':unittest.main()

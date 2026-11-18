import asyncio
import unittest
from unittest.mock import patch
import httpx
from agents import RunState
from evidence import EvidenceStore
from app import app, progress_runs
from test_live import Fake, URL, PAGE

class ActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_chat_exposes_live_handoffs_and_keeps_final_snapshot(self):
        fake=Fake();writing,release=asyncio.Event(),asyncio.Event()
        async def completion(messages,*args):
            if 'You are the Writer' in messages[0]['content']:
                writing.set();await release.wait()
            return await fake(messages,*args)
        key='22222222-2222-4222-8222-222222222222'
        with patch('app.RunState',side_effect=lambda store:RunState(store,completion=completion)), patch('evidence.fetch_page',return_value=(URL,PAGE)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                task=asyncio.create_task(client.post('/chat',json={'message':'Compare US and EU labels','request_id':key}))
                try:
                    await asyncio.wait_for(writing.wait(),3)
                    live=(await client.get('/progress/'+key)).json()
                    self.assertIn('Writer',live['activity']['active_agents'])
                    seen={e['node'] for e in live['activity']['events']}
                    self.assertTrue({'clarifier','lead_plan','product','regulation','evidence','lead_check','writer'}<=seen)
                    self.assertTrue(live['sources_read'])
                finally:release.set()
                response=await task
                self.assertEqual(response.json()['status'],'complete')
                final=response.json()['activity']
                self.assertFalse(final['active_agents']);self.assertFalse(final['queued_agents'])
                self.assertEqual(final['events'][-1]['decision'],'approved')
                self.assertEqual((await client.get('/progress/'+key)).json()['status'],'pending')

    async def test_queued_completions_are_not_reported_as_active(self):
        first_started, release = asyncio.Event(), asyncio.Event()
        async def completion(*args):
            first_started.set()
            await release.wait()
            return {'role':'assistant','content':'done'}
        state=RunState(EvidenceStore(),completion=completion,slots=asyncio.Semaphore(1))
        first=asyncio.create_task(state.complete('Product Researcher 1',[]))
        await first_started.wait()
        second=asyncio.create_task(state.complete('Evidence Researcher 2',[]))
        await asyncio.sleep(0)
        snapshot=state.activity_snapshot()
        self.assertEqual(snapshot['active_agents'],['Product Researcher 1'])
        self.assertEqual(snapshot['queued_agents'],['Evidence Researcher 2'])
        self.assertEqual(len(snapshot['events']),1)
        release.set();await asyncio.gather(first,second)
        self.assertFalse(state.active_agents);self.assertFalse(state.queued_agents)
        events=state.activity_snapshot()['events']
        self.assertEqual([e['kind'] for e in events],['model_started','model_finished']*2)
        self.assertEqual(events[0]['operation_id'],events[1]['operation_id'])

    async def test_failed_completion_cleans_up_activity(self):
        async def fail(*args):raise RuntimeError('provider failure')
        state=RunState(EvidenceStore(),completion=fail)
        with self.assertRaises(RuntimeError):await state.complete('Writer',[])
        self.assertFalse(state.active_agents);self.assertFalse(state.queued_agents)
        self.assertEqual(state.activity_events[-1]['kind'],'model_failed')

    async def test_progress_exposes_execution_metadata_without_source_bodies(self):
        state=RunState(EvidenceStore());key='11111111-1111-4111-8111-111111111111'
        call=state.start_call('Lead','research',{'specialty':'product','question':'Compare labels'})
        state.finish_call(call,{'content':'PRIVATE_SOURCE_BODY','findings':[]})
        audit=state.start_call('Citation Reviewer','check_report',{'attempt':1})
        state.finish_call(audit,{'supported':False,'issues':['PRIVATE_REVIEW_TEXT']},True)
        progress_runs[key]=state
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get('/progress/'+key)
            self.assertEqual(response.status_code,200)
            events=response.json()['activity']['events']
            self.assertEqual(events[0]['specialty'],'product')
            self.assertEqual(events[-1]['decision'],'revise')
            self.assertNotIn('PRIVATE_SOURCE_BODY',response.text)
            self.assertNotIn('PRIVATE_REVIEW_TEXT',response.text)
            self.assertEqual([e['sequence'] for e in events],[1,2,3,4])
        finally:progress_runs.pop(key,None)

    async def test_chat_retains_final_activity_after_progress_is_removed(self):
        async def fake_run(state,history):
            call=state.start_call('Clarifier','clarify_question',{'message':history[-1]['content']})
            state.finish_call(call,{'needs_clarification':True})
            return {'response':'Which food?','status':'clarification'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            with patch('app.run_research',fake_run):
                response=await client.post('/chat',json={'message':'Food question'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'clarification')
        self.assertEqual(response.json()['activity']['events'][-1]['node'],'clarifier')

if __name__=='__main__':unittest.main()

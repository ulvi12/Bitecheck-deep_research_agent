import json,unittest
from unittest.mock import patch
from agents import RunState,run_research,researcher_name
from evidence import EvidenceStore
from test_live import Fake,calls,URL,PAGE

class ResearcherNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_followups_count_within_specialty_and_keep_creation_order(self):
        fake=Fake();lead_turns=0
        async def completion(messages,*args):
            nonlocal lead_turns
            if 'You are the Lead' in messages[0]['content']:
                lead_turns+=1
                if lead_turns==1:return calls(*[('research',{'specialty':s,'question':s}) for s in ('product','regulation','evidence')])
                if lead_turns==2:return calls(('research',{'specialty':'product','question':'follow-up one'}),('research',{'specialty':'product','question':'follow-up two'}))
                return calls(('finish_research',{'reason':'done','gaps':[]}))
            return await fake(messages,*args)
        state=RunState(EvidenceStore(),completion=completion)
        with patch('evidence.fetch_page',return_value=(URL,PAGE)):
            result=await run_research(state,[{'role':'user','content':'Compare this food in the US and EU'}])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(state.researcher_counts,{'product':3,'regulation':1,'evidence':1})
        self.assertEqual(state.researcher_orders,{'Product Researcher':1,'Regulation Researcher':2,'Evidence Researcher':3,'Product Researcher 2':4,'Product Researcher 3':5})
        for call in state.trace:
            if 'Researcher' in call['agent']:self.assertEqual(call['task_order'],state.researcher_orders[call['agent']])
        for event in state.activity_events:self.assertNotEqual(event['agent'],'Product Researcher 1')

    async def test_first_task_has_no_suffix_and_counts_are_request_local(self):
        self.assertEqual(researcher_name('product',1),'Product Researcher')
        self.assertEqual(researcher_name('product',2),'Product Researcher 2')
        first,second=RunState(EvidenceStore()),RunState(EvidenceStore())
        first.researcher_counts['product']=3
        self.assertEqual(second.researcher_counts,{})

if __name__=='__main__':unittest.main()

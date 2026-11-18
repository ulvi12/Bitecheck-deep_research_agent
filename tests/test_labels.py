import asyncio,json,unittest,hashlib
from unittest.mock import patch,MagicMock
from evidence import EvidenceStore,fetch_page,PageText,PageContent,market_hint
from labels import extract_panels
from agents import RunState,run_research,run_researcher
from test_live import Fake,PAGE,URL,calls

US='''Classic spread
Serving Size: 2 Tbsp. (37g)
Calories200
Total Fat11 g | 14%
Saturated Fat4 g | 20%
Trans Fat0 g
CholesterolLess than 5 mg | 0%
Total Carbohydrates22 g | 8%
Dietary Fiber1 g | 4%
Total Sugars21 g
Includes 19g Added Sugars38%
Protein2 g
Sodium15 mg | 1%
'''
EU='''Classic spread
Durchschnittswerte 100 g
Energie2252 kJ | 539 kcal
Fett30,9 g
davon gesättigte Fettsäuren10,6 g
Kohlenhydrate57,5 g
davon Zucker56,3 g
Eiweiß6,3 g
Salz0,107 g
'''

def source(store,text,url='https://example.com/us/en/product',**extra):
    with patch('evidence.fetch_page',return_value=(url,text)):result=store.read_source(url=url)
    store.sources[result['id']].update(extra)
    return result['id']

class LabelTests(unittest.TestCase):
    def test_full_compact_us_panel_including_added_sugars(self):
        panels=extract_panels(US)
        self.assertEqual(len(panels),1);self.assertEqual(panels[0]['basis_amount'],37)
        values=panels[0]['nutrients'];self.assertEqual(len(values),9)
        self.assertEqual(values['energy_kcal'],200);self.assertEqual(values['added_sugars_g'],19)
        self.assertEqual(values['sodium_mg'],15)

    def test_european_decimals_salt_conversion_and_declared_gaps(self):
        store=EvidenceStore();sid=source(store,EU,'https://example.com/de/de/product')
        result=store.extract_label(sid,'DE','Classic spread')
        normalized=result['record']['normalized_nutrients']
        self.assertEqual(normalized['sodium_mg'],42.8);self.assertEqual(normalized['total_fat_g'],30.9)
        self.assertIsNone(normalized['fiber_g']);self.assertIsNone(normalized['added_sugars_g'])
        self.assertEqual(store.label_coverage()['markets']['DE']['missing_core_fields'],[])

    def test_multiple_bases_require_selection_without_mixing(self):
        second='''Serving size 15 g
Calories80
Total Fat4.6 g
Total Sugars8.4 g
Protein0.9 g
'''
        store=EvidenceStore();sid=source(store,US+second)
        result=store.extract_label(sid,'US','Classic spread')
        self.assertEqual(len(result['candidates']),2);self.assertFalse(store.labels)
        self.assertEqual(result['candidates'][0]['nutrients']['sugars_g'],21)
        self.assertEqual(result['candidates'][1]['nutrients']['sugars_g'],8.4)
        result=store.extract_label(sid,'US','Classic spread',candidate_index=0)
        self.assertEqual(result['record']['basis_amount'],37)

    def test_unknown_inequalities_and_percentages_are_not_exact_values(self):
        panels=extract_panels('Serving size 100 g\nTotal Sugars0 g\nProtein2 g\nDietary Fiber<1 g\nSodium[unreadable]\nTotal Fat14%\n')
        self.assertEqual(panels[0]['nutrients'],{'sugars_g':0,'protein_g':2})
        self.assertEqual(extract_panels('Recipe ingredients sugar flour milk. Per serving: enjoy!'),[])

    def test_belgian_french_and_canadian_french_are_not_france(self):
        self.assertEqual(market_hint('https://example.com/be/fr/product'),'BE')
        self.assertEqual(market_hint('https://example.com/ca/fr/product'),'CA')
        store=EvidenceStore();sid=source(store,EU,'https://example.com/be/fr/product')
        with self.assertRaisesRegex(ValueError,'Belgium'):store.extract_label(sid,'FR','Spread')

    def test_table_boundaries_structured_data_and_discovered_assets(self):
        markup='''<title>Classic spread</title><table><tr><td>Total Sugars</td><td>21 g</td></tr></table>
        <a href="/label.pdf">Nutrition sheet</a><img alt="Nutrition label" src="data:image/gif;base64,x" data-src="/label.png">
        <script type="application/ld+json">{"@type":"Product","name":"Classic spread","nutrition":{"sugarContent":"21 g","servingSize":"37 g"},"unrelatedSecret":"omit"}</script><script>ignore this script</script>'''
        parser=PageText();parser.feed(markup)
        self.assertIn('Total Sugars | 21 g',''.join(parser.parts))
        self.assertIn('sugarContent',parser.structured[0]);self.assertNotIn('unrelatedSecret',parser.structured[0])
        self.assertEqual(parser.assets(parser.links,'https://example.com/product',12)[0]['url'],'https://example.com/label.pdf')
        self.assertEqual(parser.assets(parser.images,'https://example.com/product',8)[0]['url'],'https://example.com/label.png')

    def test_plain_text_and_pdf_sources_have_serializable_titles(self):
        store=EvidenceStore();sid=source(store,US)
        self.assertIsInstance(store.sources[sid]['title'],str)
        json.dumps(store.sources[sid])

    def test_extract_failure_enables_manual_fallback(self):
        store=EvidenceStore();sid=source(store,'A product page with ingredients but no text nutrition panel. '*5)
        self.assertFalse(store.extract_label(sid,'US','Food')['candidates'])
        self.assertIn(sid,store.manual_label_sources)

    def test_a_thinner_repeated_extraction_does_not_erase_a_complete_label(self):
        store=EvidenceStore();sid=source(store,US)
        store.extract_label(sid,'US','Classic spread')
        store.run_tool('normalize_label',{'source_id':sid,'market':'US','name':'Classic spread','basis_amount':37,'basis_unit':'g','nutrients':{'sugars_g':21}})
        self.assertEqual(len(store.label_coverage()['markets']['US']['available_fields']),9)

    def test_search_reads_alternatives_when_top_candidates_lack_a_panel(self):
        links=[{'uri':f'https://example.com/page{i}','title':f'Food {i}'} for i in range(6)]
        def fetch(url):return url,US if url.endswith('page3') else 'A readable page with ingredients but no label values. '*4
        with patch('evidence.grounded_search',return_value=(links,['query'],'')),patch('evidence.fetch_page',side_effect=fetch):
            result=EvidenceStore().search_sources('food US',kind='product')
        self.assertEqual(len(result['results']),5);self.assertTrue(any('Calories200' in s['content'] for s in result['results']))
        self.assertEqual(len(result['other_candidates']),1)

    def test_brand_domain_priority_is_discovered_from_the_live_query(self):
        links=[{'uri':f'https://shop{i}.example.com/acme','title':'Acme label'} for i in range(4)]+[{'uri':'https://www.acme.example/product','title':'Acme official product'}]
        with patch('evidence.grounded_search',return_value=(links,['query'],'')),patch('evidence.fetch_page',side_effect=lambda url:(url,US)):
            store=EvidenceStore();result=store.search_sources('Acme US nutrition ingredients',kind='product')
        self.assertEqual(result['results'][0]['url'],'https://www.acme.example/product')
        self.assertIn('acme.example',store.product_domains)
        self.assertEqual(result['results'][0]['source_role_hint'],'brand-domain candidate')

    def test_image_requires_a_discovered_parent_asset(self):
        store=EvidenceStore();sid=source(store,US)
        with self.assertRaisesRegex(ValueError,'discovered'):store.read_label_image(sid,'https://example.com/guessed.png')

    def test_image_transcription_keeps_parent_market_and_uncertainty(self):
        store=EvidenceStore();url='https://cdn.example.com/label.png'
        sid=source(store,EU,'https://example.com/de/de/product',label_images=[{'url':url,'label':'Nutrition'}])
        image=MagicMock();image.__enter__.return_value=image;image.is_redirect=False;image.headers={'Content-Type':'image/png'};image.iter_content.return_value=[b'PNG fixture']
        reply=MagicMock();reply.json.return_value={'candidates':[{'content':{'parts':[{'text':json.dumps({'transcription':EU,'uncertainties':['Small print may be unclear']})}]}}]}
        credentials=MagicMock();credentials.token='fixture'
        with patch('evidence.checked_url',side_effect=lambda u:u),patch('evidence.requests.get',return_value=image),patch('evidence.requests.post',return_value=reply),patch('google.auth.default',return_value=(credentials,None)),patch.dict('os.environ',{'GOOGLE_CLOUD_PROJECT':'fixture'}):
            result=store.read_label_image(sid,url)
        self.assertEqual(result['reading_method'],'image_transcription');self.assertEqual(result['parent_source_id'],sid)
        self.assertTrue(result['uncertainties'])
        with self.assertRaisesRegex(ValueError,'Germany'):store.extract_label(result['id'],'US','Food')

class PlanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_product_extracts_fetched_panels_before_a_prose_only_finish(self):
        url='https://example.com/us/en/product';sid='web-'+hashlib.sha256(url.encode()).hexdigest()[:12]
        step=0
        async def completion(messages,tools=None,required=False,schema=None):
            nonlocal step
            step+=1
            if step==1:return calls(('search_sources',{'query':'classic spread US nutrition'}))
            if step==2:
                self.assertTrue(required)
                self.assertEqual([t['function']['name'] for t in tools],['extract_label'])
                return calls(('extract_label',{'source_id':sid,'market':'US','name':'Classic spread'}))
            return {'role':'assistant','content':json.dumps({'findings':[{'text':'The fetched US label declares the nutrition values.','source_ids':[sid]}],'gaps':[]})}
        state=RunState(EvidenceStore(),completion=completion)
        with patch('evidence.grounded_search',return_value=([{'uri':url,'title':'Classic spread'}],['query'],'')),patch('evidence.fetch_page',return_value=(url,US)):
            result=await run_researcher(state,'product','Read the US nutrition label',json.dumps({'user_question':'Read the US nutrition label'}),1)
        self.assertEqual(step,3)
        self.assertEqual(len(result['label_coverage']['US']['available_fields']),9)
        self.assertEqual(result['label_coverage']['US']['missing_core_fields'],[])

    async def test_lead_repairs_a_prose_plan_before_parallel_dispatch(self):
        fake=Fake();repaired=False
        async def completion(messages,*args):
            nonlocal repaired
            if 'You are the Lead' in messages[0]['content'] and not repaired:
                repaired=True;return {'role':'assistant','content':'I will split the question into research tasks.'}
            return await fake(messages,*args)
        state=RunState(EvidenceStore(),completion=completion)
        with patch('evidence.fetch_page',return_value=(URL,PAGE)):
            result=await run_research(state,[{'role':'user','content':'Compare this food in the US and EU'}])
        self.assertEqual(result['status'],'complete');self.assertGreaterEqual(fake.peak,3)

if __name__=='__main__':unittest.main()

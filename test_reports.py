import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import main
from src.config import load_config

ROOT = Path(__file__).parent
CATALOG = main.load_catalog(ROOT / 'reports.json')
CFG = load_config(ROOT / 'config.yaml')

class ReportsTests(unittest.TestCase):
    def test_official_html_with_markup_and_entities(self):
        report = dict(CATALOG[0], id='official-guide', url='https://www.anthropic.com/research/example', title='Agents & evaluation')
        response = Mock(url=report['url'], text='<h1>Agents &amp; <em>evaluation</em></h1>')
        with patch('main.requests.get', return_value=response):
            main.verify_source(report)
            response.url = 'https://www.anthropic.com.example.net/fake'
            with self.assertRaises(ValueError):
                main.verify_source(report)

    def test_pdf_must_match_reviewed_bytes(self):
        content = b'%PDF-1.7 reviewed fixture'
        report = dict(CATALOG[0], source_format='pdf', pdf_sha256=main.hashlib.sha256(content).hexdigest())
        response = Mock(url=report['url'], content=content)
        with patch('main.requests.get', return_value=response):
            main.verify_source(report)
            response.content += b'changed'
            with self.assertRaises(ValueError):
                main.verify_source(report)

    def test_relevance_before_recency_and_newer_tiebreak(self):
        r = copy.deepcopy(CATALOG[0])
        old = dict(r, id='old', priority=120, published='2020-01-01')
        new = dict(r, id='new', priority=110, published='2026-09-24')
        self.assertEqual(main.select_report([old,new], {}, '2026-09-25')[0]['id'], 'old')
        new['priority'] = 120
        self.assertEqual(main.select_report([old,new], {}, '2026-09-25')[0]['id'], 'new')

    def test_excludes_future_and_avoids_repeat(self):
        future = dict(CATALOG[0], id='future', published='2099-01-01')
        state = {'reports': {CATALOG[0]['id']: '2026-09-25'}}
        selected, review = main.select_report(CATALOG+[future], state, '2026-09-26')
        self.assertNotIn(selected['id'], [CATALOG[0]['id'], 'future'])
        self.assertFalse(review)

    def test_exhaustion_is_explicit_review(self):
        state = {'reports': {r['id']: f'2026-09-{i+1:02}' for i,r in enumerate(CATALOG)}}
        selected, review = main.select_report(CATALOG, state, '2026-09-25')
        self.assertTrue(review)
        self.assertEqual(selected['id'], CATALOG[0]['id'])
        html, text = main.render(selected, '2026-09-25', CFG, review)
        self.assertIn('间隔复习', text)
        self.assertIn('间隔复习', html)

    def test_html_escapes_content(self):
        r = dict(CATALOG[0], why='<script>bad</script>')
        html, text = main.render(r, '2026-09-25', CFG)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('对应面试问题', text)

    def run_isolated(self, args, result, initial=None):
        with tempfile.TemporaryDirectory() as directory:
            cfg = copy.deepcopy(CFG)
            cfg['reports']['catalog'] = str(ROOT / 'reports.json')
            cfg['reports']['state_path'] = str(Path(directory) / 'state.json')
            state_path = Path(cfg['reports']['state_path'])
            if initial:
                state_path.write_text(json.dumps(initial), encoding='utf-8')
            original = os.getcwd()
            try:
                os.chdir(directory)
                with patch('main.load_config',return_value=cfg), patch('main.load_dotenv'), patch('main.verify_source'), patch('main.send_email', return_value=result) as send, patch('sys.argv', ['main.py']+args):
                    try:
                        main.main()
                    except SystemExit:
                        if result:
                            raise
                    return send.call_count, json.loads(state_path.read_text()) if state_path.exists() else None
            finally:
                os.chdir(original)

    def test_preview_does_not_send_or_advance(self):
        calls, state = self.run_isolated(['--preview'], True)
        self.assertEqual((calls,state), (0,None))

    def test_retired_run_never_sends(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '36087080961'}):
            calls, state = self.run_isolated([], False)
        self.assertEqual((calls, state), (0, None))

    def test_failed_send_does_not_advance(self):
        calls, state = self.run_isolated([], False)
        self.assertEqual((calls,state), (1,None))

    def test_success_and_same_day_retry(self):
        calls, state = self.run_isolated([], True)
        self.assertEqual(calls, 1)
        self.assertEqual(len(state['dates']), 1)
        calls, same = self.run_isolated([], True, state)
        self.assertEqual(calls, 0)
        self.assertEqual(same, state)

if __name__ == '__main__':
    unittest.main()

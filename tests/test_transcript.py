import json
from pathlib import Path
import tempfile
import unittest

from harbor_adapter.transcript import export_transcript


class TranscriptTests(unittest.TestCase):
    def test_preserves_events_and_non_json_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'kimi-code.txt'
            source.write_text('CLI diagnostic\n{"role":"assistant","content":"hello"}\n{broken\n')
            target = export_transcript(source)
            result = json.loads(target.read_text())
            self.assertFalse(source.exists())
            self.assertEqual(result['events'], [{'source_line': 2, 'event': {
                'role': 'assistant', 'content': 'hello'}}])
            self.assertEqual([d['text'] for d in result['diagnostics']],
                             ['CLI diagnostic', '{broken'])

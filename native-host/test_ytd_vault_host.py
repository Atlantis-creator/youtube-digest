import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import ytd_vault_host as host

COLLECTION = Path('Wiki', '收藏')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                          encoding='utf-8', check=True).stdout


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.collection = self.root / COLLECTION
        (self.collection / 'Ali Abdaal').mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def request(self, **overrides):
        payload = {
            'action': 'land',
            'vaultRoot': str(self.root),
            'author': 'Andrew Huberman',
            'title': 'The Art of: True Happiness | Dr. Brooks?',
            'source': 'https://www.youtube.com/watch?v=Gk2ArbsrZwE',
            'segments': [
                {'start': 0, 'text': 'Welcome to the podcast.'},
                {'start': 3725.6, 'text': 'We talk about [happiness] today.'},
            ],
        }
        payload.update(overrides)
        return payload


class CollectionTest(VaultCase):
    def test_missing_vault_is_reported(self):
        result = host.handle(self.request(vaultRoot=str(self.root / 'nope')))
        self.assertFalse(result['ok'])

    def test_missing_collection_is_reported_and_not_created(self):
        (self.collection / 'Ali Abdaal').rmdir()
        self.collection.rmdir()
        for request in [self.request(),
                        {'action': 'findSource', 'vaultRoot': str(self.root), 'source': VIDEO}]:
            result = host.handle(request)
            self.assertFalse(result['ok'], request['action'])
            self.assertIn('Wiki/收藏/', result['error'])
        self.assertFalse(self.collection.exists())

    def test_wiki_list_is_gone_and_a_wiki_parameter_is_ignored(self):
        self.assertFalse(host.handle({'action': 'listWikis', 'vaultRoot': str(self.root)})['ok'])
        result = host.handle(self.request(wiki='个人运转 Wiki'))
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['path'].startswith('Wiki/收藏/Andrew Huberman/'), result['path'])


# Shared with video-transcriber: copied verbatim from its tests/fixtures/, do not edit here alone.
DEDUPE_CASES = json.loads((Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'dedupe_cases.json')
                          .read_text(encoding='utf-8'))['cases']


class SharedDedupeCasesTest(VaultCase):
    """Duplicate detection follows the cases both import tools share."""

    def landed(self, existing):
        shutil.rmtree(self.collection)
        (self.collection / 'Ali Abdaal').mkdir(parents=True)
        old = self.collection / 'Ali Abdaal' / 'old.md'
        old.write_text(f'---\ntitle: Old\nsource: {existing}\nauthor:\n  - Ali Abdaal\n---\n', encoding='utf-8')
        return old.relative_to(self.root).as_posix()

    def test_find_source_matches_every_shared_case(self):
        self.assertEqual(len(DEDUPE_CASES), 24)
        for case in DEDUPE_CASES:
            with self.subTest(case['name']):
                path = self.landed(case['existing'])
                result = host.handle({'action': 'findSource', 'vaultRoot': str(self.root), 'source': case['incoming']})
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['landed'], case['duplicate'])
                if case['duplicate']:
                    self.assertEqual(result['path'], path)

    def test_landing_a_web_source_stops_exactly_on_shared_duplicates(self):
        for index, case in enumerate(c for c in DEDUPE_CASES if c['incoming'].startswith('http')):
            with self.subTest(case['name']):
                path = self.landed(case['existing'])
                result = host.handle(self.request(source=case['incoming'], title=f'Case {index}'))
                self.assertEqual(result['ok'], not case['duplicate'], result)
                if case['duplicate']:
                    self.assertEqual(result['existing'], path)


class LandTest(VaultCase):
    def test_writes_three_key_frontmatter_and_sentence_body(self):
        result = host.handle(self.request())
        self.assertTrue(result['ok'], result)
        note = self.collection / 'Andrew Huberman' / 'The Art of True Happiness  Dr. Brooks.md'
        self.assertEqual(result['path'], note.relative_to(self.root).as_posix())
        text = note.read_text(encoding='utf-8')
        self.assertEqual(text, '\n'.join([
            '---',
            'title: "The Art of: True Happiness | Dr. Brooks?"',
            'source: https://www.youtube.com/watch?v=Gk2ArbsrZwE',
            'author:',
            '  - Andrew Huberman',
            '---',
            '> 来源：[The Art of: True Happiness | Dr. Brooks?](https://www.youtube.com/watch?v=Gk2ArbsrZwE)',
            '',
            '## Transcript',
            '',
            '**00:00:00** · Welcome to the podcast.',
            '',
            '**01:02:05** · We talk about [happiness] today.',
            '',
        ]))

    def test_source_is_written_without_fragment_time_or_tracking(self):
        for index, (given, written) in enumerate([
            ('https://www.youtube.com/watch?v=Gk2ArbsrZwE&t=30s&si=abc#top',
             'https://www.youtube.com/watch?v=Gk2ArbsrZwE'),
            ('https://www.bilibili.com/video/BV1aa411c7xx/?spm_id_from=333.337&vd_source=e57b&t=146.7&p=2',
             'https://www.bilibili.com/video/BV1aa411c7xx/?p=2'),
        ]):
            result = host.handle(self.request(source=given, title=f'Clean {index}'))
            self.assertTrue(result['ok'], result)
            text = (self.root / result['path']).read_text(encoding='utf-8')
            self.assertIn(f'\nsource: {written}\n', text)
            self.assertIn(f']({written})\n', text)

    def test_rejects_a_local_path_as_video_address(self):
        result = host.handle(self.request(source='D:/media/lecture.mp4'))
        self.assertFalse(result['ok'])
        self.assertEqual(list(self.collection.rglob('*.md')), [])

    def test_link_text_escapes_brackets(self):
        host.handle(self.request(title='Why [this] works'))
        note = self.collection / 'Andrew Huberman' / 'Why [this] works.md'
        self.assertIn('> 来源：[Why \\[this\\] works](', note.read_text(encoding='utf-8'))

    def test_duplicate_video_anywhere_in_collection_stops_before_writing(self):
        old = self.collection / 'Ali Abdaal' / 'old.md'
        old.write_text('---\ntitle: x\nsource: "https://youtu.be/Gk2ArbsrZwE"\nmedia_id: youtube:Gk2ArbsrZwE\n---\n', encoding='utf-8')
        result = host.handle(self.request())
        self.assertFalse(result['ok'])
        self.assertEqual(result['existing'], old.relative_to(self.root).as_posix())
        self.assertFalse((self.collection / 'Andrew Huberman').exists())

    def test_same_file_name_stops(self):
        host.handle(self.request())
        result = host.handle(self.request(source='https://www.youtube.com/watch?v=OTHERvideo1'))
        self.assertFalse(result['ok'])
        self.assertIn('existing', result)

    def test_rejects_path_tricks(self):
        self.assertFalse(host.handle(self.request(author='..'))['ok'])
        self.assertFalse(host.handle(self.request(title='///'))['ok'])

    def test_requires_segments(self):
        self.assertFalse(host.handle(self.request(segments=[]))['ok'])

    def test_not_a_git_repo_keeps_file_and_reports_commit_failure(self):
        result = host.handle(self.request())
        self.assertTrue(result['ok'])
        self.assertFalse(result['commit']['ok'])
        self.assertTrue((self.root / result['path']).is_file())


class GitVaultCase(VaultCase):
    def setUp(self):
        super().setUp()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 't@example.com')
        git(self.root, 'config', 'user.name', 'Test')
        (self.root / 'draft.md').write_text('draft', encoding='utf-8')
        (self.root / 'staged.md').write_text('staged', encoding='utf-8')
        git(self.root, 'add', 'staged.md')


class CommitTest(GitVaultCase):
    def test_reuses_existing_author_dir_regardless_of_case(self):
        (self.collection / 'andrew huberman').mkdir()
        result = host.handle(self.request())
        self.assertTrue(result['commit']['ok'], result)
        self.assertEqual(result['path'].split('/')[2], 'andrew huberman')
        subject = git(self.root, 'log', '-1', '--format=%s').strip()
        self.assertEqual(subject, '新增来源：andrew huberman/The Art of True Happiness  Dr. Brooks')
        files = git(self.root, '-c', 'core.quotepath=false', 'show', '--name-only', '--format=').split('\n')
        self.assertEqual([f for f in files if f], [result['path']])

    def test_commits_only_the_new_source(self):
        result = host.handle(self.request())
        self.assertTrue(result['commit']['ok'], result)
        subject = git(self.root, 'log', '-1', '--format=%s').strip()
        self.assertEqual(subject, '新增来源：Andrew Huberman/The Art of True Happiness  Dr. Brooks')
        files = git(self.root, '-c', 'core.quotepath=false', 'show', '--name-only', '--format=').split('\n')
        self.assertEqual([f for f in files if f], [result['path']])
        status = git(self.root, 'status', '--porcelain')
        self.assertIn('A  staged.md', status)
        self.assertIn('?? draft.md', status)


FAKE_STORE = '''
import json, sys
from pathlib import Path
args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
payload = json.loads(Path(args['--payload']).read_text(encoding='utf-8'))
root = Path(args['--vault-root'])
(root / 'store-call.json').write_text(json.dumps({'argv': sys.argv[1:], 'payload': payload}), encoding='utf-8')
if payload['entry'] == 'bad':
    print(json.dumps({'error': 'invalid-payload', 'message': 'nope'}), file=sys.stderr)
    sys.exit(2)
(root / 'word').mkdir(exist_ok=True)
(root / 'word' / (payload['entry'] + '.md')).write_text('# ' + payload['entry'], encoding='utf-8')
source = root / args['--source']
source.write_text(source.read_text(encoding='utf-8') + '\\n## 查询词条\\n', encoding='utf-8')
action = 'deduplicated' if payload['entry'] == 'dup' else 'created'
print(json.dumps({'action': action, 'entry_path': 'word/' + payload['entry'] + '.md',
                  'source_path': args['--source'], 'occurrence_id': 'O1', 'state': '快查'}))
'''

VIDEO = 'https://www.youtube.com/watch?v=Gk2ArbsrZwE'


class AddWordTest(GitVaultCase):
    def setUp(self):
        super().setUp()
        self.store = self.root / 'store.py'
        self.store.write_text(FAKE_STORE, encoding='utf-8')
        self.note = self.collection / 'Ali Abdaal' / 'talk.md'
        self.note.write_text(f'---\ntitle: Talk\nsource: {VIDEO}\n---\n## Transcript\n', encoding='utf-8')
        git(self.root, 'add', 'store.py', self.note.relative_to(self.root).as_posix())
        git(self.root, 'commit', '-q', '-m', 'init', '--', 'store.py', self.note.relative_to(self.root).as_posix())

    def add(self, entry='run', **overrides):
        request = {
            'action': 'addWord', 'vaultRoot': str(self.root), 'storeScript': str(self.store),
            'source': 'https://youtu.be/Gk2ArbsrZwE', 'date': '2026-09-28',
            'payload': {'entry': entry, 'query_form': 'running', 'source_domain': 'general',
                        'source_topic': 'AI 主题', 'occurrence': {'sentence': 'It is **running**.'},
                        'analysis': {}},
        }
        request.update(overrides)
        return host.handle(request)

    def store_call(self):
        return json.loads((self.root / 'store-call.json').read_text(encoding='utf-8'))

    def test_find_source_searches_the_whole_collection(self):
        result = host.handle({'action': 'findSource', 'vaultRoot': str(self.root), 'source': VIDEO})
        self.assertEqual(result, {'ok': True, 'landed': True, 'path': self.note.relative_to(self.root).as_posix()})
        missing = host.handle({'action': 'findSource', 'vaultRoot': str(self.root),
                               'source': 'https://www.youtube.com/watch?v=OTHERvideo1'})
        self.assertEqual(missing, {'ok': True, 'landed': False})

    def test_records_lookup_and_commits_entry_with_transcript(self):
        result = self.add()
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['entryPath'], result['occurrenceId'], result['state']), ('word/run.md', 'O1', '快查'))
        self.assertTrue(result['commit']['ok'], result)
        self.assertEqual(result['vaultName'], self.root.resolve().name)
        call = self.store_call()
        self.assertEqual(call['argv'][0], 'record-lookup')
        self.assertIn(self.note.relative_to(self.root).as_posix(), call['argv'])
        self.assertEqual(call['payload']['source_topic'], 'AI 主题')
        subject = git(self.root, 'log', '-1', '--format=%s').strip()
        self.assertEqual(subject, '查词：run ← talk')
        files = git(self.root, '-c', 'core.quotepath=false', 'show', '--name-only', '--format=').split('\n')
        self.assertEqual(sorted(f for f in files if f), sorted(['word/run.md', self.note.relative_to(self.root).as_posix()]))
        self.assertIn('A  staged.md', git(self.root, 'status', '--porcelain'))

    def test_reuses_saved_domain_and_topic(self):
        self.note.write_text(f'---\ntitle: Talk\nsource: {VIDEO}\nsource_domain: software-engineering\n'
                             'source_topic: "React: 渲染"\n---\n', encoding='utf-8')
        self.assertTrue(self.add()['ok'])
        payload = self.store_call()['payload']
        self.assertEqual((payload['source_domain'], payload['source_topic']), ('software-engineering', 'React: 渲染'))

    def test_deduplicated_lookup_does_not_commit(self):
        head = git(self.root, 'rev-parse', 'HEAD')
        result = self.add('dup')
        self.assertEqual((result['action'], result['commit']), ('deduplicated', None))
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), head)

    def test_store_errors_and_missing_prerequisites_are_reported(self):
        self.assertIn('nope', self.add('bad')['error'])
        self.assertIn('还没存到 Wiki', self.add(source='https://www.youtube.com/watch?v=OTHERvideo1')['error'])
        self.assertIn('找不到', self.add(storeScript=str(self.root / 'missing.py'))['error'])
        self.assertFalse(self.add(date='')['ok'])


class ProtocolTest(unittest.TestCase):
    def test_round_trips_length_prefixed_json(self):
        import io
        message = {'action': 'findSource', 'vaultRoot': '中文'}
        body = json.dumps(message).encode('utf-8')
        stream = io.BytesIO(len(body).to_bytes(4, 'little') + body)
        self.assertEqual(host.read_message(stream), message)
        out = io.BytesIO()
        host.write_message(out, {'ok': True})
        raw = out.getvalue()
        self.assertEqual(json.loads(raw[4:]), {'ok': True})
        self.assertEqual(int.from_bytes(raw[:4], 'little'), len(raw) - 4)


if __name__ == '__main__':
    unittest.main()

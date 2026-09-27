import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import ytd_vault_host as host

SM = host.SOURCE_MATERIAL


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / '个人运转 Wiki' / SM / 'Ali Abdaal').mkdir(parents=True)
        (self.root / '瞄准 Wiki' / SM).mkdir(parents=True)
        (self.root / 'Templates').mkdir()
        (self.root / '.obsidian' / SM).mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def request(self, **overrides):
        payload = {
            'action': 'land',
            'vaultRoot': str(self.root),
            'wiki': '个人运转 Wiki',
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


class ListWikisTest(VaultCase):
    def test_lists_only_visible_dirs_with_source_material(self):
        result = host.handle({'action': 'listWikis', 'vaultRoot': str(self.root)})
        self.assertEqual(result, {'ok': True, 'wikis': ['个人运转 Wiki', '瞄准 Wiki']})

    def test_missing_vault_is_reported(self):
        result = host.handle({'action': 'listWikis', 'vaultRoot': str(self.root / 'nope')})
        self.assertFalse(result['ok'])


class DuplicateKeyTest(unittest.TestCase):
    def test_youtube_variants_share_the_video_id(self):
        keys = {host.source_key(url) for url in [
            'https://www.youtube.com/watch?v=Gk2ArbsrZwE&t=30s',
            'https://youtu.be/Gk2ArbsrZwE?si=abc',
            'https://m.youtube.com/shorts/Gk2ArbsrZwE',
            'https://www.youtube.com/embed/Gk2ArbsrZwE',
        ]}
        self.assertEqual(keys, {'youtube:Gk2ArbsrZwE'})

    def test_other_urls_drop_fragment_and_tracking(self):
        self.assertEqual(host.source_key('https://example.com/a?utm_source=x&id=2#top'),
                         host.source_key('https://example.com/a?id=2'))

    def test_local_media_uses_file_name(self):
        self.assertEqual(host.source_key('lecture.mp4'), 'file:lecture.mp4')


class LandTest(VaultCase):
    def test_writes_three_key_frontmatter_and_sentence_body(self):
        result = host.handle(self.request())
        self.assertTrue(result['ok'], result)
        note = self.root / '个人运转 Wiki' / SM / 'Andrew Huberman' / 'The Art of True Happiness  Dr. Brooks.md'
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

    def test_link_text_escapes_brackets(self):
        host.handle(self.request(title='Why [this] works'))
        note = self.root / '个人运转 Wiki' / SM / 'Andrew Huberman' / 'Why [this] works.md'
        self.assertIn('> 来源：[Why \\[this\\] works](', note.read_text(encoding='utf-8'))

    def test_duplicate_video_anywhere_in_wiki_stops_before_writing(self):
        old = self.root / '个人运转 Wiki' / SM / 'Ali Abdaal' / 'old.md'
        old.write_text('---\ntitle: x\nsource: "https://youtu.be/Gk2ArbsrZwE"\nmedia_id: youtube:Gk2ArbsrZwE\n---\n', encoding='utf-8')
        result = host.handle(self.request())
        self.assertFalse(result['ok'])
        self.assertEqual(result['existing'], old.relative_to(self.root).as_posix())
        self.assertFalse((self.root / '个人运转 Wiki' / SM / 'Andrew Huberman').exists())

    def test_same_file_name_stops(self):
        host.handle(self.request())
        result = host.handle(self.request(source='https://www.youtube.com/watch?v=OTHERvideo1'))
        self.assertFalse(result['ok'])
        self.assertIn('existing', result)

    def test_rejects_unknown_wiki_and_path_tricks(self):
        for wiki in ['Templates', '../个人运转 Wiki', '.obsidian', '']:
            self.assertFalse(host.handle(self.request(wiki=wiki))['ok'], wiki)
        self.assertFalse(host.handle(self.request(author='..'))['ok'])
        self.assertFalse(host.handle(self.request(title='///'))['ok'])

    def test_requires_segments(self):
        self.assertFalse(host.handle(self.request(segments=[]))['ok'])

    def test_not_a_git_repo_keeps_file_and_reports_commit_failure(self):
        result = host.handle(self.request())
        self.assertTrue(result['ok'])
        self.assertFalse(result['commit']['ok'])
        self.assertTrue((self.root / result['path']).is_file())


class CommitTest(VaultCase):
    def setUp(self):
        super().setUp()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 't@example.com')
        git(self.root, 'config', 'user.name', 'Test')
        (self.root / 'draft.md').write_text('draft', encoding='utf-8')
        (self.root / 'staged.md').write_text('staged', encoding='utf-8')
        git(self.root, 'add', 'staged.md')

    def test_reuses_existing_author_dir_regardless_of_case(self):
        (self.root / '个人运转 Wiki' / SM / 'andrew huberman').mkdir()
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


class ProtocolTest(unittest.TestCase):
    def test_round_trips_length_prefixed_json(self):
        import io
        message = {'action': 'listWikis', 'vaultRoot': '中文'}
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

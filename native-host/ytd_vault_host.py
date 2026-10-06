"""YouTube Digest native messaging host: land platform captions in the Obsidian Wiki.

Chrome starts this script on demand (see install.ps1), sends one JSON request,
and reads one JSON response. `land` writes exactly one collection note,
`Wiki/收藏/<作者>/<标题>.md`, per the for_obsidian Knowledge System contract
(never creating `Wiki/收藏/` itself), then commits only that file;
`addWord` records one lookup in word/ through danzi-skill's store script.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

COLLECTION = Path('Wiki', '收藏')
ILLEGAL = r'[\\/:*?"<>|]'
CONFIG_FILE = Path(__file__).with_name('config.json')
YOUTUBE_HOSTS = ('youtube.com', 'youtube-nocookie.com')
TRACKING_PARAMS = {'si', 'feature', 'fbclid', 'gclid'}


# ---------------------------------------------------------------- protocol

def read_message(stream):
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack('<I', header)
    return json.loads(stream.read(length).decode('utf-8'))


def write_message(stream, message):
    body = json.dumps(message, ensure_ascii=False).encode('utf-8')
    stream.write(struct.pack('<I', len(body)))
    stream.write(body)
    stream.flush()


# ---------------------------------------------------------------- vault rules

def configured_vault_root():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8')).get('vaultRoot', '')
    except (OSError, ValueError):
        return ''


def vault_root(request):
    root = str(request.get('vaultRoot') or '').strip() or configured_vault_root()
    if not root:
        raise LandingError('未设置 Obsidian vault 路径：请在扩展设置页填写，或重新运行 install.ps1 -VaultRoot。')
    path = Path(root)
    if not path.is_dir():
        raise LandingError(f'找不到 vault 目录：{root}')
    return path


def collection_dir(root):
    collection = Path(root) / COLLECTION
    if not collection.is_dir():
        raise LandingError(f'vault 下缺少收藏区目录 {COLLECTION.as_posix()}/。')
    return collection


def clean_name(value, label):
    cleaned = re.sub(ILLEGAL, '', str(value or '')).strip()
    if not cleaned or cleaned.strip('.') == '':
        raise LandingError(f'{label}去除非法字符后为空。')
    return cleaned


def source_key(source):
    """Duplicate key derived from frontmatter `source` (shared with video-transcriber)."""
    text = str(source or '').strip().strip('"\'')
    parts = urlsplit(text)
    if not parts.scheme:
        return f'file:{text}'
    host = (parts.hostname or '').lower()
    if host == 'youtu.be':
        return f'youtube:{parts.path.strip("/").split("/")[0]}'
    if any(host == h or host.endswith('.' + h) for h in YOUTUBE_HOSTS):
        video = dict(parse_qsl(parts.query)).get('v')
        segments = [s for s in parts.path.split('/') if s]
        if not video and len(segments) >= 2 and segments[0] in ('shorts', 'embed', 'live', 'v'):
            video = segments[1]
        if video:
            return f'youtube:{video}'
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.startswith('utm_') and k not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip('/'), urlencode(query), ''))


def find_author_dir(collection, author):
    """Reuse an existing author folder that differs only in case.

    Windows paths ignore case but git pathspecs do not, so writing into
    `andrew huberman/` while committing `Andrew Huberman/...` fails; always
    use the folder's real on-disk name.
    """
    wanted = author.casefold()
    for child in collection.iterdir():
        if child.is_dir() and child.name.casefold() == wanted:
            return child
    return collection / author


SOURCE_LINE = re.compile(r'^source:\s*(.+?)\s*$', re.M)


def find_duplicate(collection, key):
    for note in sorted(collection.rglob('*.md')):
        try:
            with note.open(encoding='utf-8', errors='replace') as handle:
                head = handle.read(4096)
        except OSError:
            continue
        if not head.startswith('---'):
            continue
        match = SOURCE_LINE.search(head.split('\n---', 1)[0])
        if match and source_key(match[1]) == key:
            return note
    return None


def yaml_text(value):
    text = str(value)
    # Plain YAML scalars break on ": ", " #", leading indicators, quotes and edge whitespace.
    if (re.search(r': | #|[\'"]|^\s|\s$|^[-?:,\[\]{}#&*!|>%@`]', text)
            or text.lower() in ('true', 'false', 'null', 'yes', 'no', '~')
            or re.fullmatch(r'[-+]?(\d[\d_]*\.?\d*|\.\d+)([eE][-+]?\d+)?', text)):
        return json.dumps(text, ensure_ascii=False)
    return text


def timestamp(seconds):
    total = max(0, int(float(seconds)))
    return f'{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}'


def render_note(*, title, author, source, segments):
    link_text = re.sub(r'([\[\]])', r'\\\1', title)
    lines = ['---', f'title: {yaml_text(title)}', f'source: {yaml_text(source)}', 'author:',
             f'  - {yaml_text(author)}', '---', f'> 来源：[{link_text}]({source})', '', '## Transcript', '']
    for segment in segments:
        lines += [f"**{timestamp(segment['start'])}** · {segment['text']}", '']
    return '\n'.join(lines)


def clean_segments(raw):
    segments = []
    for item in raw if isinstance(raw, list) else []:
        text = ' '.join(str(item.get('text') or '').split()) if isinstance(item, dict) else ''
        try:
            start = float(item.get('start'))
        except (TypeError, ValueError, AttributeError):
            continue
        if text:
            segments.append({'start': start, 'text': text})
    if not segments:
        raise LandingError('没有可落盘的字幕。')
    return segments


# ---------------------------------------------------------------- git

def run_git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=60,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def commit_note(root, relative, message):
    return commit_paths(root, [relative], message)


def commit_paths(root, relatives, message):
    try:
        top = run_git(root, 'rev-parse', '--show-toplevel')
        if top.returncode != 0:
            return {'ok': False, 'error': 'vault 不是 Git 仓库。'}
        for args in (('add', '--', *relatives), ('commit', '-q', '-m', message, '--only', '--', *relatives)):
            result = run_git(root, *args)
            if result.returncode != 0:
                return {'ok': False, 'error': (result.stderr or result.stdout).strip() or f'git {args[0]} 失败'}
        head = run_git(root, 'rev-parse', '--short', 'HEAD')
        return {'ok': True, 'hash': head.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as error:
        return {'ok': False, 'error': str(error)}


# ---------------------------------------------------------------- actions

class LandingError(Exception):
    pass


def land(request):
    root = vault_root(request)
    collection = collection_dir(root)
    author = clean_name(request.get('author'), '作者')
    title = str(request.get('title') or '').strip()
    file_title = clean_name(title, '标题')
    source = str(request.get('source') or '').strip()
    if not urlsplit(source).scheme:
        raise LandingError('缺少视频网址。')
    segments = clean_segments(request.get('segments'))

    duplicate = find_duplicate(collection, source_key(source))
    if duplicate:
        return {'ok': False, 'error': '这个视频已经落盘过。', 'existing': duplicate.relative_to(root).as_posix()}
    author_dir = find_author_dir(collection, author)
    note = author_dir / f'{file_title}.md'
    if note.exists():
        return {'ok': False, 'error': '同名文件已存在。', 'existing': note.relative_to(root).as_posix()}

    author_dir.mkdir(exist_ok=True)
    with note.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(render_note(title=title, author=author, source=source, segments=segments))
    relative = note.relative_to(root).as_posix()
    commit = commit_note(root, relative, f'新增来源：{author_dir.name}/{file_title}')
    return {'ok': True, 'path': relative, 'commit': commit}


# ---------------------------------------------------------------- word list
# Entries follow for_obsidian/word/DESIGN.md; danzi-skill's vocabulary_store.py
# owns that format, so this host only finds the transcript and calls it (ADR 0003).

DEFAULT_STORE = Path('.claude/skills/danzi-skill/scripts/vocabulary_store.py')
PROFILE_LINE = re.compile(r'^(source_domain|source_topic):\s*(.+?)\s*$', re.M)


def find_landed(root, source):
    return find_duplicate(collection_dir(root), source_key(source))


def source_profile(note):
    """The transcript's saved domain and topic; later lookups reuse them."""
    text = note.read_text(encoding='utf-8', errors='replace')
    if not text.startswith('---'):
        return {}
    profile = {}
    for name, value in PROFILE_LINE.findall(text.split('\n---', 1)[0]):
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        profile[name] = value.strip('\'"') if isinstance(value, str) else value
    return profile


def find_source(request):
    root = vault_root(request)
    note = find_landed(root, str(request.get('source') or ''))
    if not note:
        return {'ok': True, 'landed': False}
    return {'ok': True, 'landed': True, 'path': note.relative_to(root).as_posix()}


def run_store(script, *args):
    env = {**os.environ, 'PYTHONUTF8': '1'}
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=60, env=env,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        output = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except ValueError:
        output = {'message': (result.stderr or result.stdout).strip()}
    if result.returncode != 0:
        raise LandingError(f'词表脚本拒绝写入：{output.get("message") or "未知错误"}')
    return output


def add_word(request):
    root = vault_root(request)
    note = find_landed(root, str(request.get('source') or ''))
    if not note:
        raise LandingError('这个视频还没存到 Wiki。')
    payload = request.get('payload')
    if not isinstance(payload, dict):
        raise LandingError('缺少查词内容。')
    script = Path(str(request.get('storeScript') or '').strip() or root / DEFAULT_STORE)
    if not script.is_file():
        raise LandingError(f'找不到 danzi 词表脚本：{script}')
    date = str(request.get('date') or '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise LandingError('缺少查词日期。')

    profile = source_profile(note)
    if profile.get('source_domain') and profile.get('source_topic'):
        payload = {**payload, **profile}
    source_rel = note.relative_to(root).as_posix()
    handle, payload_path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False)
        result = run_store(script, 'record-lookup', '--vault-root', str(root), '--source', source_rel,
                           '--payload', payload_path, '--date', date)
    finally:
        os.unlink(payload_path)

    commit = None
    if result.get('action') != 'deduplicated':
        entry = Path(result['entry_path']).stem
        commit = commit_paths(root, [result['entry_path'], source_rel], f'查词：{entry} ← {note.stem}')
    return {'ok': True, 'action': result.get('action'), 'entryPath': result.get('entry_path'),
            'occurrenceId': result.get('occurrence_id'), 'state': result.get('state'),
            'vaultName': root.resolve().name, 'commit': commit}


def handle(request):
    try:
        action = request.get('action') if isinstance(request, dict) else None
        if action == 'land':
            return land(request)
        if action == 'findSource':
            return find_source(request)
        if action == 'addWord':
            return add_word(request)
        return {'ok': False, 'error': f'未知操作：{action}'}
    except LandingError as error:
        return {'ok': False, 'error': str(error)}
    except OSError as error:
        return {'ok': False, 'error': f'写入失败：{error}'}
    except subprocess.SubprocessError as error:
        return {'ok': False, 'error': f'词表脚本运行失败：{error}'}


def main():
    request = read_message(sys.stdin.buffer)
    if request is not None:
        write_message(sys.stdout.buffer, handle(request))


if __name__ == '__main__':
    main()

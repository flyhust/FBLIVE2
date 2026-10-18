"""Checks for the industry-neutral dashboard: type detection, goal config, six modules, export.

Uses synthetic subtitles and comments on an ephemeral loopback server; no download or model.
"""
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'tool.py'
WORK = ROOT / '.test-work'
WORK.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('tool', SRC)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

segments = [
    {'id': 'T00001', 'start': 0.0, 'end': 40.0, 'text': '今天教你三个方法，比如这个步骤，为什么要这样做'},
    {'id': 'T00002', 'start': 310.0, 'end': 350.0, 'text': '大家觉得怎么样？可以下单，链接在留言区，限时折扣'},
    {'id': 'T00003', 'start': 650.0, 'end': 700.0, 'text': '我来演示一下，给你们看效果，报名课程的朋友也可以练习'},
]
comments = [
    {'id': 'C00001', 'source_id': 's1', 'start': 320.0, 'text': '多少钱？配送到新山吗', 'user': 'a1', 'role': 'viewer', 'parent_id': None},
    {'id': 'C00002', 'source_id': 's2', 'start': 330.0, 'text': '我要买 A1 + 2', 'user': 'a2', 'role': 'viewer', 'parent_id': None},
    {'id': 'C00003', 'source_id': 's3', 'start': 660.0, 'text': '谢谢，学到了很多', 'user': 'a3', 'role': None, 'parent_id': None},
    {'id': 'C00004', 'source_id': 's4', 'start': 665.0, 'text': '报名课程怎么报名', 'user': 'a4', 'role': None, 'parent_id': None},
    {'id': 'C00005', 'source_id': 's5', 'start': 670.0, 'text': '这位朋友请看留言区', 'user': 'h9', 'role': 'host', 'parent_id': 's1'},
]
base_report = {'title': '新品介绍', 'metadata': {'view_count': 1200}, 'transcription': {'duration': 900.0},
               'transcript': segments, 'comments': comments}

# A declared host role keeps staff comments out of the audience counts.
csv_path = WORK / 'dashboard.csv'
csv_path.write_text('id,timestamp,text,user_id,role\nx1,65,我要买两盒,u1,viewer\nx2,70,请看留言区,u9,主播\n', encoding='utf-8-sig')
parsed, _ = app.parse_comments(csv_path, '', 0, 'job')
assert [row['role'] for row in parsed] == ['viewer', 'host'], parsed

board = app.dashboard.build_dashboard(dict(base_report), {'live_type': 'auto', 'goals': []})
assert board['profile']['mode'] == '规则建议，待确认'
assert board['profile']['live_type'] in app.dashboard.TEMPLATES, board['profile']
assert board['overview']['audience_comments'] == 4 and board['overview']['staff_comments'] == 1
assert board['overview']['audience_people'] == 4
assert board['coverage']['unplaced_comments'] == 0
assert [section['start'] for section in board['content_map']] == [0, 300, 600]
assert [bin['minute'] for bin in board['timeline']] == [5, 11]
# The host reply resolves its parent question; the unanswered one stays listed.
assert board['questions']['unresolved_ids'] == ['C00004'], board['questions']
print('PASS: auto detection, audience/staff split, content map, timeline, unresolved questions')

manual = app.dashboard.build_dashboard(dict(base_report), {'live_type': 'service', 'goals': ['appointment'], 'goals_manual': True})
assert manual['profile']['mode'] == '用户指定' and manual['profile']['label'] == '房产／服务'
assert [action['id'] for action in manual['actions']] == ['appointment']
assert all(action['actual'] is None for action in manual['actions']), 'external results must stay unmeasured'
# Missing identities must not be reported as a distinct-person count.
anonymous = dict(base_report, comments=[dict(row, user=None) for row in comments])
assert app.dashboard.build_dashboard(anonymous, {'live_type': 'sales', 'goals': ['purchase'], 'goals_manual': True})['overview']['audience_people'] is None
for invalid in ({'live_type': 'nope', 'goals': []}, {'live_type': 'auto', 'goals': ['no_such_goal']}):
    try:
        app.dashboard.validate_config(invalid)
        raise AssertionError('invalid profile accepted: ' + json.dumps(invalid))
    except ValueError:
        pass
print('PASS: manual type/goals, unmeasured external results, unknown identities, config validation')

port = 18766
process = subprocess.Popen([sys.executable, str(SRC), '--no-browser', '--port', str(port), '--data-dir', str(WORK / 'board-data')],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f'http://127.0.0.1:{port}'
try:
    for attempt in range(60):
        try:
            text = urlopen(base, timeout=1).read().decode()
            break
        except Exception:
            time.sleep(.1)
    else:
        raise AssertionError('server did not start')
    token = re.search(r"const TOKEN='([a-f0-9]+)'", text)[1]

    def call(path, value=None, raw=None):
        headers = {'X-Session-Token': token}
        data = raw
        if value is not None:
            data = json.dumps(value).encode()
            headers['Content-Type'] = 'application/json'
        with urlopen(Request(base + path, data=data, headers=headers), timeout=10) as response:
            return response.read()

    templates = json.loads(call('/api/templates'))
    assert len(templates['types']) == 6 and 'purchase' in templates['goals'], templates
    srt = WORK / 'dashboard.srt'
    srt.write_text('\n\n'.join(f"{i+1}\n{app.stamp(s['start'], True)} --> {app.stamp(s['end'], True)}\n{s['text']}"
                               for i, s in enumerate(segments)) + '\n', encoding='utf-8-sig')
    uploaded = json.loads(call('/api/upload?ext=.srt', raw=srt.read_bytes()))['file']
    uploaded_comments = json.loads(call('/api/upload?ext=.csv', raw=csv_path.read_bytes()))['file']
    started = json.loads(call('/api/start', {'transcript': uploaded, 'comments': uploaded_comments, 'asr_model': 'small',
                                             'language': '', 'offset': 0, 'live_type': 'auto', 'goals': [],
                                             'title': '通用 Dashboard 验收（合成）'}))
    for _ in range(100):
        job = json.loads(call('/api/jobs/' + started['id']))
        if job['status'] in ['failed', 'done']:
            break
        time.sleep(.1)
    assert job['status'] == 'done', job
    assert job['report']['profile_config'] == {'live_type': 'auto', 'goals': [], 'goals_manual': False}
    assert job['report']['dashboard']['profile']['mode'] == '规则建议，待确认'

    changed = json.loads(call('/api/profile', {'id': started['id'], 'live_type': 'education', 'goals': ['learn', 'signup']}))
    assert [action['id'] for action in changed['dashboard']['actions']] == ['learn', 'signup'], changed['dashboard']['actions']
    stored = json.loads(call('/api/jobs/' + started['id']))['report']
    assert stored['dashboard']['profile']['live_type'] == 'education'
    assert len(stored['transcript']) == len(segments), 'reconfiguring must not discard the transcript'
    for invalid in ({'live_type': 'nope', 'goals': []}, {'live_type': 'auto', 'goals': ['no_such_goal']}, {'live_type': 'auto', 'goals': 'all'}):
        try:
            call('/api/profile', {'id': started['id'], **invalid})
            raise AssertionError('invalid profile accepted over HTTP: ' + json.dumps(invalid))
        except HTTPError as error:
            assert error.code == 400, error

    markdown = call('/api/export/' + started['id'] + '/md').decode('utf-8-sig')
    for heading in ('## 直播类型与目标', '## 直播总览', '## 内容地图', '## 观众洞察', '## 目标行动', '## 复盘建议'):
        assert heading in markdown, heading
    assert '实际结果 未取得' in markdown
    call('/api/shutdown', {})
    process.wait(timeout=10)
    print('PASS: templates API, pipeline dashboard, profile rebuild, invalid input, report export')
finally:
    if process.poll() is None:
        process.kill()

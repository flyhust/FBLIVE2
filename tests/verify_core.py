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

srt = WORK / 'fixture.srt'
srt.write_text('1\n00:00:00,000 --> 00:00:04,000\n今天教你怎么挑选产品。\n\n2\n00:00:04,000 --> 00:00:10,000\n因为每个人的需求不同，比如先看使用场景。\n\n3\n00:01:00,000 --> 00:01:09,000\n大家有没有问题？可以留言告诉我。\n\n4\n00:01:09,000 --> 00:01:15,000\n点击链接下单前先确认规格，今天有优惠。\n', encoding='utf-8')
segments = app.parse_transcript(srt)
assert len(segments) == 4 and segments[2]['start'] == 60 and segments[-1]['end'] == 75
assert '00:01:00,000 --> 00:01:09,000' in app.export_transcript(segments, 'srt')
vtt = WORK / 'fixture.vtt'
vtt.write_text('WEBVTT\n\n00:02.500 --> 00:04.000\n<b>Hello</b> &amp; welcome\n', encoding='utf-8')
assert app.parse_transcript(vtt)[0] == {'id': 'T00001', 'start': 2.5, 'end': 4., 'text': 'Hello & welcome'}
plain = WORK / 'plain.txt'
plain.write_text('没有时间戳也不编造时间\n[00:01:20] 有时间戳的原文', encoding='utf-8')
plain_rows = app.parse_transcript(plain)
assert plain_rows[0]['start'] is None and plain_rows[1]['start'] == 80
try:
    app.export_transcript(plain_rows, 'srt')
    raise AssertionError('Must not invent SRT times')
except ValueError:
    pass
comments = WORK / 'fixture.csv'
comments.write_text('id,timestamp,text,user_id,parent_id\na,2026-10-18T15:01:02+08:00,多少钱,u1,\na,2026-10-18T15:01:02+08:00,多少钱,u1,\nb,65,我要链接,u2,a\nc,,<script>malicious()</script>,u2,\n', encoding='utf-8-sig')
parsed, removed = app.parse_comments(comments, '2026-10-18T15:00:00+08:00', 2, 'job')
assert len(parsed) == 3 and removed == 1 and parsed[0]['start'] == 60 and parsed[1]['start'] == 63
assert parsed[2]['start'] is None and parsed[1]['parent_id'] == 'a'
assert parsed[0]['user'] != 'u1'
assert app.built_in_analysis(segments, parsed)['signals']['互动引导'] >= 1
for url in ['file:///etc/passwd', 'https://evil.com/fb.watch', 'https://facebook.com.evil.com/test', 'http://facebook.com/a']:
    try:
        app.validate_fb_url(url)
        raise AssertionError(url)
    except ValueError:
        pass
cookie_jar = WORK / 'cookies.txt'
cookie_jar.write_text('# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\tnot-a-real-value\n', encoding='utf-8')
app.check_cookie_file(cookie_jar)
try:
    app.check_cookie_file(WORK / 'plain.txt')
    raise AssertionError('a transcript must not pass as a cookie jar')
except ValueError:
    pass
print('PASS: real subtitle boundaries, plain text, timezone alignment, ID deduplication, missing values, URL boundary, cookie jar format')

port = 18765
process = subprocess.Popen([sys.executable, str(SRC), '--no-browser', '--port', str(port), '--data-dir', str(WORK/'data')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            data=json.dumps(value).encode()
            headers['Content-Type']='application/json'
        with urlopen(Request(base+path, data=data, headers=headers), timeout=10) as response:
            return response.read()
    try:
        urlopen(base+'/api/jobs', timeout=2)
        raise AssertionError('Unauthenticated API must fail')
    except HTTPError as error:
        assert error.code == 403
    uploaded = json.loads(call('/api/upload?ext=.srt', raw=srt.read_bytes()))['file']
    uploaded_comments = json.loads(call('/api/upload?ext=.csv', raw=comments.read_bytes()))['file']
    started = json.loads(call('/api/start', {'transcript':uploaded,'comments':uploaded_comments,'asr_model':'small','language':'','start_time':'2026-10-18T15:00:00+08:00','offset':2,'title':'本地验收样例（合成）'}))
    for _ in range(100):
        job = json.loads(call('/api/jobs/'+started['id']))
        if job['status'] in ['failed','done']:
            break
        time.sleep(.1)
    assert job['status'] == 'done', job
    report = job['report']
    assert len(report['transcript'])==4 and len(report['comments'])==3
    assert report['metadata'].get('like_count') is None
    srt_export = call('/api/export/'+started['id']+'/srt').decode('utf-8-sig')
    assert '00:01:00,000 --> 00:01:09,000' in srt_export
    html_export = call('/api/export/'+started['id']+'/html').decode()
    assert '<script>malicious()</script>' not in html_export
    assert json.loads(call('/api/export/'+started['id']+'/json'))['transcript'][0]['text'] == segments[0]['text']
    assert (WORK/'data/runs'/started['id']/'report.html').is_file()
    # A cookie jar is a live session: it must be gone once the run that used it ends.
    uploaded_cookies = json.loads(call('/api/upload?ext=.txt', raw=cookie_jar.read_bytes()))['file']
    assert (WORK/'data/uploads'/uploaded_cookies).is_file()
    with_cookies = json.loads(call('/api/start', {'transcript':uploaded,'cookies':uploaded_cookies,'asr_model':'small','language':'','offset':0,'title':'cookies 清理检查（合成）'}))
    for _ in range(100):
        cookie_job = json.loads(call('/api/jobs/'+with_cookies['id']))
        if cookie_job['status'] in ['failed','done']:
            break
        time.sleep(.1)
    assert cookie_job['status'] == 'done', cookie_job
    assert not (WORK/'data/uploads'/uploaded_cookies).exists(), 'cookie jar outlived its run'
    assert uploaded_cookies not in json.dumps(cookie_job['report'], ensure_ascii=False), 'the jar must not be named in the report'
    try:
        call('/api/start', {'transcript':uploaded,'cookies':'../../etc/passwd','asr_model':'small','language':'','offset':0})
        raise AssertionError('invalid cookies id accepted')
    except HTTPError as error:
        assert error.code == 400, error
    call('/api/shutdown', {})
    process.wait(timeout=10)
    print('PASS: local HTTP start/upload/analyze/history/export/shutdown pipeline, cookie cleanup and API session checks')
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)

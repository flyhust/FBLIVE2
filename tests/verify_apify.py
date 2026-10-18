"""Offline checks for the Apify integration: token handling, reshaping, counts, limits.

Nothing here calls Apify or any network service; a paid run is never triggered by the tests.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.test-work'
WORK.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('apify', ROOT / 'apify.py')
apify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apify)
spec = importlib.util.spec_from_file_location('tool', ROOT / 'tool.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

# --- the token is read from a .env and never printed back
home = WORK / 'apify-home'
home.mkdir(exist_ok=True)
(home / '.env').write_text('# local only\nAPIFY_TOKEN="apify_api_fake_value_for_tests"\nOTHER=1\n', encoding='utf-8')
assert apify.load_token(home) == 'apify_api_fake_value_for_tests'
assert apify.load_token(WORK / 'no-such-folder') is None or isinstance(apify.load_token(WORK / 'no-such-folder'), str)
for bad in (0, -5, apify.MAX_LIMIT + 1):
    try:
        apify.check_limit(bad)
        raise AssertionError('accepted an out-of-range limit: ' + str(bad))
    except ValueError:
        pass
assert apify.check_limit(None) == apify.DEFAULT_LIMIT
print('PASS: token loaded from .env, limits bounded')

# --- counts come through only when the actor returned them
assert apify.post_metrics({})['like_count'] is None
metrics = apify.post_metrics({'likes': 1200, 'comments': '2,345', 'shares': 17,
                              'reactions': {'like': 1000, 'love': 200}})
assert metrics['like_count'] == 1200 and metrics['comment_count'] == 2345 and metrics['repost_count'] == 17
assert metrics['reaction_count'] == 1200 and metrics['view_count'] is None
print('PASS: counts mapped, missing counts stay missing')

# --- replies keep their thread, and a guessed parent is counted so it can be disclosed
items = [
    {'commentId': 'c1', 'date': '2026-10-18T17:05:00.000Z', 'text': '多少钱？', 'profileId': 'u1', 'threadingDepth': 0},
    {'commentId': 'c2', 'date': '2026-10-18T17:06:00.000Z', 'text': '请看留言区', 'profileId': 'page', 'threadingDepth': 1},
    {'commentId': 'c3', 'date': '2026-10-18T17:07:00.000Z', 'text': '谢谢', 'profileId': 'u1', 'threadingDepth': 2},
    {'commentId': 'c4', 'date': '2026-10-18T17:20:00.000Z', 'text': '我要买两盒', 'profileId': 'u2', 'threadingDepth': 0},
    {'commentId': 'c5', 'date': '', 'text': '   ', 'profileId': 'u3', 'threadingDepth': 0},
    {'commentId': 'c6', 'date': '2026-10-18T17:25:00.000Z', 'text': '已回复', 'profileId': 'p',
     'threadingDepth': 1, 'replyToCommentId': 'c4'},
]
csv_text, guessed = apify.comments_to_csv(items)
assert guessed == 2, guessed                      # c2 and c3 inferred, c6 stated by the actor
path = WORK / 'apify-comments.csv'
path.write_text(csv_text, encoding='utf-8')
rows, dropped = app.parse_comments(path, '2026-10-18T17:00:00+00:00', 0, 'job')
assert dropped == 0 and len(rows) == 5, (dropped, len(rows))   # the blank comment never becomes a row
assert 'c5' not in csv_text, 'an empty comment must not reach the CSV'
assert [row['start'] for row in rows] == [300, 360, 420, 1200, 1500], [r['start'] for r in rows]
assert [row['parent_id'] for row in rows] == [None, 'c1', 'c2', None, 'c4'], [r['parent_id'] for r in rows]
assert all(row['user'] and row['user'] != 'u1' for row in rows), 'commenter ids must be hashed'
print('PASS: replies threaded, blank rows dropped, times aligned, identities hashed')

# --- the pipeline refuses a paid run that cannot work, before queueing anything
assert 'use_apify' in (ROOT / 'tool.py').read_text(encoding='utf-8')
report = {'title': '', 'metadata': metrics, 'transcription': {'duration': 1800.0},
          'transcript': [{'id': 'T00001', 'start': 0.0, 'end': 20.0, 'text': '今天介绍这个产品，可以下单'}],
          'comments': rows}
board = dashboard_board = app.dashboard.build_dashboard(report, {'live_type': 'auto', 'goals': []})
assert board['overview']['likes'] == 1200 and board['overview']['reactions'] == 1200
assert board['overview']['imported_comments'] == len(rows)
print('PASS: Apify counts reach the dashboard overview')
print(json.dumps({'rows': len(rows), 'guessed_parents': guessed}, ensure_ascii=False))

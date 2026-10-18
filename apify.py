"""Optional Apify integration: the only path that fetches comments and interaction counts from a link.

The token is read from the environment or a local .env, sent in the Authorization header,
and never written into a report, an export or a log line.
"""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
ENDPOINT = 'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items'
COMMENTS_ACTOR = 'apify~facebook-comments-scraper'
POSTS_ACTOR = 'apify~facebook-posts-scraper'
# A paid run that fetches thousands of comments should be a deliberate choice, not a default.
DEFAULT_LIMIT = 200
MAX_LIMIT = 5000


def load_token(home=None):
    """Environment first, then a .env beside the tool. Returns None when unset."""
    token = (os.environ.get('APIFY_TOKEN') or '').strip()
    if token:
        return token
    for folder in (home, BASE):
        if not folder:
            continue
        env = Path(folder) / '.env'
        if not env.is_file():
            continue
        for line in env.read_text(encoding='utf-8', errors='replace').splitlines():
            name, _, value = line.partition('=')
            if name.strip() == 'APIFY_TOKEN':
                return value.strip().strip('"').strip("'")
    return None


def call_actor(actor, payload, token, timeout=600):
    request = Request(ENDPOINT.format(actor=actor), data=json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=timeout) as response:
        items = json.loads(response.read().decode('utf-8'))
    return items if isinstance(items, list) else []


def check_limit(limit):
    # `or` would quietly turn a zero into the default, so an absent value is matched explicitly.
    limit = DEFAULT_LIMIT if limit in (None, '') else int(limit)
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'留言上限需在 1 到 {MAX_LIMIT} 之间。')
    return limit


def fetch_comments(url, token, limit=DEFAULT_LIMIT, timeout=600):
    return call_actor(COMMENTS_ACTOR, {'startUrls': [{'url': url}], 'resultsLimit': check_limit(limit),
                                       'includeNestedComments': True, 'viewOption': 'RANKED_UNFILTERED'},
                      token, timeout)


def fetch_post(url, token, timeout=300):
    items = call_actor(POSTS_ACTOR, {'startUrls': [{'url': url}], 'resultsLimit': 1}, token, timeout)
    return items[0] if items else {}


def post_metrics(item):
    """Only the counts the actor actually returned; anything absent stays absent."""
    def number(*names):
        for name in names:
            value = item.get(name)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.replace(',', '').isdigit():
                return int(value.replace(',', ''))
        return None
    reactions = item.get('reactions') if isinstance(item.get('reactions'), dict) else {}
    return {'like_count': number('likes', 'likesCount'),
            'comment_count': number('comments', 'commentsCount'),
            'repost_count': number('shares', 'sharesCount'),
            'view_count': number('viewsCount', 'videoViewCount', 'views'),
            'reaction_count': sum(v for v in reactions.values() if isinstance(v, int)) or None,
            'reactions_breakdown': reactions or None}


def comments_to_csv(items):
    """Reshape into the CSV this tool already parses, so one code path handles both sources.

    The actor reports how deep a reply sits but not which comment it answers, so a reply is
    attached to the nearest shallower comment before it. That is the thread order the actor
    returns, not a stated relationship: it is a reading aid, not evidence of who replied to whom.
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(['id', 'timestamp', 'text', 'user_id', 'role', 'parent_id', 'likes'])
    ancestors = {}
    guessed = 0
    for item in items:
        text = (item.get('text') or '').strip()
        if not text:
            continue
        depth = item.get('threadingDepth')
        depth = int(depth) if isinstance(depth, (int, float, str)) and str(depth).isdigit() else 0
        cid = item.get('commentId') or item.get('id') or ''
        parent = item.get('replyToCommentId') or item.get('parentCommentId') or ''
        if not parent and depth:
            parent = ancestors.get(depth - 1, '')
            guessed += 1 if parent else 0
        ancestors[depth] = cid
        for deeper in [d for d in ancestors if d > depth]:
            ancestors.pop(deeper, None)
        writer.writerow([cid, item.get('date') or '', text,
                         item.get('profileId') or item.get('profileUrl') or item.get('profileName') or '',
                         '', parent, item.get('likesCount') or ''])
    return output.getvalue(), guessed

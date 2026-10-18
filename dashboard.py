"""Evidence-linked, industry-neutral dashboard; deterministic rules, not causal scores."""
import json
import re
import sys
from pathlib import Path

# Frozen builds unpack bundled data beside the modules, not next to the source file.
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
TEMPLATES = json.loads((BASE / 'analysis_templates.json').read_text(encoding='utf-8'))
GOALS = {
    'consult': '了解需求／咨询', 'purchase': '购买意向', 'learn': '理解／练习参与',
    'signup': '报名意向', 'appointment': '预约意向', 'trial': '体验意向',
    'discuss': '观点交流／提问', 'participate': '活动参与', 'support': '关注／订阅意向',
}
PATTERNS = {
    'consult': r'请问|多少|怎么|如何|哪里|哪裡|适合|適合|配送|规格|規格|price|where|how|\?',
    'purchase': r'我要买|我要買|想买|想買|我要下单|我要下單|怎么买|怎麼買|\b[A-Z]\d+\s*[+＋]\s*\d+|want to buy',
    'learn': r'明白了|懂了|学会|學會|做完|完成练习|完成練習|不明白|没懂|不懂|understand|finished the exercise',
    'signup': r'报名|報名|参加课程|參加課程|sign up|enroll',
    'appointment': r'预约|預約|看房|约时间|約時間|book an appointment',
    'trial': r'试用|試用|想体验|想體驗|试驾|試駕|try it|free trial',
    'discuss': r'我觉得|我覺得|我认为|我認為|同意|不同意|为什么|為什麼|请问|請問|[?？]|i think|agree',
    'participate': r'我参加|我參加|参加活动|參加活動|已分享|已转发|已轉發|打卡|报名活动|報名活動|count me in',
    'support': r'已关注|已關注|已订阅|已訂閱|想订阅|想訂閱|怎么关注|怎麼關注|subscribed|followed',
}
TOPICS = {
    '问答／互动': r'留言|评论|評論|大家觉得|大家覺得|提问|提問|问答|問答|chat|question',
    '教学／解释': r'步骤|步驟|方法|原理|解释|解釋|比如|例如|练习|練習|how to|because',
    '行动号召': r'下单|下單|报名|報名|预约|預約|关注|關注|订阅|訂閱|点击|點擊|分享|sign up|subscribe',
    '演示／体验': r'演示|示范|示範|给你们看|給你們看|试用|試用|展示|demo|show you',
    '故事／观点': r'经历|經歷|故事|有一次|我认为|我認為|观点|觀點|story|opinion',
}
NEEDS = {
    '价格／费用': r'多少钱|多少錢|价格|價格|费用|費用|收费|收費|贵|貴|price|cost',
    '方法／理解': r'怎么|怎麼|如何|不懂|不明白|步骤|步驟|how',
    '条件／适用性': r'适合|適合|条件|條件|要求|资格|資格|新手|小白|beginner',
    '获取／参与方式': r'哪里|哪裡|地址|链接|連結|代码|代碼|code|配送|报名|報名|预约|預約|where',
    '内容／功能': r'功能|内容|內容|支持|包含|区别|區別|有什么|有什麼|feature',
    '疑虑／负面反馈': r'担心|擔心|失望|不好|不满意|不滿意|太贵|太貴|投诉|投訴|难用|難用|disappointed',
    '正面反馈': r'谢谢|謝謝|喜欢|喜歡|有帮助|有幫助|学到了|學到了|精彩|好看|好用|太棒|thank|love it',
}


def matches(pattern, text):
    return bool(re.search(pattern, text, re.I))


def validate_config(config):
    kind = config.get('live_type', 'auto')
    if kind not in {'auto', 'general', *TEMPLATES}:
        raise ValueError('直播类型无效。')
    goals = config.get('goals', [])
    if not isinstance(goals, list) or any(g not in GOALS for g in goals):
        raise ValueError('直播目标无效。')
    return {'live_type': kind, 'goals': list(dict.fromkeys(goals)),
            'goals_manual': bool(config.get('goals_manual', bool(goals)))}


def unique_people(rows):
    # Missing identities mean an exact distinct-person count is unknowable.
    if any(not r.get('user') for r in rows):
        return None
    return len({r['user'] for r in rows})


def union_duration(rows):
    intervals = sorted((r['start'], r['end']) for r in rows
                       if r.get('start') is not None and r.get('end') is not None)
    total, edge = 0, 0
    for start, end in intervals:
        total += max(0, end - max(start, edge))
        edge = max(edge, end)
    return round(total, 2) if intervals else None


def build_dashboard(report, config=None):
    config = validate_config(config or report.get('profile_config', {}))
    transcript, comments = report['transcript'], report['comments']
    # Use actual content and title, not URL strings or inferred account attributes.
    source = [{'id': 'title', 'text': report.get('title', '')}] + transcript + comments
    detection = []
    for key, template in TEMPLATES.items():
        hits = [r for r in source if matches(template['detect'], r['text'])]
        if hits:
            detection.append({'id': key, 'label': template['label'], 'hits': len(hits),
                              'evidence_ids': [r['id'] for r in hits if r['id'] != 'title'][:4]})
    detection.sort(key=lambda x: x['hits'], reverse=True)
    inferred = detection[0]['id'] if detection else 'general'
    kind = inferred if config['live_type'] == 'auto' else config['live_type']
    template = TEMPLATES.get(kind, {'label': '通用／未确定', 'goals': ['discuss'], 'verified': '需接入外部结果数据'})
    goals = config['goals'] if config['goals_manual'] else template['goals']
    profile = {'live_type': kind, 'label': template['label'], 'goals': goals,
               'mode': '规则建议，待确认' if config['live_type'] == 'auto' else '用户指定',
               'candidates': detection, 'config': config, 'verified': template['verified']}
    staff = [c for c in comments if c.get('role') in ('host', 'admin')]
    audience = [c for c in comments if c not in staff]
    unknown_roles = sum(not c.get('role') or c['role'] == 'unknown' for c in audience)
    giveaways = [c for c in audience if matches(r'抽奖|抽獎|中奖|中獎|已分享|已转发|已轉發|giveaway', c['text'])]
    substantive = [c for c in audience if c not in giveaways]
    actions = []
    for goal in goals:
        rows = [c for c in substantive if matches(PATTERNS[goal], c['text'])]
        rows = [c for c in rows if not matches(r'不要|不想|取消|不买|不買|不报名|不報名|don.t want|cancel', c['text'])]
        actions.append({'id': goal, 'title': GOALS[goal], 'count': len(rows) if comments else None,
                        'people': unique_people(rows) if comments else None,
                        'evidence_ids': [c['id'] for c in rows], 'actual': None})
    action_ids = {eid for a in actions for eid in a['evidence_ids']}
    known_ends = [s['end'] for s in transcript if s.get('end') is not None]
    metadata = report.get('metadata', {})
    duration = report.get('transcription', {}).get('duration') or metadata.get('duration')
    duration_source = '来源音视频' if duration else '未取得'
    if not duration and known_ends:
        duration, duration_source = max(known_ends), '逐字稿结束位置（非完整直播时长）'
    content_map = []
    # Five-minute windows are explicit reading sections, not invented semantic chapters.
    groups = {}
    for s in transcript:
        key = int(s['start'] // 300) if s.get('start') is not None else None
        groups.setdefault(key, []).append(s)
    for key, rows in groups.items():
        topic_hits = {name: [r for r in rows if matches(pattern, r['text'])] for name, pattern in TOPICS.items()}
        labels = [name for name, hits in topic_hits.items() if hits]
        content_map.append({'title': ' / '.join(labels) or '其他内容', 'start': key * 300 if key is not None else None,
                            'duration': union_duration(rows), 'excerpt': rows[0]['text'][:180],
                            'evidence_ids': [r['id'] for r in rows], 'labels': labels})
    timeline = {}
    for c in audience:
        t = c.get('start')
        if t is None or t < 0 or (duration and t > duration):
            continue
        minute = int(t // 60)
        timeline.setdefault(minute, []).append(c)
    bins = []
    for minute, rows in sorted(timeline.items()):
        linked = [s for s in transcript if s.get('start') is not None
                  and s['start'] < (minute + 1) * 60
                  and (s.get('end') if s.get('end') is not None else s['start'] + .001) > minute * 60]
        bins.append({'minute': minute, 'comments': len(rows), 'people': unique_people(rows),
                     'action_count': sum(c['id'] in action_ids for c in rows),
                     'evidence_ids': [c['id'] for c in rows] + [s['id'] for s in linked]})
    insights = []
    for name, pattern in NEEDS.items():
        rows = [c for c in substantive if matches(pattern, c['text'])]
        if rows:
            insights.append({'title': name, 'count': len(rows), 'people': unique_people(rows),
                             'detail': '关键词匹配，可能重叠；请核对原文和语境。',
                             'evidence_ids': [c['id'] for c in rows]})
    insights.sort(key=lambda x: x['count'], reverse=True)
    questions = [c for c in substantive if matches(r'[?？]|请问|請問|怎么|怎麼|如何|多少|为什么|為什麼|where|how', c['text'])]
    replied = {c.get('parent_id') for c in comments if c.get('role') in ('host', 'admin') and c.get('parent_id')}
    unresolved = [c for c in questions if not c.get('source_id') or c['source_id'] not in replied]
    recommendations = []
    for insight in insights[:3]:
        recommendations.append({'title': '补充「' + insight['title'] + '」信息',
                                'detail': f"样本中 {insight['count']} 条留言匹配此需求；下一场设置说明或问答环节，并核对观众是否得到回应。",
                                'evidence_ids': insight['evidence_ids'][:3]})
    peaks = sorted(bins, key=lambda b: b['comments'], reverse=True)[:3]
    clips = [{'title': f"候选回看 · 第 {b['minute']} 分钟", 'detail':
              f"已导入样本该分钟有 {b['comments']} 条非已知主播留言。需回看画面、语音和上下文，不能据此判定最佳片段或因果。",
              'evidence_ids': b['evidence_ids'][:6]} for b in peaks]
    return {'profile': profile, 'overview': {'duration': duration, 'duration_source': duration_source,
            'views': metadata.get('view_count'), 'likes': metadata.get('like_count'),
            'reactions': metadata.get('reaction_count'), 'shares': metadata.get('repost_count'),
            'source_comments': metadata.get('comment_count'), 'imported_comments': len(comments) if comments else None,
            'audience_comments': len(audience) if comments else None, 'audience_people': unique_people(audience) if comments else None,
            'action_people': unique_people([c for c in audience if c['id'] in action_ids]) if comments else None,
            'staff_comments': len(staff), 'giveaway_comments': len(giveaways)},
            'coverage': {'unknown_roles': unknown_roles, 'missing_users': sum(not c.get('user') for c in audience),
                         'aligned_comments': sum(b['comments'] for b in bins),
                         'unplaced_comments': len(audience) - sum(b['comments'] for b in bins),
                         'source': metadata.get('source') or '本地导入',
                         'acquired_at': metadata.get('acquired_at') or report.get('created_at'),
                         'note': '分析仅覆盖已导入资料，不代表整场；未知身份仍纳入候选观众。没有外部结果数据，不计算成交或学习成效。'},
            'content_map': content_map, 'timeline': bins, 'insights': insights, 'actions': actions,
            'questions': {'count': len(questions), 'unresolved_ids': [c['id'] for c in unresolved],
                          'note': '待核实问题：仅检查已导入的主播／管理员文字回复，不代表直播中未口头回答。'},
            'recommendations': recommendations, 'clips': clips,
            'method': '本地规则初筛；五分钟内容窗口；各类信号可重叠，不作为质量评分。'}

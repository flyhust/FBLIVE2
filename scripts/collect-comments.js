/*
 * 留言采集脚本 · FBLIVE2
 *
 * 在你已经登录、能正常看到留言的 Facebook 视频／贴文页面上，打开浏览器开发者工具
 * （F12）→ Console，粘贴整段并回车。脚本会先把留言和回复展开，再导出一份 CSV，
 * 列名正好是工具要的：id / timestamp / text / user_id / role / parent_id。
 *
 * 它只读页面上已经渲染出来的内容，不调用任何接口、不发送任何数据到外部，
 * 也不会点赞、回复或删除。Facebook 的页面结构随时会变，采不到时请看末尾的提示。
 */
(async () => {
  const CONFIG = {
    hostNames: [],      // 想把某些人标成主播／管理员，就把名字填进来，例如 ['小衡', 'Jo Mama']
    maxRounds: 40,      // 最多展开几轮，每轮点一次「查看更多留言」
    pauseMs: 1200,      // 每轮之间等待加载的毫秒数
  };

  const EXPAND = /查看更多留言|查看更多評論|更多留言|更多评论|更多回覆|更多回复|查看.*则回复|view more comments|previous comments|view \d+ repl|more repl|see more/i;
  const MORE_TEXT = /^(查看更多|顯示更多|显示更多|see more)$/i;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const visible = node => !!(node.offsetParent || node.getClientRects().length);

  function clickableTargets() {
    const nodes = document.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
    return [...nodes].filter(node => visible(node) && EXPAND.test((node.innerText || '').trim()));
  }

  // 1. 反复展开，直到没有新的「更多」按钮，或者到达轮数上限
  let rounds = 0;
  for (; rounds < CONFIG.maxRounds; rounds++) {
    const targets = clickableTargets();
    if (!targets.length) break;
    targets.forEach(node => node.click());
    console.log(`[FBLIVE2] 第 ${rounds + 1} 轮：展开 ${targets.length} 处`);
    await sleep(CONFIG.pauseMs);
  }
  // 展开被折叠的长留言正文
  [...document.querySelectorAll('div[role="button"], span[role="button"]')]
    .filter(node => visible(node) && MORE_TEXT.test((node.innerText || '').trim()))
    .forEach(node => node.click());
  await sleep(800);

  // 2. 从留言节点里取出作者、正文、时间和留言 ID
  const articles = [...document.querySelectorAll('div[role="article"]')]
    .filter(node => (node.getAttribute('aria-label') || '').trim());

  // 回复本身也是 role="article"，取字段时必须跳过嵌套在里面的那些节点，
  // 否则一条留言会显示成它第一条回复的内容。
  const own = (node, selector) => [...node.querySelectorAll(selector)]
    .filter(el => el.parentElement.closest('div[role="article"]') === node);

  const idOf = node => {
    const link = own(node, 'a[href*="comment_id="]')[0];
    if (link) {
      const match = link.href.match(/comment_id=(\d+)/) || link.href.match(/reply_comment_id=(\d+)/);
      if (match) return match[1];
    }
    return null;
  };

  const authorOf = node => {
    const link = own(node, 'a[href]')
      .find(a => (a.innerText || '').trim() && /facebook\.com\/(profile\.php|[^/?#]+)/.test(a.href)
                 && !/comment_id=/.test(a.href));
    if (!link) return { name: '', id: '' };
    const profile = link.href.split('?')[0].replace(/\/$/, '');
    const uid = link.href.match(/[?&]id=(\d+)/);
    return { name: (link.innerText || '').trim().split('\n')[0], id: uid ? uid[1] : profile };
  };

  const textOf = (node, authorName) => {
    const blocks = own(node, 'div[dir="auto"], span[dir="auto"]')
      .map(el => (el.innerText || '').trim())
      .filter(t => t && t !== authorName && !/^\d+\s*(小时|小時|分钟|分鐘|週|周|天|年|h|m|d|w|y)$/i.test(t));
    return blocks.sort((a, b) => b.length - a.length)[0] || '';
  };

  // 工具按带时区的 ISO 时间对齐留言，所以在这里就把本地化的日期字符串转过去；
  // 认不出来的格式原样保留，工具会把它当成「没有时间」，不会猜。
  const isoTime = title => {
    if (!title) return '';
    const offset = -new Date().getTimezoneOffset();
    const zone = (offset < 0 ? '-' : '+')
      + String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0') + ':'
      + String(Math.abs(offset) % 60).padStart(2, '0');
    const pad = n => String(n).padStart(2, '0');
    const cjk = title.match(/(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[^\d]*(\d{1,2})\s*[:：]\s*(\d{2})/);
    if (cjk) return `${cjk[1]}-${pad(cjk[2])}-${pad(cjk[3])}T${pad(cjk[4])}:${cjk[5]}:00${zone}`;
    const parsed = new Date(title.replace(/at/i, ''));
    if (!isNaN(parsed)) {
      return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`
           + `T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}${zone}`;
    }
    return title;
  };

  const timeOf = node => {
    const stamp = own(node, 'a[href*="comment_id="] [title], a[href*="comment_id="][title], abbr[title]')[0]
      || [...node.querySelectorAll('a[href*="comment_id="] [title]')]
           .find(el => el.closest('div[role="article"]') === node);
    return stamp ? isoTime((stamp.getAttribute('title') || '').trim()) : '';
  };

  const rows = [];
  const seen = new Set();
  for (const node of articles) {
    const id = idOf(node);
    const key = id || (node.getAttribute('aria-label') + '|' + (node.innerText || '').slice(0, 80));
    if (seen.has(key)) continue;
    seen.add(key);
    const author = authorOf(node);
    const text = textOf(node, author.name);
    if (!text) continue;
    const parentNode = node.parentElement && node.parentElement.closest('div[role="article"]');
    rows.push({
      id: id || '',
      timestamp: timeOf(node),
      text,
      user_id: author.id || author.name,
      role: CONFIG.hostNames.includes(author.name) ? 'host' : '',
      parent_id: parentNode ? (idOf(parentNode) || '') : '',
    });
  }

  if (!rows.length) {
    console.warn('[FBLIVE2] 一条留言都没取到。先手动把留言区滚到底、确认留言是展开的，再跑一次；'
               + '如果页面结构变了，就得改这个脚本的选择器。');
    return;
  }

  // 3. 存成 CSV（UTF-8 BOM，Excel 直接打开不乱码）
  const escape = value => '"' + String(value == null ? '' : value).replace(/"/g, '""') + '"';
  const header = ['id', 'timestamp', 'text', 'user_id', 'role', 'parent_id'];
  const csv = '﻿' + [header.join(','), ...rows.map(r => header.map(h => escape(r[h])).join(','))].join('\r\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  link.download = 'fb-comments-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '') + '.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();

  const withTime = rows.filter(r => r.timestamp).length;
  const replies = rows.filter(r => r.parent_id).length;
  console.log(`[FBLIVE2] 展开 ${rounds} 轮，导出 ${rows.length} 条留言（其中回复 ${replies} 条，带时间 ${withTime} 条）。`);
  console.log('[FBLIVE2] 导出的时间是发布时间，不是直播内的分秒；想对齐时间轴，'
            + '请在工具的「高级设置」里填直播开始时间（含时区）。没有时间的留言仍可用于观众洞察。');
})();

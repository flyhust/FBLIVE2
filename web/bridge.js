'use strict';

// Only the explicitly paired loopback worker receives files, API calls or tokens.
let API_BASE = '', TOKEN = '', connected = false, connecting = false, taskPending = false;
const CONNECTION_KEY = 'live-notes-loopback-session';

function validateConnection(base, token) {
  const match = /^http:\/\/127\.0\.0\.1:(\d{4,5})\/?$/.exec(String(base).trim());
  if (!match || Number(match[1]) < 1024 || Number(match[1]) > 65535) {
    throw Error('本机地址必须是 http://127.0.0.1:端口，端口范围为 1024–65535。请使用本地工具提供的地址。');
  }
  const normalizedToken = String(token).trim().toLowerCase();
  if (!/^[a-f0-9]{48}$/.test(normalizedToken)) {
    throw Error('连接令牌应为本地工具提供的 48 位字符。请重新复制本次启动的配对链接。');
  }
  return {base: 'http://127.0.0.1:' + Number(match[1]), token: normalizedToken};
}

function parsePairingURL(text) {
  let url;
  try { url = new URL(String(text).trim(), location.href); }
  catch (_) { throw Error('配对链接格式不完整，请复制本地工具打开的完整网页链接。'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw Error('配对链接应为 HTTP 或 HTTPS 网页链接。');
  const params = new URLSearchParams(url.hash.slice(1));
  if (params.getAll('bridge').length !== 1 || params.getAll('token').length !== 1) {
    throw Error('配对链接需包含本次启动的本机地址与连接令牌。');
  }
  return validateConnection(params.get('bridge'), params.get('token'));
}

function saveConnection(value) {
  try {
    if (value) sessionStorage.setItem(CONNECTION_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(CONNECTION_KEY);
  } catch (_) { /* Pairing still works when the browser disables session storage. */ }
}

function connectionMessage(text, level = '') {
  $('connection-message').textContent = text;
  $('connection-message').className = 'note' + (level ? ' ' + level : '');
}

function updateConnectionUI() {
  $('start').disabled = !connected || taskPending;
  $('connect').disabled = connecting;
  $('connect').textContent = connecting ? '正在连接…' : (API_BASE ? '连接／重新连接' : '连接本机工具');
  $('disconnect').classList.toggle('hidden', !connected);
  $('shutdown-worker').disabled = !connected;
  $('connection-state').textContent = connected ? '已连接本机工具' : (connecting ? '正在连接' : '尚未连接本机工具');
  $('connection-state').classList.toggle('offline', !connected);
  $('connection-details').open = !connected;
  $('connected-address').textContent = connected ? API_BASE : '';
  $('model-note').textContent = connected ? '正在检查本机 Ollama…' : '连接本机工具后，可查看已安装的本地 AI 模型。';
  if (!connected) {
    $('cancel').disabled = true;
    $('local-model').replaceChildren(el('option', '规则初筛（无需语言模型）'));
    $('local-model').firstChild.value = '';
  }
}

function lostConnection(message, forget = false) {
  connected = false;
  clearTimeout(pollTimer);
  if (forget) { API_BASE = ''; TOKEN = ''; saveConnection(null); }
  updateConnectionUI();
  connectionMessage(message, 'error');
}

async function localRequest(path, options = {}, timeout = 0) {
  if (!API_BASE || !TOKEN) throw Error('请先启动本地工具，并在上方完成连接。');
  if (!path.startsWith('/api/')) throw Error('无效的本机接口路径。');
  const requestBase = API_BASE, requestToken = TOKEN;
  const controller = new AbortController();
  const timer = timeout ? setTimeout(() => controller.abort(), timeout) : null;
  let response;
  try {
    response = await fetch(requestBase + path, {
      ...options,
      headers: {...options.headers, 'X-Session-Token': requestToken},
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      cache: 'no-store',
      signal: controller.signal
    });
  } catch (error) {
    const message = error.name === 'AbortError'
      ? '连接本机工具超时。请确认本地程序正在运行，再点击重新连接。'
      : '无法连接本机工具。请启动本地程序；若浏览器提示「本地网络访问」，请允许此网页访问本机，再重新连接。程序重启后请使用新的配对链接。';
    if (requestBase === API_BASE && requestToken === TOKEN) lostConnection(message);
    throw Error(message);
  } finally { if (timer) clearTimeout(timer); }
  let data;
  try { data = await response.json(); }
  catch (_) { throw Error('本机工具返回了无法读取的资料，请更新本地工具后重试。'); }
  if (requestBase !== API_BASE || requestToken !== TOKEN) throw Error('网页连接已变更，已忽略上一次连接的返回资料。');
  if (!response.ok) {
    if (response.status === 403) {
      const message = '配对已失效（403）。请使用本地工具本次启动生成的新配对链接；本地工具必须允许当前网页地址。';
      lostConnection(message, true);
      throw Error(message);
    }
    throw Error(data.error || '本机操作未完成（' + response.status + '）。');
  }
  return data;
}

async function api(path, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  return localRequest(path, options);
}

async function uploadFile(inputId) {
  const file = $(inputId).files[0];
  if (!file) return null;
  if (!connected) throw Error('请先连接本机工具，再导入文件。');
  if (file.size === 0 || file.size > 4 * 1024 ** 3) throw Error('文件为空或超过 4GB，请选择较小的音视频文件。');
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  const data = await localRequest('/api/upload?ext=' + encodeURIComponent(ext), {method: 'POST', body: file});
  return data.file;
}

async function connectWorker(value) {
  if (connecting) return;
  try {
    if (!value) {
      const pairing = $('pairing-url').value.trim();
      const manualBase = $('worker-url').value.trim();
      const manualToken = $('worker-token').value.trim();
      value = pairing ? parsePairingURL(pairing)
        : validateConnection(manualBase || API_BASE, manualToken || TOKEN);
    }
    value = validateConnection(value.base, value.token);
    if (API_BASE && (API_BASE !== value.base || TOKEN !== value.token)) resetLocalView();
    API_BASE = value.base; TOKEN = value.token;
    connecting = true; connected = false;
    updateConnectionUI();
    connectionMessage('正在连接你指定的本机工具…');
    const health = await localRequest('/api/health', {}, 12000);
    if (typeof health.version !== 'string' || typeof health.data_dir !== 'string' || health.bridge_protocol !== 1) {
      throw Error('此地址未返回兼容的本地工具状态，请更新程序后重新配对。');
    }
    if (health.portal_origin !== location.origin) {
      throw Error('本地启动器没有允许当前网页地址。请使用配套启动器打开正确的线上工作台。');
    }
    connected = true;
    saveConnection(value);
    $('data-path').textContent = health.data_dir;
    $('pairing-url').value = ''; $('worker-url').value = ''; $('worker-token').value = '';
    updateConnectionUI();
    connectionMessage('已连接。音视频、逐字稿、报告与分析记录均由本机工具处理和保存。网页不会把这些内容上传到 Vercel。');
    await discoverModels();
    if (activeJob && connected) await pollJob();
    if (!$('page-history').classList.contains('hidden') && connected) await loadHistory();
  } catch (error) {
    connected = false;
    updateConnectionUI();
    connectionMessage(error.message, 'error');
  } finally {
    connecting = false;
    // Preserve a running task's disabled start button after reconnecting.
    $('connect').disabled = false;
    $('connect').textContent = API_BASE ? '连接／重新连接' : '连接本机工具';
    $('connection-state').textContent = connected ? '已连接本机工具' : '尚未连接本机工具';
  }
}

async function discoverModels() {
  try {
    const data = await localRequest('/api/models', {}, 15000);
    $('local-model').replaceChildren(el('option', '规则初筛（无需语言模型）'));
    $('local-model').firstChild.value = '';
    for (const model of data.models || []) {
      const option = el('option', model + ' · 本地 AI'); option.value = model;
      $('local-model').append(option);
    }
    $('model-note').textContent = data.available
      ? (data.models.length ? '已连接本机 Ollama；可选择模型进行深度分析。' : '已连接 Ollama，但没有已安装的语言模型。')
      : '未连接本机 Ollama，规则初筛仍可使用。';
  } catch (error) {
    $('model-note').textContent = '本地 AI 模型检查未完成：' + error.message;
  }
}

function resetLocalView() {
  clearTimeout(pollTimer);
  activeJob = null; report = null; taskPending = false;
  $('report-area').classList.add('hidden'); $('status').classList.add('hidden');
  $('empty').classList.remove('hidden');
  $('downloads').replaceChildren(); $('history-list').replaceChildren();
  $('data-path').textContent = '';
}

function disconnectWorker() {
  if (connected && !confirm('断开网页连接？本机任务会继续运行；稍后可用配对链接重新连接并查看本地历史。')) return;
  resetLocalView();
  API_BASE = ''; TOKEN = ''; connected = false;
  saveConnection(null);
  updateConnectionUI();
  connectionMessage('已断开网页与本机工具的连接。本机程序和正在进行的任务仍会继续运行。');
}

async function quitTool() {
  if (!connected) { toast('请先连接正在运行的本机工具。'); return; }
  if (!confirm('关闭本机工具？尚未完成的任务会停止，已保存记录保留。关闭网页或断开连接则不会停止本机任务。')) return;
  try {
    await api('/api/shutdown', {});
    resetLocalView();
    API_BASE = ''; TOKEN = ''; connected = false; saveConnection(null);
    updateConnectionUI();
    connectionMessage('本机工具已关闭，已保存记录保留。下次启动本地程序后，使用新的配对链接重新连接。');
  } catch (error) { toast(error.message); }
}

function consumePairingFragment() {
  const fragment = location.hash;
  if (!fragment) return false;
  // A launcher can target a tab that already has this page open: hash-only
  // navigation does not reload scripts, so handle it as a new pairing too.
  history.replaceState(null, '', location.pathname + location.search);
  try { connectWorker(parsePairingURL(location.origin + location.pathname + fragment)); }
  catch (error) { connectionMessage(error.message, 'error'); }
  return true;
}

function initializePortal() {
  const actions = {
    "showPage('work')": () => showPage('work'),
    "showPage('history')": () => showPage('history'),
    'quitTool()': quitTool,
    'startJob()': startJob,
    'cancelJob()': cancelJob,
    "setTab('analysis')": () => setTab('analysis'),
    "setTab('transcript')": () => setTab('transcript'),
    "setTab('audience')": () => setTab('audience'),
    'segmentLimit+=150;renderTranscript()': () => { segmentLimit += 150; renderTranscript(); },
    'commentLimit+=100;renderComments()': () => { commentLimit += 100; renderComments(); },
    'loadHistory()': loadHistory,
    'connectWorker()': () => connectWorker(),
    'disconnectWorker()': disconnectWorker
  };
  for (const element of document.querySelectorAll('[data-action]')) {
    const handler = actions[element.dataset.action];
    if (!handler) throw Error('网页操作未注册：' + element.dataset.action);
    element.addEventListener('click', handler);
  }
  $('transcript-search').addEventListener('input', renderTranscript);
  $('comment-search').addEventListener('input', renderComments);
  $('pairing-url').addEventListener('keydown', event => { if (event.key === 'Enter') connectWorker(); });
  $('worker-token').addEventListener('keydown', event => { if (event.key === 'Enter') connectWorker(); });
  updateConnectionUI();
  window.addEventListener('hashchange', consumePairingFragment);
  if (consumePairingFragment()) return;
  try {
    const saved = sessionStorage.getItem(CONNECTION_KEY);
    if (saved) { const value = JSON.parse(saved); connectWorker(validateConnection(value.base, value.token)); return; }
  } catch (_) { saveConnection(null); }
  connectionMessage('请先运行电脑上的本地工具，并使用它打开的配对网页。也可在下面粘贴本次启动的完整配对链接。');
}

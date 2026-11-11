'use strict';
const $ = (id) => document.getElementById(id);
let source = 'api', paused = false, loading = false, snapshot = null, authBlocked = false;
function connection(text, state = '') { $('connection').textContent = text; $('light').className = state; }
function showAuth(message) {
  authBlocked = true; snapshot = null; render(); $('auth').hidden = false;
  $('auth-message').textContent = message; connection('需要访问密码', 'bad');
}
function empty(title, description) {
  const box = document.createElement('div'); box.className = 'empty';
  const symbol = document.createElement('span'); symbol.textContent = '⌁';
  const strong = document.createElement('strong'); strong.textContent = title;
  const p = document.createElement('p'); p.textContent = description;
  box.append(symbol, strong, p); $('logs').replaceChildren(box);
}
function render() {
  if (!snapshot) { $('count').textContent = '0 条'; empty('等待日志连接', '连接成功后显示原始日志。'); return; }
  const needle = $('search').value.trim().toLowerCase(), level = $('level').value;
  const lines = snapshot.lines.filter(line => (level === 'all' || line.level === level)
    && (!needle || line.text.toLowerCase().includes(needle))
    && (!$('noise').checked || !/\/(?:api\/health|ops\/logs\/)/.test(line.text)));
  $('count').textContent = `${lines.length} / ${snapshot.lines.length} 条`;
  $('window').textContent = snapshot.window;
  if (!lines.length) { empty('当前没有匹配的日志', '可切换来源、级别或调整关键词。'); return; }
  const pane = $('logs'), follow = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80 || !pane.querySelector('.line');
  const oldScroll = pane.scrollTop, fragment = document.createDocumentFragment();
  lines.forEach((line, i) => {
    const row = document.createElement('div'); row.className = `line ${line.level}`;
    const number = document.createElement('span'); number.className = 'number'; number.textContent = String(i + 1);
    const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = {info:'INFO', warning:'WARN', error:'ERROR'}[line.level];
    const text = document.createElement('span'); text.className = 'text'; text.textContent = line.text;
    row.append(number, tag, text); fragment.append(row);
  });
  pane.replaceChildren(fragment); pane.scrollTop = follow ? pane.scrollHeight : oldScroll;
}
async function refresh() {
  if (loading) return;
  loading = true; $('refresh').disabled = true; const requestedSource = source;
  try {
    const response = await fetch(`./api/logs?source=${encodeURIComponent(source)}`, {
      credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(12000)
    });
    const data = await response.json();
    if (response.status === 401 || response.status === 403) { showAuth(data.message); return; }
    if (!response.ok) throw new Error(data.message || `请求失败 (${response.status})`);
    if (requestedSource !== source) return;
    authBlocked = false; $('auth').hidden = true; snapshot = data; $('error-message').hidden = true;
    const age = Math.max(0, Math.floor((Date.now() - Date.parse(data.collected_at)) / 1000));
    connection(paused ? '已暂停更新' : age > 30 ? '采集延迟' : '实时连接', age > 30 ? 'bad' : 'online');
    $('updated').textContent = new Date(data.collected_at).toLocaleTimeString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) + ' 更新';
    if (age > 30) { $('error-message').hidden = false; $('error-message').textContent = `当前为 ${age} 秒前的快照，采集可能中断。`; }
    render();
  } catch (error) {
    connection('连接暂时中断', 'bad'); $('error-message').hidden = false;
    $('error-message').textContent = error.name === 'TimeoutError' ? '请求超时，将自动重试。' : '暂时无法获取日志，将自动重试。';
  } finally {
    loading = false; $('refresh').disabled = false;
    if (requestedSource !== source && !authBlocked) queueMicrotask(refresh);
  }
}
document.querySelectorAll('[data-source]').forEach(button => button.addEventListener('click', () => {
  source = button.dataset.source; snapshot = null; render();
  document.querySelectorAll('[data-source]').forEach(tab => { const selected = tab === button; tab.classList.toggle('active', selected); tab.setAttribute('aria-pressed', String(selected)); });
  refresh();
}));
['search', 'level', 'noise'].forEach(id => $(id).addEventListener('input', render));
$('refresh').addEventListener('click', refresh);
$('reconnect').addEventListener('click', () => { authBlocked = false; refresh(); });
$('pause').addEventListener('click', () => {
  paused = !paused; $('pause').textContent = paused ? '▶ 继续' : 'Ⅱ 暂停'; $('pause').setAttribute('aria-pressed', String(paused));
  if (paused) connection('已暂停更新'); else refresh();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && !paused && !authBlocked) refresh(); });
setInterval(() => { if (!paused && !document.hidden && !authBlocked) refresh(); }, 5000);
refresh();

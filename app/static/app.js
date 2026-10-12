const categories = [
  ['qualification', '资格条件'],
  ['rejection', '废标/否决条款'],
  ['materials', '材料清单'],
  ['deadlines', '截止时间'],
];
let selectedFile = null;
let activeCategory = 'qualification';
let currentTask = null;
let latestResult = null;
let requestInFlight = false;

const $ = (id) => document.getElementById(id);
const fileInput = $('file-input');
const dropZone = $('drop-zone');

function showNotice(message, error = false) {
  const box = $('notice');
  box.hidden = !message;
  box.textContent = message || '';
  box.classList.toggle('error', error);
}

function selectFile(file) {
  if (!file) return;
  const allowed = ['.pdf', '.docx', '.txt', '.md'];
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowed.includes(extension)) {
    showNotice('只支持 PDF、DOCX、TXT 或 MD 文件。', true);
    return;
  }
  selectedFile = file;
  $('file-name').textContent = file.name;
  $('file-meta').textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 等待检查`;
  $('start-btn').disabled = false;
  showNotice('');
}

fileInput.addEventListener('change', (event) => selectFile(event.target.files[0]));
['dragenter', 'dragover'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault(); dropZone.classList.add('drag');
}));
['dragleave', 'drop'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault(); dropZone.classList.remove('drag');
}));
dropZone.addEventListener('drop', (event) => selectFile(event.dataTransfer.files[0]));

async function loadConfig() {
  try {
    const response = await fetch('/api/config');
    const config = await response.json();
    $('size-label').textContent = config.max_file_mb;
    $('model-label').textContent = '未配置模型';
    if (config.mock) showNotice('当前为 mock 模式，不会产生模型费用。');
  } catch (_) {
    showNotice('无法读取服务配置，请确认本地服务已启动。', true);
  }
}

function readModelOptions() {
  const model = $('model-input').value.trim();
  const protocol = $('protocol-input').value;
  const baseUrl = $('base-url-input').value.trim();
  if (!model || !protocol || !baseUrl) {
    showNotice('请先填写模型名称、协议和代理地址。', true);
    return null;
  }
  return { model, protocol, baseUrl };
}

$('test-btn').addEventListener('click', async () => {
  const options = readModelOptions();
  if (!options) return;
  const button = $('test-btn');
  button.disabled = true;
  button.textContent = '测试中...';
  try {
    const params = new URLSearchParams({
      protocol: options.protocol,
      model: options.model,
      base_url: options.baseUrl,
    });
    const response = await fetch(`/api/connection?${params}`);
    const data = await response.json();
    $('connection-dot').classList.toggle('online', data.ok);
    showNotice(data.message, !data.ok);
  } catch (_) {
    $('connection-dot').classList.remove('online');
    showNotice('连接测试失败，请检查代理地址和 CCSwitch 是否运行。', true);
  } finally {
    button.disabled = false;
    button.textContent = '测试连接';
  }
});

$('start-btn').addEventListener('click', async () => {
  if (!selectedFile || requestInFlight) return;
  const options = readModelOptions();
  if (!options) return;
  requestInFlight = true;
  const form = new FormData();
  form.append('file', selectedFile);
  form.append('model', options.model);
  form.append('protocol', options.protocol);
  form.append('base_url', options.baseUrl);
  $('start-btn').disabled = true;
  $('progress-panel').hidden = false;
  $('results-panel').hidden = true;
  showNotice('');
  try {
    const response = await fetch('/api/analyze', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '创建任务失败');
    currentTask = data.task_id;
    await pollTask();
  } catch (error) {
    showNotice(error.message, true);
    $('start-btn').disabled = false;
    requestInFlight = false;
  }
});

async function pollTask() {
  const maxAttempts = 180;
  let failures = 0;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const response = await fetch(`/api/tasks/${currentTask}`);
      const task = await response.json();
      if (!response.ok) throw new Error(task.detail || '任务状态查询失败');
      failures = 0;
      $('stage-label').textContent = task.stage;
      $('progress-value').textContent = `${task.progress}%`;
      $('progress-bar').style.width = `${task.progress}%`;
      $('progress-message').textContent = task.message || task.error || '';
      if (task.status === 'completed') {
        latestResult = task.result;
        renderResults();
        $('start-btn').disabled = false;
        requestInFlight = false;
        return;
      }
      if (task.status === 'failed') {
        showNotice(task.error || '检查失败', true);
        $('start-btn').disabled = false;
        requestInFlight = false;
        return;
      }
    } catch (error) {
      failures += 1;
      if (failures >= 3) {
        showNotice(error.message || '无法查询任务状态，请稍后重试。', true);
        $('start-btn').disabled = false;
        requestInFlight = false;
        return;
      }
    }
    await new Promise((resolve) => window.setTimeout(resolve, failures ? 1500 : 900));
  }
  showNotice('任务处理时间过长，请重新查询或稍后重试。', true);
  $('start-btn').disabled = false;
  requestInFlight = false;
}

function renderResults() {
  $('results-panel').hidden = false;
  $('json-link').href = `/api/tasks/${currentTask}/export.json`;
  $('json-link').setAttribute('download', 'check-results.json');
  $('csv-link').href = `/api/tasks/${currentTask}/export.csv`;
  $('csv-link').setAttribute('download', 'check-results.csv');
  renderTabs();
  renderTable();
}

function renderTabs() {
  $('tabs').innerHTML = categories.map(([key, label]) => {
    const active = key === activeCategory ? 'active' : '';
    const count = latestResult[key]?.length || 0;
    return `<button class="tab ${active}" data-category="${key}">${label}<span class="count">${count}</span></button>`;
  }).join('');
  document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => {
    activeCategory = tab.dataset.category;
    renderTabs(); renderTable();
  }));
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function renderTable() {
  const items = latestResult[activeCategory] || [];
  if (!items.length) {
    $('table-wrap').innerHTML = '<div class="empty">没有识别到此类条款。请仍结合原文人工复核。</div>';
    return;
  }
  $('table-wrap').innerHTML = `<table><thead><tr><th>事项</th><th>原文证据</th><th>位置</th><th>状态</th><th>严重程度</th></tr></thead><tbody>${items.map((item) => {
    const status = item.verified ? '<span class="badge ok">原文已匹配</span>' : '<span class="badge wait">待人工核验</span>';
    const severityClass = item.severity === '高' ? 'high' : item.severity === '中' ? 'medium' : 'wait';
    const extra = activeCategory === 'deadlines' ? `<div class="muted">${escapeHtml(item.time_type || '时间节点')} ${escapeHtml(item.normalized_time || '')}</div>` : '';
    return `<tr><td><div class="item-title">${escapeHtml(item.title)}</div><div class="item-req">${escapeHtml(item.requirement)}</div>${extra}</td><td><div class="evidence">${escapeHtml(item.evidence)}</div></td><td><div class="location">${escapeHtml(item.location?.label || '出处待核验')}</div><div class="muted">${escapeHtml(item.source_id)}</div></td><td>${status}<div class="muted">${escapeHtml(item.verification_note || '')}</div></td><td><span class="badge ${severityClass}">${escapeHtml(item.severity)}</span>${item.ambiguity ? `<div class="muted">${escapeHtml(item.ambiguity)}</div>` : ''}</td></tr>`;
  }).join('')}</tbody></table>`;
}

loadConfig();

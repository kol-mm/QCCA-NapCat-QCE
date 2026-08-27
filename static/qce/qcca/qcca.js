(function () {
  'use strict';

  var apiPort = new URLSearchParams(location.search).get('apiPort') || '40655';
  if (!/^\d{1,5}$/.test(apiPort) || Number(apiPort) < 1 || Number(apiPort) > 65535) apiPort = '40655';
  var API_BASE = 'http://' + (location.hostname === 'localhost' ? 'localhost' : '127.0.0.1') + ':' + apiPort;
  var state = { configs: {}, selectedUid: null, draft: null, dirty: false, smtpConfigured: false, smtpSenderQq: '', smtpAccounts: [], smtpLoginQq: '', audioModel: { status: 'unknown', message: '' }, liveCapture: { enabled: false, sessions: [], webhookUrl: '', webhookToken: '' }, liveCaptureSessions: [], liveCaptureLoading: false };

  var icons = {
    'arrow-left': '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    'refresh-cw': '<path d="M21 12a9 9 0 0 0-15-6.7L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 15 6.7l3-2.7"/><path d="M16 16h5v5"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    'settings-2': '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
    'trash-2': '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="m20 6-11 11-5-5"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>'
  };

  function iconSvg(name) {
    return '<svg class="lucide" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' + (icons[name] || '') + '</svg>';
  }

  function renderIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (element) {
      var name = element.dataset.icon;
      element.removeAttribute('data-icon');
      element.insertAdjacentHTML('afterbegin', iconSvg(name));
    });
  }

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function byId(id) { return document.getElementById(id); }
  function workspaces() { return state.draft ? state.draft.workspaces : {}; }
  function sessionTotal(user) {
    return Object.values(user.workspaces || {}).reduce(function (total, item) {
      return total + Object.keys(item.sessions || {}).length;
    }, 0);
  }

  async function request(path, options) {
    var response;
    try {
      response = await fetch(API_BASE + path, options);
    } catch (error) {
      throw new Error('无法连接 QCCA API，请确认服务已启动');
    }
    var payload = null;
    try { payload = await response.json(); } catch (error) {}
    if (!response.ok) throw new Error(payload && payload.detail ? payload.detail : '请求失败（' + response.status + '）');
    return payload;
  }

  async function requestQce(path, options) {
    var response;
    var requestOptions = options || {};
    var headers = Object.assign({ 'Content-Type': 'application/json' }, requestOptions.headers || {});
    try {
      var token = localStorage.getItem('qce_access_token');
      if (token) {
        headers.Authorization = 'Bearer ' + token;
        headers['X-Access-Token'] = token;
      }
    } catch (error) {}
    requestOptions = Object.assign({}, requestOptions, { headers: headers });
    try { response = await fetch(path, requestOptions); } catch (error) { throw new Error('无法连接 QQ Chat Exporter API'); }
    var payload = null;
    try { payload = await response.json(); } catch (error) {}
    if (!response.ok || !payload || payload.success === false) {
      throw new Error(payload && payload.error && payload.error.message ? payload.error.message : 'QQ Chat Exporter 请求失败');
    }
    return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
  }

  function setConnection(online, text) {
    byId('connectionDot').className = 'status-dot ' + (online ? 'online' : 'offline');
    byId('connectionText').textContent = text;
  }

  function toast(message, type) {
    var item = document.createElement('div');
    item.className = 'toast ' + (type || 'success');
    item.innerHTML = iconSvg(type === 'error' ? 'alert' : 'check');
    var text = document.createElement('span');
    text.textContent = message;
    item.appendChild(text);
    byId('toastRegion').appendChild(item);
    setTimeout(function () { item.remove(); }, 3200);
  }

  async function loadConfigs(keepSelection) {
    setConnection(false, '正在连接');
    try {
      var responses = await Promise.all([request('/qcca/configs'), request('/qcca/smtp-config'), request('/qcca/audio-model-status')]);
      state.configs = responses[0];
      applySmtpResult(responses[1]);
      state.audioModel = responses[2];
      try {
        applyLiveCaptureConfig(await requestQce('/api/config'));
      } catch (error) {
        state.liveCapture = { enabled: false, sessions: [], webhookUrl: '', webhookToken: '' };
        toast('无法读取 QQ Chat Exporter 的实时捕获配置', 'error');
      }
      setConnection(true, 'API 已连接');
      if (!keepSelection || !state.configs[state.selectedUid]) {
        state.selectedUid = Object.keys(state.configs).sort()[0] || null;
      }
      state.draft = state.selectedUid ? clone(state.configs[state.selectedUid]) : null;
      state.dirty = false;
      render();
      loadLiveCaptureSessions();
    } catch (error) {
      setConnection(false, 'API 未连接');
      toast(error.message, 'error');
      renderSidebar();
    }
  }

  function render() {
    renderSidebar();
    renderAudioModelStatus();
    renderSmtpSettings();
    renderLiveCapture();
    var hasUser = Boolean(state.selectedUid && state.draft);
    byId('emptyState').hidden = hasUser;
    byId('editor').hidden = !hasUser;
    byId('saveButton').hidden = !hasUser;
    byId('deleteUserButton').hidden = !hasUser;
    if (!hasUser) return;
    byId('userTitle').textContent = state.selectedUid;
    renderEditor();
  }

  function applyLiveCaptureConfig(config) {
    var value = config && config.liveCapture ? config.liveCapture : {};
    state.liveCapture = {
      enabled: Boolean(value.enabled),
      sessions: Array.isArray(value.sessions) ? clone(value.sessions) : [],
      webhookUrl: value.webhookUrl || '',
      webhookToken: value.webhookToken || ''
    };
  }

  function liveCaptureKey(item) { return String(item.chatType || 1) + ':' + String(item.peerUid || ''); }

  function renderLiveCapture() {
    var config = state.liveCapture || {};
    byId('liveCaptureEnabled').checked = Boolean(config.enabled);
    byId('liveCaptureWebhookUrl').value = config.webhookUrl || '';
    byId('liveCaptureWebhookToken').value = config.webhookToken || '';
    var selected = new Set((config.sessions || []).map(liveCaptureKey));
    var list = byId('liveCaptureSessionList');
    list.replaceChildren();
    if (state.liveCaptureLoading) {
      var loading = document.createElement('div');
      loading.className = 'no-sessions';
      loading.textContent = '正在加载会话…';
      list.appendChild(loading);
    } else if (!state.liveCaptureSessions.length) {
      var empty = document.createElement('div');
      empty.className = 'no-sessions';
      empty.textContent = '暂无可用会话';
      list.appendChild(empty);
    } else {
      state.liveCaptureSessions.forEach(function (item) {
        var label = document.createElement('label');
        label.className = 'live-capture-session';
        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selected.has(liveCaptureKey(item));
        checkbox.addEventListener('change', function () {
          var current = state.liveCapture.sessions.filter(function (entry) { return liveCaptureKey(entry) !== liveCaptureKey(item); });
          if (checkbox.checked) current.push(item);
          state.liveCapture.sessions = current;
          renderLiveCaptureSummary();
        });
        var name = document.createElement('span');
        name.textContent = item.name;
        var uid = document.createElement('small');
        uid.textContent = item.peerUid;
        label.appendChild(checkbox);
        label.appendChild(name);
        label.appendChild(uid);
        list.appendChild(label);
      });
    }
    renderLiveCaptureSummary();
    var status = byId('liveCaptureStatus');
    status.textContent = config.enabled ? '已启用' : '未启用';
    status.classList.toggle('configured', Boolean(config.enabled));
  }

  function renderLiveCaptureSummary() {
    var count = (state.liveCapture.sessions || []).length;
    byId('liveCaptureSessionSummary').textContent = count ? ('已选择 ' + count + ' 个会话') : '未选择会话';
  }

  async function loadLiveCaptureSessions() {
    state.liveCaptureLoading = true;
    renderLiveCapture();
    try {
      var results = await Promise.all([requestQce('/api/groups?page=1&limit=1000'), requestQce('/api/friends?page=1&limit=1000')]);
      var groups = Array.isArray(results[0] && results[0].groups) ? results[0].groups : [];
      var friends = Array.isArray(results[1] && results[1].friends) ? results[1].friends : [];
      state.liveCaptureSessions = groups.map(function (item) { return { chatType: 2, peerUid: String(item.groupCode || item.groupId || ''), name: item.groupName || item.groupCode || '群聊' }; }).filter(function (item) { return item.peerUid; })
        .concat(friends.map(function (item) { return { chatType: item.chatType || 1, peerUid: String(item.uid || item.uin || ''), name: item.remark || item.nick || item.uin || '好友' }; }).filter(function (item) { return item.peerUid; }));
    } catch (error) {
      state.liveCaptureSessions = [];
      toast(error.message, 'error');
    } finally {
      state.liveCaptureLoading = false;
      renderLiveCapture();
    }
  }

  async function saveLiveCapture() {
    var button = byId('saveLiveCaptureButton');
    button.disabled = true;
    var config = {
      enabled: byId('liveCaptureEnabled').checked,
      sessions: state.liveCapture.sessions || [],
      webhookUrl: byId('liveCaptureWebhookUrl').value.trim() || null,
      webhookToken: byId('liveCaptureWebhookToken').value.trim() || null
    };
    try {
      var result = await requestQce('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ liveCapture: config }) });
      applyLiveCaptureConfig(result);
      renderLiveCapture();
      toast('实时捕获配置已保存');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; }
  }

  function renderSmtpSettings() {
    var status = byId('smtpStatus');
    status.textContent = state.smtpConfigured ? '已配置' : '未配置';
    status.classList.toggle('configured', state.smtpConfigured);
    var senderSelect = byId('smtpSenderQq');
    senderSelect.replaceChildren();
    state.smtpAccounts.forEach(function (account) {
      var label = account.qq + (account.qq === state.smtpLoginQq ? '（当前登录）' : '') + (account.configured ? '' : '（未配置授权码）');
      option(senderSelect, account.qq, label);
    });
    senderSelect.value = state.smtpSenderQq;
    var selected = state.smtpSenderQq;
    byId('deleteSmtpButton').hidden = !selected || selected === state.smtpLoginQq;
    byId('smtpNewSenderQq').value = '';
    byId('smtpAuthCode').value = '';
    byId('smtpNewAuthCode').value = '';
  }

  function renderAudioModelStatus() {
    var status = byId('audioModelStatus');
    var current = state.audioModel || {};
    var labels = {
      not_started: 'Agent 未启动',
      loading: '模型加载中',
      ready: '模型已就绪',
      failed: '加载失败',
      stopped: 'Agent 已停止',
      unknown: '状态未知'
    };
    var value = current.status || 'unknown';
    status.textContent = labels[value] || '状态未知';
    status.className = 'model-status ' + value;
    status.title = current.message || status.textContent;
  }

  async function loadAudioModelStatus() {
    try {
      state.audioModel = await request('/qcca/audio-model-status');
    } catch (error) {
      state.audioModel = { status: 'unknown', message: '无法连接 QCCA API' };
    }
    renderAudioModelStatus();
  }

  function applySmtpResult(result) {
    state.smtpConfigured = Boolean(result.configured);
    state.smtpSenderQq = result.selected_sender_qq || '';
    state.smtpAccounts = Array.isArray(result.accounts) ? result.accounts : [];
    state.smtpLoginQq = result.login_qq || '';
  }

  function renderSidebar() {
    var query = byId('userSearch').value.trim();
    var list = byId('userList');
    list.replaceChildren();
    Object.keys(state.configs).sort().filter(function (uid) { return !query || uid.indexOf(query) !== -1; }).forEach(function (uid) {
      var user = state.configs[uid];
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'user-item' + (uid === state.selectedUid ? ' active' : '');
      button.dataset.uid = uid;
      button.innerHTML = '<span class="user-avatar">' + iconSvg('user') + '</span><span class="user-id"></span><span class="user-meta"></span>';
      button.querySelector('.user-id').textContent = uid;
      button.querySelector('.user-meta').textContent = Object.keys(user.workspaces || {}).length + '/' + sessionTotal(user);
      button.addEventListener('click', function () { selectUser(uid); });
      list.appendChild(button);
    });
  }

  function selectUser(uid) {
    if (uid === state.selectedUid) return;
    if (state.dirty && !window.confirm('当前修改尚未保存，确定切换用户吗？')) return;
    state.selectedUid = uid;
    state.draft = clone(state.configs[uid]);
    state.dirty = false;
    render();
  }

  function setDirty() {
    state.dirty = true;
    byId('saveButton').disabled = false;
  }

  function renderEditor() {
    var items = workspaces();
    byId('workspaceCount').textContent = Object.keys(items).length;
    byId('sessionCount').textContent = sessionTotal(state.draft);
    byId('saveButton').disabled = !state.dirty;
    renderRecentSelectors();
    renderWorkspaceList();
  }

  function option(select, value, label) {
    var item = document.createElement('option');
    item.value = value;
    item.textContent = label;
    select.appendChild(item);
  }

  function recentPair() {
    var entries = Object.entries(state.draft.recent_workspace_and_session || {});
    return entries.length ? entries[0] : ['', ''];
  }

  function renderRecentSelectors(preferredWorkspace) {
    var workspaceSelect = byId('recentWorkspace');
    var sessionSelect = byId('recentSession');
    var pair = recentPair();
    var selectedWorkspace = preferredWorkspace !== undefined ? preferredWorkspace : pair[0];
    workspaceSelect.replaceChildren();
    var names = Object.keys(workspaces());
    option(workspaceSelect, '', names.length ? '选择工作区' : '暂无工作区');
    names.forEach(function (name) { option(workspaceSelect, name, name); });
    workspaceSelect.value = names.includes(selectedWorkspace) ? selectedWorkspace : '';
    sessionSelect.replaceChildren();
    var sessions = workspaceSelect.value ? Object.keys(workspaces()[workspaceSelect.value].sessions || {}) : [];
    option(sessionSelect, '', sessions.length ? '选择会话' : '暂无会话');
    sessions.forEach(function (name) { option(sessionSelect, name, name); });
    sessionSelect.value = workspaceSelect.value === pair[0] && sessions.includes(pair[1]) ? pair[1] : '';
  }

  function renderWorkspaceList() {
    var list = byId('workspaceList');
    list.replaceChildren();
    var entries = Object.entries(workspaces());
    if (!entries.length) {
      var empty = document.createElement('div');
      empty.className = 'no-sessions';
      empty.textContent = '暂无工作区';
      list.appendChild(empty);
      return;
    }
    entries.forEach(function (entry, workspaceIndex) {
      var workspaceName = entry[0];
      var workspace = entry[1];
      var card = document.createElement('article');
      card.className = 'workspace-card';
      card.innerHTML =
          '<div class="workspace-header">' +
          '<label class="field"><span>工作目录</span><input class="workspace-name" spellcheck="false" readonly></label>' +
          '<label class="field"><span>沙箱权限</span><select class="sandbox"><option value="read-only">只读</option><option value="workspace-write">工作区可写</option><option value="danger-full-access">完全访问</option></select></label>' +
          '</div>' +
        '<div class="sessions-wrap"><div class="sessions-heading"><span>会话</span></div><div class="session-list"></div></div>';
      var nameInput = card.querySelector('.workspace-name');
      nameInput.value = workspaceName;
      var sandbox = card.querySelector('.sandbox');
      sandbox.value = workspace.sandbox || 'read-only';
      sandbox.addEventListener('change', function () { workspace.sandbox = sandbox.value; setDirty(); });
      renderSessions(card.querySelector('.session-list'), workspaceName, workspace.sessions || {});
      list.appendChild(card);
    });
  }

  function renderSessions(list, workspaceName, sessions) {
    var entries = Object.entries(sessions);
    if (!entries.length) {
      var empty = document.createElement('div');
      empty.className = 'no-sessions';
      empty.textContent = '暂无会话';
      list.appendChild(empty);
      return;
    }
    entries.forEach(function (entry) {
      var sessionName = entry[0];
      var row = document.createElement('div');
      row.className = 'session-row';
      row.innerHTML = '<input class="session-name" aria-label="会话名称" readonly><input class="session-resume" aria-label="Codex 会话 ID" readonly>';
      var nameInput = row.querySelector('.session-name');
      var resumeInput = row.querySelector('.session-resume');
      nameInput.value = sessionName;
      resumeInput.value = entry[1] || '';
      list.appendChild(row);
    });
  }

  function uniqueName(base, existing) {
    var name = base;
    var index = 2;
    while (Object.prototype.hasOwnProperty.call(existing, name)) name = base + ' ' + index++;
    return name;
  }

  function addWorkspace() {
    var name = uniqueName('新工作区', workspaces());
    workspaces()[name] = { sandbox: 'read-only', sessions: {} };
    setDirty();
    renderEditor();
  }

  function renameWorkspace(oldName, newName) {
    newName = newName.trim();
    if (!newName || (newName !== oldName && workspaces()[newName])) {
      toast(!newName ? '工作目录不能为空' : '工作目录不能重复', 'error');
      renderWorkspaceList();
      return;
    }
    if (newName === oldName) return;
    var rebuilt = {};
    Object.entries(workspaces()).forEach(function (entry) { rebuilt[entry[0] === oldName ? newName : entry[0]] = entry[1]; });
    state.draft.workspaces = rebuilt;
    var pair = recentPair();
    if (pair[0] === oldName) state.draft.recent_workspace_and_session = Object.fromEntries([[newName, pair[1]]]);
    setDirty();
    renderEditor();
  }

  function removeWorkspace(name) {
    delete workspaces()[name];
    if (recentPair()[0] === name) state.draft.recent_workspace_and_session = {};
    setDirty();
    renderEditor();
  }

  function addSession(workspaceName) {
    var sessions = workspaces()[workspaceName].sessions;
    var name = uniqueName('新会话', sessions);
    sessions[name] = '';
    setDirty();
    renderEditor();
  }

  function renameSession(workspaceName, oldName, newName) {
    newName = newName.trim();
    var sessions = workspaces()[workspaceName].sessions;
    if (!newName || (newName !== oldName && Object.prototype.hasOwnProperty.call(sessions, newName))) {
      toast(!newName ? '会话名称不能为空' : '会话名称不能重复', 'error');
      renderWorkspaceList();
      return;
    }
    if (newName === oldName) return;
    var rebuilt = {};
    Object.entries(sessions).forEach(function (entry) { rebuilt[entry[0] === oldName ? newName : entry[0]] = entry[1]; });
    workspaces()[workspaceName].sessions = rebuilt;
    var pair = recentPair();
    if (pair[0] === workspaceName && pair[1] === oldName) state.draft.recent_workspace_and_session = Object.fromEntries([[workspaceName, newName]]);
    setDirty();
    renderEditor();
  }

  function removeSession(workspaceName, sessionName) {
    delete workspaces()[workspaceName].sessions[sessionName];
    var pair = recentPair();
    if (pair[0] === workspaceName && pair[1] === sessionName) state.draft.recent_workspace_and_session = {};
    setDirty();
    renderEditor();
  }

  async function saveUser() {
    byId('saveButton').disabled = true;
    try {
      await request('/qcca/config/update/' + encodeURIComponent(state.selectedUid), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.draft)
      });
      state.configs[state.selectedUid] = clone(state.draft);
      state.dirty = false;
      render();
      toast('配置已保存');
    } catch (error) {
      setDirty();
      toast(error.message, 'error');
    }
  }

  async function saveSmtpConfig() {
    var senderQq = byId('smtpSenderQq').value;
    var input = byId('smtpAuthCode');
    var authCode = input.value.trim();
    if (!/^\d{5,12}$/.test(senderQq)) {
      toast('请选择要更新的发件 QQ', 'error');
      byId('smtpSenderQq').focus();
      return;
    }
    if (!authCode) {
      toast('请输入 QQ 邮箱授权码', 'error');
      input.focus();
      return;
    }
    var button = byId('saveSmtpButton');
    button.disabled = true;
    try {
      var result = await request('/qcca/smtp-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sender_qq: senderQq, auth_code: authCode })
      });
      input.value = '';
      applySmtpResult(result);
      renderSmtpSettings();
      toast('授权码已更新');
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function addSmtpConfig() {
    var senderInput = byId('smtpNewSenderQq');
    var authInput = byId('smtpNewAuthCode');
    var senderQq = senderInput.value.trim();
    var authCode = authInput.value.trim();
    if (!/^\d{5,12}$/.test(senderQq)) {
      toast('请输入有效的新增发件 QQ 号', 'error');
      senderInput.focus();
      return;
    }
    if (!authCode) {
      toast('请输入该 QQ 的邮箱授权码', 'error');
      authInput.focus();
      return;
    }
    var button = byId('addSmtpButton');
    button.disabled = true;
    try {
      var result = await request('/qcca/smtp-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sender_qq: senderQq, auth_code: authCode })
      });
      applySmtpResult(result);
      renderSmtpSettings();
      toast('发件 QQ 已新增并设为当前账号');
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function deleteSmtpConfig() {
    var senderQq = state.smtpSenderQq;
    if (!senderQq || senderQq === state.smtpLoginQq) return;
    if (!window.confirm('删除发件 QQ ' + senderQq + ' 及其授权码？')) return;
    try {
      var result = await request('/qcca/smtp-config/' + encodeURIComponent(senderQq), { method: 'DELETE' });
      applySmtpResult(result);
      renderSmtpSettings();
      toast('发件 QQ 已删除');
    } catch (error) { toast(error.message, 'error'); }
  }

  function closeDeleteModal() { byId('deleteModal').hidden = true; }

  async function deleteUser() {
    try {
      await request('/qcca/config/delete/' + encodeURIComponent(state.selectedUid), { method: 'DELETE' });
      delete state.configs[state.selectedUid];
      state.selectedUid = Object.keys(state.configs).sort()[0] || null;
      state.draft = state.selectedUid ? clone(state.configs[state.selectedUid]) : null;
      state.dirty = false;
      closeDeleteModal();
      render();
      toast('QQ 用户已删除');
    } catch (error) { toast(error.message, 'error'); }
  }

  byId('refreshButton').addEventListener('click', function () { loadConfigs(true); });
  byId('userSearch').addEventListener('input', renderSidebar);
  document.querySelectorAll('[data-close-delete]').forEach(function (button) { button.addEventListener('click', closeDeleteModal); });
  byId('deleteUserButton').addEventListener('click', function () { byId('deleteModal').hidden = false; });
  byId('confirmDeleteUser').addEventListener('click', deleteUser);
  byId('saveButton').addEventListener('click', saveUser);
  byId('saveSmtpButton').addEventListener('click', saveSmtpConfig);
  byId('addSmtpButton').addEventListener('click', addSmtpConfig);
  byId('deleteSmtpButton').addEventListener('click', deleteSmtpConfig);
  byId('loadLiveCaptureSessions').addEventListener('click', loadLiveCaptureSessions);
  byId('saveLiveCaptureButton').addEventListener('click', saveLiveCapture);
  byId('smtpSenderQq').addEventListener('change', async function () {
    var senderQq = byId('smtpSenderQq').value;
    if (!senderQq || senderQq === state.smtpSenderQq) return;
    try {
      var result = await request('/qcca/smtp-config/select/' + encodeURIComponent(senderQq), { method: 'PUT' });
      applySmtpResult(result);
      renderSmtpSettings();
    } catch (error) {
      toast(error.message, 'error');
      renderSmtpSettings();
    }
  });
  byId('recentWorkspace').addEventListener('change', function () {
    state.draft.recent_workspace_and_session = {};
    renderRecentSelectors(byId('recentWorkspace').value);
    setDirty();
  });
  byId('recentSession').addEventListener('change', function () {
    var workspace = byId('recentWorkspace').value;
    var session = byId('recentSession').value;
    state.draft.recent_workspace_and_session = workspace && session ? Object.fromEntries([[workspace, session]]) : {};
    setDirty();
  });
  window.addEventListener('beforeunload', function (event) { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });

  renderIcons();
  byId('apiAddress').textContent = 'API · ' + API_BASE.replace(/^https?:\/\//, '');
  loadConfigs(false);
  window.setInterval(loadAudioModelStatus, 5000);
})();

// ========== PWA ==========
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/frontend/sw.js').catch(e => console.error('SW:', e));
}

// ========== Markdown ==========
if (typeof marked !== 'undefined') {
  marked.setOptions({ breaks: true, gfm: true, tables: true });
}

function renderMD(text) {
  if (typeof marked === 'undefined') return text.replace(/\n/g, '<br>');
  try {
    let html = marked.parse(text);
    // 將表格包裝在可滾動容器中
    html = html.replace(/<table>/g, '<div class="table-wrapper"><table>');
    html = html.replace(/<\/table>/g, '</table></div>');
    return html;
  } catch { return text.replace(/\n/g, '<br>'); }
}

function hasMD(text) {
  return /\|.*\|.*\n\s*\|[-\s|:]+\|/.test(text) || /\*\*.*\*\*/.test(text) || /#{1,6}\s/.test(text) || /^\s*[-*+]\s/m.test(text);
}

// ========== 狀態 ==========
let currentMode = 'smart';
let chats = {};
let chatId = null;
let chatBox = null;

// 帳號管理
let allUsers = [], currentPage = 1, pageSize = 15;
let currentPasswordTarget = null, currentEditRoleTarget = null, currentEditProfileTarget = null;

// 上傳
let pendingFiles = [];

// ========== 模式選擇 ==========
function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  const hints = {
    smart: '🧠 智慧模式：AI 自動判斷並搜尋所有資料',
    technical: '🔧 技術模式：搜尋技術規格、手冊',
    business: '📊 業務模式：搜尋客戶、活動資料',
    personal: '👤 個人模式：搜尋個人上傳的文件'
  };
  document.getElementById('mode-hint').textContent = hints[mode];
}

// ========== 聊天功能 ==========
function renderChatList() {
  const el = document.getElementById('chat-list');
  if (!el) return;
  
  const entries = Object.entries(chats);
  if (entries.length === 0) {
    el.innerHTML = '<p class="text-center text-sand-400 text-sm py-4">尚無對話</p>';
    return;
  }
  
  el.innerHTML = entries.reverse().map(([id, c]) => `
    <div class="chat-item group ${id === chatId ? 'active' : ''}" onclick="switchChat('${id}')">
      <div class="flex items-center justify-between gap-2">
        <span class="text-sm text-sand-700 dark:text-sand-300 truncate">${c.title || '新對話'}</span>
        <button onclick="event.stopPropagation();deleteChat('${id}')" class="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500 transition">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
    </div>
  `).join('');
}

function renderChat() {
  chatBox = document.getElementById('chat-box');
  if (!chatBox) return;
  
  const chat = chats[chatId];
  const welcome = document.getElementById('welcome-screen');
  const title = document.getElementById('chat-title');
  
  if (title) title.textContent = chat?.title || '新對話';
  
  if (!chat || !chat.messages || chat.messages.length === 0) {
    chatBox.innerHTML = '';
    if (welcome) { chatBox.appendChild(welcome); welcome.style.display = 'flex'; }
    return;
  }
  
  if (welcome) welcome.style.display = 'none';
  
  chatBox.innerHTML = '<div class="max-w-3xl mx-auto space-y-4">' + 
    chat.messages.map(m => msgHTML(m.role, m.text)).join('') + '</div>';
  chatBox.scrollTop = chatBox.scrollHeight;
}

function msgHTML(role, text) {
  if (role === 'user') {
    return `<div class="flex justify-end message-bubble">
      <div class="user-bubble max-w-[80%] px-4 py-3">
        <p class="text-sm">${text}</p>
      </div>
    </div>`;
  }
  const isMD = hasMD(text);
  const content = isMD ? renderMD(text) : text.replace(/\n/g, '<br>');
  return `<div class="flex items-start gap-3 message-bubble">
    <div class="w-8 h-8 rounded-full bg-gradient-to-br from-claude-400 to-claude-600 flex-shrink-0 flex items-center justify-center">
      <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
      </svg>
    </div>
    <div class="ai-bubble max-w-[80%] px-4 py-3 ${isMD ? 'md-content' : ''}">
      <div class="text-sm text-sand-800 dark:text-sand-200">${content}</div>
    </div>
  </div>`;
}

function appendMsg(role, text, loading = false) {
  const welcome = document.getElementById('welcome-screen');
  if (welcome) welcome.style.display = 'none';
  
  let container = chatBox.querySelector('.max-w-3xl');
  if (!container) {
    chatBox.innerHTML = '<div class="max-w-3xl mx-auto space-y-4"></div>';
    container = chatBox.querySelector('.max-w-3xl');
  }
  
  if (role === 'user') {
    container.innerHTML += `<div class="flex justify-end message-bubble">
      <div class="user-bubble max-w-[80%] px-4 py-3"><p class="text-sm">${text}</p></div>
    </div>`;
  } else {
    const loadingHTML = loading ? '<div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>' : text;
    container.innerHTML += `<div class="flex items-start gap-3 message-bubble">
      <div class="w-8 h-8 rounded-full bg-gradient-to-br from-claude-400 to-claude-600 flex-shrink-0 flex items-center justify-center">
        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
        </svg>
      </div>
      <div class="ai-bubble max-w-[80%] px-4 py-3">
        <div class="text-sm text-sand-800 dark:text-sand-200">${loadingHTML}</div>
      </div>
    </div>`;
  }
  chatBox.scrollTop = chatBox.scrollHeight;
}

function newChat() {
  chatId = Date.now().toString();
  chats[chatId] = { title: '新對話', messages: [] };
  saveChats();
  renderChat();
  renderChatList();
  closeSidebar();
}

function switchChat(id) {
  chatId = id;
  localStorage.setItem('chatId', chatId);
  renderChat();
  renderChatList();
  closeSidebar();
}

async function deleteChat(id) {
  if (!confirm('確定刪除此對話？')) return;
  try {
    await fetch('/chat_logs/' + id, { method: 'DELETE', headers: authHeader() });
    delete chats[id];
    if (chatId === id) {
      const keys = Object.keys(chats);
      chatId = keys.length ? keys[keys.length - 1] : Date.now().toString();
      if (!chats[chatId]) chats[chatId] = { title: '新對話', messages: [] };
    }
    saveChats();
    renderChat();
    renderChatList();
  } catch { alert('刪除失敗'); }
}

async function sendMessage() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  
  if (!chats[chatId]) {
    chatId = Date.now().toString();
    chats[chatId] = { title: '新對話', messages: [] };
    renderChatList();
  }
  
  chats[chatId].messages.push({ role: 'user', text });
  input.value = '';
  input.style.height = 'auto';
  
  appendMsg('user', text);
  appendMsg('ai', '', true);
  
  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ question: text, chat_id: chatId, user: localStorage.getItem('username'), mode: currentMode })
    });
    
    if (res.status === 401) { localStorage.removeItem('token'); alert('請重新登入'); location.reload(); return; }
    
    const data = await res.json();
    const container = chatBox.querySelector('.max-w-3xl');
    const lastMsg = container.lastElementChild;
    const bubble = lastMsg.querySelector('.ai-bubble > div');
    
    const answer = data.answer || '（無回應）';
    if (hasMD(answer)) {
      lastMsg.querySelector('.ai-bubble').classList.add('md-content');
      bubble.innerHTML = renderMD(answer);
    } else {
      bubble.innerHTML = answer.replace(/\n/g, '<br>');
    }
    
    // 來源標籤
    if (data.sources?.length) {
      let srcClass = 'src-tag';
      if (data.source_type === 'technical') srcClass += ' src-tech';
      else if (data.source_type === 'business') srcClass += ' src-biz';
      else if (data.source_type === 'personal') srcClass += ' src-personal';
      else srcClass += ' src-mix';
      
      bubble.innerHTML += `<div class="mt-3 pt-2 border-t border-sand-200 dark:border-sand-600">
        <div class="text-xs text-sand-500 mb-1">📋 來源：</div>
        <div class="flex flex-wrap gap-1">${data.sources.map(s => `<span class="${srcClass}">${s}</span>`).join('')}</div>
      </div>`;
    }
    
    // 圖片顯示（個人知識庫）
    if (data.images?.length) {
      const imageGrid = data.images.map(img => `
        <div class="relative group cursor-pointer" onclick="showImageLightbox('${img.url}', '${img.context || img.filename || ''}')">
          <img src="${img.url}" alt="${img.context || ''}" 
               class="w-24 h-24 object-cover rounded-lg border border-sand-200 dark:border-sand-600 hover:border-claude-500 transition" 
               loading="lazy"
               onerror="this.style.display='none'">
          <div class="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs p-1 rounded-b-lg truncate opacity-0 group-hover:opacity-100 transition">
            ${img.context?.slice(0, 30) || img.image_name || '圖片'}
          </div>
        </div>
      `).join('');
      
      bubble.innerHTML += `<div class="mt-3 pt-2 border-t border-sand-200 dark:border-sand-600">
        <div class="text-xs text-sand-500 mb-2">📷 相關圖片：</div>
        <div class="flex flex-wrap gap-2">${imageGrid}</div>
      </div>`;
    }
    
    chats[chatId].messages.push({ role: 'ai', text: answer });
    
    if ((!chats[chatId].title || chats[chatId].title === '新對話') && data.title) {
      chats[chatId].title = data.title;
      renderChatList();
      document.getElementById('chat-title').textContent = data.title;
    }
  } catch {
    const container = chatBox.querySelector('.max-w-3xl');
    const bubble = container.lastElementChild.querySelector('.ai-bubble > div');
    bubble.innerHTML = '❌ 無法取得回應';
    chats[chatId].messages.push({ role: 'ai', text: '❌ 無法取得回應' });
  }
  
  saveChats();
  chatBox.scrollTop = chatBox.scrollHeight;
}

// 圖片燈箱
function showImageLightbox(url, caption) {
  const lightbox = document.getElementById('image-lightbox') || createImageLightbox();
  const img = lightbox.querySelector('img');
  const cap = lightbox.querySelector('.lightbox-caption');
  
  img.src = url;
  if (cap) cap.textContent = caption;
  lightbox.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeImageLightbox() {
  const lightbox = document.getElementById('image-lightbox');
  if (lightbox) {
    lightbox.classList.add('hidden');
    document.body.style.overflow = '';
  }
}

function createImageLightbox() {
  const div = document.createElement('div');
  div.id = 'image-lightbox';
  div.className = 'fixed inset-0 bg-black/90 z-50 hidden flex items-center justify-center p-4';
  div.onclick = (e) => { if (e.target === div) closeImageLightbox(); };
  div.innerHTML = `
    <button onclick="closeImageLightbox()" class="absolute top-4 right-4 text-white hover:text-claude-400 text-3xl">&times;</button>
    <div class="max-w-4xl max-h-[90vh] flex flex-col items-center">
      <img src="" alt="" class="max-w-full max-h-[80vh] object-contain rounded-lg">
      <p class="lightbox-caption text-white text-center mt-4 text-sm"></p>
    </div>
  `;
  document.body.appendChild(div);
  return div;
}

function setExample(q) { document.getElementById('input').value = q; document.getElementById('input').focus(); }
function handleKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }
function saveChats() { localStorage.setItem('chats', JSON.stringify(chats)); localStorage.setItem('chatId', chatId); }

// ========== 認證 ==========
function authHeader() { return { Authorization: 'Bearer ' + localStorage.getItem('token') }; }

function parseJWT(token) {
  try {
    const parts = token.split('.');
    return parts.length === 3 ? JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))) : null;
  } catch { return null; }
}

function login() {
  const acc = document.getElementById('login-account').value.trim();
  const pwd = document.getElementById('login-password').value.trim();
  fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account: acc, password: pwd }) })
    .then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(d => {
      localStorage.setItem('token', d.token);
      localStorage.setItem('username', acc);
      localStorage.setItem('name', d.name);
      document.getElementById('login-error').classList.add('hidden');
      showChat();
      applyTheme(localStorage.getItem('theme') || 'light');
    })
    .catch(() => document.getElementById('login-error').classList.remove('hidden'));
}

function logout() { localStorage.clear(); location.reload(); }

async function showChat() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('chat-page').classList.remove('hidden');
  chats = {};
  
  try {
    const res = await fetch('/chat_ids/me', { headers: authHeader() });
    const list = await res.json();
    for (const item of list) {
      const logRes = await fetch('/chat_logs/' + item.chat_id, { headers: authHeader() });
      const logs = await logRes.json();
      chats[item.chat_id] = {
        title: item.title || '對話',
        messages: logs.flatMap(l => [{ role: 'user', text: l.question }, { role: 'ai', text: l.answer }])
      };
    }
    chatId = Object.keys(chats).pop() || Date.now().toString();
    if (!chats[chatId]) chats[chatId] = { title: '新對話', messages: [] };
    saveChats();
  } catch {
    chatId = Date.now().toString();
    chats[chatId] = { title: '新對話', messages: [] };
  }
  
  renderChat();
  renderChatList();
  
  const name = localStorage.getItem('name') || '';
  document.getElementById('user-info-dropdown').textContent = name;
  document.getElementById('user-avatar').textContent = name.charAt(0) || 'U';
}

// ========== UI 控制 ==========
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const bd = document.getElementById('sidebar-backdrop');
  sb.classList.toggle('-translate-x-full');
  bd.classList.toggle('hidden');
}

function closeSidebar() {
  document.getElementById('sidebar').classList.add('-translate-x-full');
  document.getElementById('sidebar-backdrop').classList.add('hidden');
}

function toggleDropdown() { document.getElementById('user-dropdown').classList.toggle('hidden'); }

function toggleTheme() {
  const next = (localStorage.getItem('theme') || 'light') === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  localStorage.setItem('theme', next);
}

function applyTheme(t) { document.documentElement.classList.toggle('dark', t === 'dark'); }

function handleResize() {
  if (window.innerWidth >= 768) {
    document.getElementById('sidebar').classList.remove('-translate-x-full');
    document.getElementById('sidebar-backdrop').classList.add('hidden');
  }
}

// ========== 知識庫 ==========
let currentDocType = 'technical';
let uploadInProgress = false;
let personalNotes = [];
let editingNoteId = null;

function openKnowledgeBase() {
  document.getElementById('kb-page').classList.remove('hidden');
  
  // 根據角色顯示/隱藏管理員功能
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  const isAdmin = payload?.role === 'admin';
  
  // 管理員專屬區塊
  const adminBiz = document.getElementById('admin-business-section');
  const adminUpload = document.getElementById('admin-upload-section');
  const reloadBtn = document.getElementById('reload-btn');
  
  if (adminBiz) adminBiz.classList.toggle('hidden', !isAdmin);
  if (adminUpload) adminUpload.classList.toggle('hidden', !isAdmin);
  if (reloadBtn) reloadBtn.classList.toggle('hidden', !isAdmin);
  
  // 載入資料
  refreshFileList();
  refreshKnowledgeStats();
  loadPersonalNotes();
  setupDropZone();
}

function closeKnowledgeBase() { 
  document.getElementById('kb-page').classList.add('hidden'); 
}

function setDocType(type) {
  currentDocType = type;
  document.querySelectorAll('.doc-type-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.type === type);
  });
  refreshFileList();
}

async function refreshFileList() {
  const el = document.getElementById('file-list');
  el.innerHTML = '<p class="text-sand-400 text-sm animate-pulse">載入中...</p>';
  
  try {
    const res = await fetch('/knowledge/files', { headers: authHeader() });
    const data = await res.json();
    
    // 根據當前類型過濾
    const files = data.files?.filter(f => f.type === currentDocType) || [];
    
    // 檢查是否為管理員（只有管理員能刪除）
    const token = localStorage.getItem('token');
    const isAdmin = parseJWT(token)?.role === 'admin';
    
    if (files.length) {
      el.innerHTML = files.map(f => `
        <div class="file-item flex items-center justify-between p-3 bg-sand-50 dark:bg-sand-700 rounded-lg group hover:bg-sand-100 dark:hover:bg-sand-600 transition">
          <div class="flex items-center gap-3 min-w-0">
            <span class="text-xl">${getFileIcon(f.name)}</span>
            <div class="min-w-0">
              <p class="text-sm font-medium text-sand-700 dark:text-sand-300 truncate">${f.name}</p>
              <p class="text-xs text-sand-500">${formatFileSize(f.size)} · ${formatDate(f.modified)}</p>
            </div>
          </div>
          ${isAdmin ? `
          <button onclick="deleteFile('${f.name}', '${f.type}')" 
            class="opacity-0 group-hover:opacity-100 p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
            </svg>
          </button>
          ` : ''}
        </div>
      `).join('');
    } else {
      el.innerHTML = `<div class="text-center py-8 text-sand-400">
        <svg class="w-12 h-12 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
        </svg>
        <p class="text-sm">尚無${currentDocType === 'technical' ? '技術文檔' : '業務資料'}</p>
      </div>`;
    }
  } catch (e) { 
    el.innerHTML = '<p class="text-red-500 text-sm">載入失敗: ' + e.message + '</p>'; 
  }
}

async function refreshKnowledgeStats() {
  try {
    // 知識庫統計
    const statsRes = await fetch('/knowledge/stats', { headers: authHeader() });
    const stats = await statsRes.json();
    
    document.getElementById('stat-docs').textContent = stats.technical?.files || stats.total_files || 0;
    document.getElementById('stat-biz').textContent = stats.business?.records || stats.business?.files || 0;
    document.getElementById('stat-notes').textContent = personalNotes.length || 0;
    
    // 系統狀態
    const sysRes = await fetch('/system/status', { headers: authHeader() });
    const sys = await sysRes.json();
    document.getElementById('stat-chunks').textContent = sys.tech_chunks || 0;
  } catch (e) {
    console.error('Stats error:', e);
  }
}

function getFileIcon(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const icons = {
    'pdf': '📕', 'docx': '📘', 'doc': '📘', 
    'md': '📝', 'txt': '📄', 'csv': '📊',
    'xlsx': '📊', 'xls': '📊', 'rtf': '📄'
  };
  return icons[ext] || '📄';
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function formatDate(isoStr) {
  const d = new Date(isoStr);
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function setupDropZone() {
  const dropZone = document.getElementById('drop-zone');
  if (!dropZone || dropZone.dataset.initialized) return;
  dropZone.dataset.initialized = 'true';
  
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, e => { e.preventDefault(); e.stopPropagation(); });
  });
  
  ['dragenter', 'dragover'].forEach(evt => {
    dropZone.addEventListener(evt, () => dropZone.classList.add('drag-over'));
  });
  
  ['dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, () => dropZone.classList.remove('drag-over'));
  });
  
  dropZone.addEventListener('drop', e => {
    const files = Array.from(e.dataTransfer.files);
    if (files.length) {
      pendingFiles = files;
      updateUploadList();
    }
  });
}

function handleFileSelect(e) {
  pendingFiles = Array.from(e.target.files);
  updateUploadList();
}

function updateUploadList() {
  const el = document.getElementById('upload-list');
  if (pendingFiles.length) {
    el.innerHTML = pendingFiles.map((f, i) => `
      <div class="flex items-center justify-between p-2 bg-sand-50 dark:bg-sand-700 rounded text-sm" data-idx="${i}">
        <span class="flex items-center gap-2">
          <span>${getFileIcon(f.name)}</span>
          <span class="text-sand-700 dark:text-sand-300 truncate max-w-[200px]">${f.name}</span>
          <span class="text-sand-400 text-xs">(${formatFileSize(f.size)})</span>
        </span>
        <span class="upload-status text-sand-400">待上傳</span>
      </div>
    `).join('');
    document.getElementById('upload-btn').classList.remove('hidden');
  } else {
    el.innerHTML = '';
    document.getElementById('upload-btn').classList.add('hidden');
  }
}

async function uploadFiles() {
  if (!pendingFiles.length || uploadInProgress) return;
  
  uploadInProgress = true;
  const btn = document.getElementById('upload-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 上傳中...';
  
  const results = [];
  
  for (let i = 0; i < pendingFiles.length; i++) {
    const file = pendingFiles[i];
    const statusEl = document.querySelector(`[data-idx="${i}"] .upload-status`);
    
    if (statusEl) statusEl.innerHTML = '<span class="animate-spin">⏳</span>';
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('doc_type', currentDocType);
      formData.append('auto_convert', 'true');
      
      const res = await fetch('/knowledge/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Upload failed');
      }
      
      const data = await res.json();
      results.push({ success: true, file: file.name, data });
      
      if (statusEl) {
        if (data.converted) {
          statusEl.innerHTML = '<span class="text-green-500">✅ 已轉換</span>';
        } else {
          statusEl.innerHTML = '<span class="text-green-500">✅ 已上傳</span>';
        }
      }
    } catch (e) {
      results.push({ success: false, file: file.name, error: e.message });
      if (statusEl) statusEl.innerHTML = `<span class="text-red-500">❌ ${e.message}</span>`;
    }
  }
  
  // 完成
  uploadInProgress = false;
  btn.disabled = false;
  btn.innerHTML = '📤 開始上傳';
  
  // 清除並刷新
  const successes = results.filter(r => r.success).length;
  if (successes > 0) {
    setTimeout(() => {
      pendingFiles = [];
      updateUploadList();
      refreshFileList();
      refreshKnowledgeStats();
    }, 1500);
  }
  
  // 顯示結果
  const failCount = results.length - successes;
  if (failCount > 0) {
    alert(`上傳完成: ${successes} 成功, ${failCount} 失敗`);
  }
}

async function deleteFile(filename, docType) {
  if (!confirm(`確定要刪除「${filename}」？`)) return;
  
  try {
    const res = await fetch(`/knowledge/files/${encodeURIComponent(filename)}?doc_type=${docType}`, {
      method: 'DELETE',
      headers: authHeader()
    });
    
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Delete failed');
    }
    
    refreshFileList();
    refreshKnowledgeStats();
  } catch (e) {
    alert('刪除失敗: ' + e.message);
  }
}

async function reloadIndex() {
  const btn = document.getElementById('reload-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 重建中...';
  
  try {
    const res = await fetch('/system/reload', {
      method: 'POST',
      headers: authHeader()
    });
    
    if (!res.ok) throw new Error('Reload failed');
    
    const data = await res.json();
    alert(`索引重建完成！\n技術文件: ${data.tech_files || 0}\nChunks: ${data.tech_chunks || 0}`);
    refreshKnowledgeStats();
  } catch (e) {
    alert('重建失敗: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔄 重建索引';
  }
}

// ========== 業務日報上傳 ==========
let businessFile = null;

function handleBusinessFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  
  businessFile = file;
  document.getElementById('business-file-name').textContent = `📄 ${file.name} (${formatFileSize(file.size)})`;
  document.getElementById('upload-business-btn').disabled = false;
}

async function uploadBusinessReport() {
  if (!businessFile) return;
  
  const btn = document.getElementById('upload-business-btn');
  const statusEl = document.getElementById('business-upload-status');
  const monthsToKeep = document.getElementById('months-to-keep').value;
  
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 處理中...';
  statusEl.classList.remove('hidden');
  statusEl.innerHTML = '<span class="text-sand-500">正在上傳並處理業務日報...</span>';
  
  try {
    const formData = new FormData();
    formData.append('file', businessFile);
    formData.append('months_to_keep', monthsToKeep);
    formData.append('merge_existing', 'true');
    formData.append('auto_reload', 'true');
    
    const res = await fetch('/knowledge/upload-business', {
      method: 'POST',
      headers: authHeader(),
      body: formData
    });
    
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }
    
    const data = await res.json();
    const stats = data.stats || {};
    
    // 顯示處理結果
    statusEl.innerHTML = `
      <div class="p-3 bg-green-50 dark:bg-green-900/20 rounded-lg text-green-700 dark:text-green-300">
        <p class="font-medium">✅ 處理完成！</p>
        <ul class="text-sm mt-2 space-y-1">
          <li>• 原始記錄: ${stats.raw_records || 0} 筆</li>
          <li>• 日期過濾: ${stats.filtered_by_date || 0} 筆（早於 ${stats.cutoff_date || '?'}）</li>
          <li>• 去重: ${stats.duplicates_removed || 0} 筆</li>
          <li>• 最終記錄: ${stats.final_records || 0} 筆</li>
          ${data.reloaded ? '<li>• ✅ 索引已重建</li>' : ''}
        </ul>
      </div>
    `;
    
    // 清除選擇
    businessFile = null;
    document.getElementById('business-file').value = '';
    document.getElementById('business-file-name').textContent = '點擊選擇業務日報 TXT 檔案';
    
    // 刷新統計
    refreshFileList();
    refreshKnowledgeStats();
    
  } catch (e) {
    statusEl.innerHTML = `<div class="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600 dark:text-red-400">
      <p class="font-medium">❌ 處理失敗</p>
      <p class="text-sm mt-1">${e.message}</p>
    </div>`;
  } finally {
    btn.disabled = !businessFile;
    btn.innerHTML = '🚀 處理並更新';
  }
}

// ========== 個人筆記 ==========

async function loadPersonalNotes() {
  const el = document.getElementById('notes-list');
  if (!el) return;
  
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  if (!payload) {
    el.innerHTML = '<p class="text-sand-400 text-sm text-center py-4">請先登入</p>';
    return;
  }
  
  el.innerHTML = '<p class="text-sand-400 text-sm text-center py-4 animate-pulse">載入中...</p>';
  
  const userAccount = payload.sub || payload.account;
  
  try {
    // 同時載入手寫筆記和個人知識庫文件
    const [notesRes, docsRes] = await Promise.all([
      fetch(`/kb/notes?user_account=${encodeURIComponent(userAccount)}`, { headers: authHeader() }).catch(() => null),
      fetch(`/kb/personal/documents?user_account=${encodeURIComponent(userAccount)}`, { headers: authHeader() }).catch(() => null)
    ]);
    
    // 處理手寫筆記
    let notes = [];
    if (notesRes?.ok) {
      const notesData = await notesRes.json();
      notes = (notesData.notes || []).map(n => ({ ...n, _type: 'note' }));
    }
    
    // 處理個人知識庫文件
    let docs = [];
    if (docsRes?.ok) {
      const docsData = await docsRes.json();
      docs = (docsData.documents || []).map(d => ({
        id: d.doc_id,
        title: d.filename,
        filename: d.filename,
        updated_at: d.upload_time,
        size: d.file_size,
        category: 'file',
        chunks: d.chunks,
        images: d.images,
        _type: 'doc'
      }));
    }
    
    // 合併並按時間排序
    personalNotes = [...notes, ...docs].sort((a, b) => 
      new Date(b.updated_at || 0) - new Date(a.updated_at || 0)
    );
    
    // 更新統計
    const statEl = document.getElementById('stat-notes');
    if (statEl) statEl.textContent = personalNotes.length;
    
    renderNotesList();
  } catch (e) {
    el.innerHTML = '<p class="text-sand-500 text-sm text-center py-4">尚無筆記，點擊上方新增</p>';
    personalNotes = [];
  }
}

function renderNotesList() {
  const el = document.getElementById('notes-list');
  
  if (!personalNotes || personalNotes.length === 0) {
    el.innerHTML = '<p class="text-sand-500 text-sm text-center py-4">尚無知識，上傳文件或手寫筆記開始</p>';
    return;
  }
  
  el.innerHTML = personalNotes.map(n => {
    // 判斷是個人知識庫文件、上傳文件還是手寫筆記
    const isPersonalDoc = n._type === 'doc';
    const isFile = n.category === 'file' || n.filename?.match(/\.(pdf|docx?|xlsx?|csv|png|jpg|jpeg)$/i);
    const icon = isPersonalDoc ? '📂' : (isFile ? getFileIcon(n.filename || n.title) : '📝');
    
    // 個人知識庫文件顯示額外資訊
    const extraInfo = isPersonalDoc ? 
      `<span class="text-xs text-blue-500 ml-2">${n.chunks || 0} 段落${n.images > 0 ? ` · ${n.images} 圖片` : ''}</span>` : '';
    
    // 刪除函數名稱
    const deleteFn = isPersonalDoc ? `deletePersonalDoc('${n.id}')` : `deleteNote('${n.id}')`;
    const viewFn = isPersonalDoc ? `viewPersonalDoc('${n.id}', '${escapeHtml(n.title)}')` : `viewNote('${n.id}')`;
    
    return `
    <div class="note-item flex items-center justify-between p-3 bg-sand-50 dark:bg-sand-700 rounded-lg group hover:bg-sand-100 dark:hover:bg-sand-600 transition cursor-pointer ${isPersonalDoc ? 'border-l-4 border-blue-400' : ''}"
         onclick="${viewFn}">
      <div class="flex items-center gap-3 min-w-0 flex-1">
        <span class="text-lg">${icon}</span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-sand-700 dark:text-sand-300 truncate">${escapeHtml(n.title)}${extraInfo}</p>
          <p class="text-xs text-sand-500 mt-0.5">${formatRelativeTime(n.updated_at)}${n.size ? ' · ' + formatFileSize(n.size) : ''}</p>
          ${n.tags?.length ? `<div class="flex flex-wrap gap-1 mt-1">${n.tags.slice(0, 3).map(t => `<span class="text-xs px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-300 rounded">${escapeHtml(t)}</span>`).join('')}${n.tags.length > 3 ? `<span class="text-xs text-sand-400">+${n.tags.length - 3}</span>` : ''}</div>` : ''}
        </div>
      </div>
      <button onclick="event.stopPropagation();${deleteFn}" 
        class="opacity-0 group-hover:opacity-100 p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition ml-2">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
        </svg>
      </button>
    </div>
  `;
  }).join('');
}

// 刪除個人知識庫文件
async function deletePersonalDoc(docId) {
  if (!confirm('確定要刪除這個文件嗎？')) return;
  
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  const userAccount = payload?.sub || payload?.account || 'default';
  
  try {
    const res = await fetch(`/kb/personal/documents/${docId}?user_account=${encodeURIComponent(userAccount)}`, {
      method: 'DELETE',
      headers: authHeader()
    });
    
    if (res.ok) {
      showToast('✅ 文件已刪除');
      await loadPersonalNotes();
    } else {
      throw new Error('刪除失敗');
    }
  } catch (e) {
    showToast('❌ 刪除失敗: ' + e.message, 'error');
  }
}

// 查看個人知識庫文件
function viewPersonalDoc(docId, filename) {
  alert(`文件：${filename}\n\n此文件已被索引，可在「個人模式」下查詢相關內容。`);
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  
  if (diff < 60) return '剛剛';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分鐘前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前';
  if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showNoteEditor(noteId = null) {
  editingNoteId = noteId;
  
  const modal = document.getElementById('note-editor-modal');
  modal.classList.remove('hidden');
  
  if (noteId) {
    // 編輯模式
    const note = personalNotes.find(n => n.id === noteId);
    if (note) {
      document.getElementById('note-title').value = note.title || '';
      document.getElementById('note-content').value = note.content || '';
      document.getElementById('note-tags').value = (note.tags || []).join(', ');
    }
    document.getElementById('note-editor-title').textContent = '編輯筆記';
  } else {
    // 新增模式
    document.getElementById('note-title').value = '';
    document.getElementById('note-content').value = '';
    document.getElementById('note-tags').value = '';
    document.getElementById('note-editor-title').textContent = '新增筆記';
  }
  
  setTimeout(() => document.getElementById('note-title').focus(), 100);
}

function closeNoteEditor() {
  document.getElementById('note-editor-modal').classList.add('hidden');
  editingNoteId = null;
}

async function saveNote() {
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  if (!payload) return alert('請先登入');
  
  const title = document.getElementById('note-title').value.trim();
  const content = document.getElementById('note-content').value.trim();
  const tagsStr = document.getElementById('note-tags').value.trim();
  
  if (!title) return alert('請輸入標題');
  if (!content) return alert('請輸入內容');
  
  const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(t => t) : [];
  
  const btn = document.getElementById('save-note-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 儲存中...';
  
  try {
    const userAccount = encodeURIComponent(payload.sub || payload.account);
    const isEdit = !!editingNoteId;
    const url = isEdit 
      ? `/kb/notes/${editingNoteId}?user_account=${userAccount}`
      : `/kb/notes?user_account=${userAccount}`;
    
    const res = await fetch(url, {
      method: isEdit ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ title, content, tags })
    });
    
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || '儲存失敗');
    }
    
    closeNoteEditor();
    await loadPersonalNotes();
    
  } catch (e) {
    alert('儲存失敗: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💾 儲存筆記';
  }
}

async function viewNote(noteId) {
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  if (!payload) return;
  
  try {
    const userAccount = encodeURIComponent(payload.sub || payload.account);
    const res = await fetch(`/kb/notes/${noteId}?user_account=${userAccount}`, { headers: authHeader() });
    
    if (!res.ok) throw new Error('載入失敗');
    
    const note = await res.json();
    
    // 更新本地資料
    const idx = personalNotes.findIndex(n => n.id === noteId);
    if (idx >= 0) {
      personalNotes[idx] = { ...personalNotes[idx], ...note };
    }
    
    // 開啟編輯器
    showNoteEditor(noteId);
    document.getElementById('note-content').value = note.content || '';
    
  } catch (e) {
    alert('載入失敗: ' + e.message);
  }
}

async function deleteNote(noteId) {
  if (!confirm('確定要刪除此筆記？')) return;
  
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  if (!payload) return;
  
  try {
    const userAccount = encodeURIComponent(payload.sub || payload.account);
    const res = await fetch(`/kb/notes/${noteId}?user_account=${userAccount}`, {
      method: 'DELETE',
      headers: authHeader()
    });
    
    if (!res.ok) throw new Error('刪除失敗');
    
    await loadPersonalNotes();
    
  } catch (e) {
    alert('刪除失敗: ' + e.message);
  }
}

// ========== 個人文件上傳 ==========

async function handlePersonalFileUpload(event) {
  const files = Array.from(event.target.files);
  if (!files.length) return;
  
  const token = localStorage.getItem('token');
  const payload = parseJWT(token);
  if (!payload) return alert('請先登入');
  
  const statusEl = document.getElementById('personal-upload-status');
  statusEl.classList.remove('hidden');
  statusEl.innerHTML = `<div class="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
    <p class="text-sm text-blue-600 dark:text-blue-300"><span class="animate-spin inline-block">⏳</span> 正在上傳 ${files.length} 個文件...</p>
  </div>`;
  
  const results = [];
  const userAccount = payload.sub || payload.account;
  
  for (const file of files) {
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      // 🆕 使用新的個人知識庫 API
      const res = await fetch(`/kb/personal/upload?user_account=${encodeURIComponent(userAccount)}`, {
        method: 'POST',
        headers: authHeader(),
        body: formData
      });
      
      const data = await res.json();
      
      if (!res.ok || !data.success) {
        throw new Error(data.message || data.detail || '上傳失敗');
      }
      
      results.push({ 
        success: true, 
        file: file.name, 
        chunks: data.chunks,
        images: data.images,
        keywords: data.keywords
      });
    } catch (e) {
      results.push({ success: false, file: file.name, error: e.message });
    }
  }
  
  // 顯示結果
  const successes = results.filter(r => r.success);
  const failures = results.filter(r => !r.success);
  
  if (failures.length === 0) {
    const totalChunks = successes.reduce((sum, s) => sum + (s.chunks || 0), 0);
    const totalImages = successes.reduce((sum, s) => sum + (s.images || 0), 0);
    statusEl.innerHTML = `<div class="p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
      <p class="text-sm text-green-600 dark:text-green-300">✅ ${successes.length} 個文件處理成功</p>
      <p class="text-xs text-green-500 mt-1">共 ${totalChunks} 段落${totalImages > 0 ? `、${totalImages} 張圖片` : ''}</p>
    </div>`;
  } else {
    statusEl.innerHTML = `<div class="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
      <p class="text-sm text-yellow-700 dark:text-yellow-300">⚠️ ${successes.length} 成功, ${failures.length} 失敗</p>
      ${failures.map(f => `<p class="text-xs text-red-500 mt-1">${f.file}: ${f.error}</p>`).join('')}
    </div>`;
  }
  
  // 清除 input 並刷新列表
  event.target.value = '';
  await loadPersonalNotes();
  
  // 5 秒後隱藏狀態
  setTimeout(() => {
    statusEl.classList.add('hidden');
  }, 5000);
}

// ========== 帳號管理 ==========
function toggleAdmin() {
  const token = localStorage.getItem('token');
  if (!token) return alert('請先登入');
  const payload = parseJWT(token);
  if (!payload) return alert('Token 無效');
  
  const isAdmin = payload.role === 'admin';
  document.getElementById('create-user-btn').classList.toggle('hidden', !isAdmin);
  
  if (isAdmin) {
    fetch('/users', { headers: authHeader() }).then(r => r.json()).then(d => { allUsers = d; currentPage = 1; renderUserTable(); });
  } else {
    fetch('/users/' + (payload.sub || payload.account), { headers: authHeader() }).then(r => r.json()).then(d => { allUsers = [d]; renderUserTable(); });
  }
  
  document.getElementById('chat-page').classList.add('hidden');
  document.getElementById('admin-page').classList.remove('hidden');
  document.getElementById('user-dropdown').classList.add('hidden');
}

function closeAdmin() {
  document.getElementById('admin-page').classList.add('hidden');
  document.getElementById('chat-page').classList.remove('hidden');
}

function renderUserTable() {
  const tb = document.getElementById('user-table');
  if (!allUsers.length) { tb.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-sand-500">無資料</td></tr>'; return; }
  
  const token = localStorage.getItem('token');
  const isAdmin = parseJWT(token)?.role === 'admin';
  const start = (currentPage - 1) * pageSize;
  const page = allUsers.slice(start, start + pageSize);
  
  tb.innerHTML = page.map(u => {
    const ops = isAdmin ? `
      <button onclick="openProfileModal('${u.account}')" class="text-xs text-blue-500 hover:underline">資料</button>
      <button onclick="resetPasswordPrompt('${u.account}')" class="text-xs text-claude-600 hover:underline">密碼</button>
      <button onclick="openRoleModal('${u.account}')" class="text-xs text-green-500 hover:underline">權限</button>
      <button onclick="deleteUser('${u.account}')" class="text-xs text-red-500 hover:underline">刪除</button>
    ` : '';
    return `<tr class="hover:bg-sand-50 dark:hover:bg-sand-700/50">
      <td class="px-4 py-3 text-sm">${u.account}</td>
      <td class="px-4 py-3 text-sm">${u.name}</td>
      <td class="px-4 py-3 text-sm text-sand-500">${u.department || '-'}</td>
      <td class="px-4 py-3"><span class="px-2 py-1 text-xs rounded-full ${u.role === 'admin' ? 'bg-claude-100 text-claude-700' : 'bg-sand-100 text-sand-600'}">${u.role}</span></td>
      <td class="px-4 py-3 space-x-2">${ops}</td>
    </tr>`;
  }).join('');
  
  renderPagination();
}

function renderPagination() {
  const el = document.getElementById('pagination');
  const total = Math.ceil(allUsers.length / pageSize);
  if (total <= 1) { el.innerHTML = ''; return; }
  
  let html = '';
  if (currentPage > 1) html += `<button onclick="currentPage--;renderUserTable()" class="btn-ghost px-3 py-1">←</button>`;
  for (let i = 1; i <= total; i++) {
    html += `<button onclick="currentPage=${i};renderUserTable()" class="${i === currentPage ? 'px-3 py-1 rounded bg-claude-500 text-white' : 'btn-ghost px-3 py-1'}">${i}</button>`;
  }
  if (currentPage < total) html += `<button onclick="currentPage++;renderUserTable()" class="btn-ghost px-3 py-1">→</button>`;
  el.innerHTML = html;
}

function openCreateModal() { document.getElementById('create-modal').classList.remove('hidden'); }
function closeCreateModal() {
  document.getElementById('create-modal').classList.add('hidden');
  ['modal-acc', 'modal-pw1', 'modal-pw2', 'modal-name'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('modal-dept').value = '';
  document.getElementById('modal-role').value = 'user';
}

function submitCreateUser() {
  const acc = document.getElementById('modal-acc').value.trim();
  const pw1 = document.getElementById('modal-pw1').value.trim();
  const pw2 = document.getElementById('modal-pw2').value.trim();
  const name = document.getElementById('modal-name').value.trim();
  const dept = document.getElementById('modal-dept').value;
  const role = document.getElementById('modal-role').value;
  
  if (!acc || !pw1 || !name || !dept) return alert('請填完所有欄位');
  if (pw1 !== pw2) return alert('密碼不一致');
  
  fetch('/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ account: acc, password: pw1, name, department: dept, role })
  }).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(() => { alert('新增成功'); closeCreateModal(); toggleAdmin(); })
    .catch(() => alert('新增失敗'));
}

function openProfileModal(acc) {
  currentEditProfileTarget = acc;
  const u = allUsers.find(x => x.account === acc);
  if (u) {
    document.getElementById('edit-name').value = u.name || '';
    document.getElementById('edit-dept').value = u.department || '';
  }
  document.getElementById('edit-profile-modal').classList.remove('hidden');
}
function closeProfileModal() { document.getElementById('edit-profile-modal').classList.add('hidden'); currentEditProfileTarget = null; }
function submitEditProfile() {
  if (!currentEditProfileTarget) return;
  fetch('/users/' + currentEditProfileTarget + '/profile', {
    method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ name: document.getElementById('edit-name').value.trim(), department: document.getElementById('edit-dept').value })
  }).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(() => { alert('修改成功'); closeProfileModal(); toggleAdmin(); })
    .catch(() => alert('修改失敗'));
}

function resetPasswordPrompt(acc) { currentPasswordTarget = acc; document.getElementById('password-modal').classList.remove('hidden'); }
function changeOwnPassword() {
  const payload = parseJWT(localStorage.getItem('token'));
  if (!payload) return;
  currentPasswordTarget = payload.sub || payload.account;
  document.getElementById('password-modal').classList.remove('hidden');
  document.getElementById('user-dropdown').classList.add('hidden');
}
function closePasswordModal() {
  document.getElementById('password-modal').classList.add('hidden');
  document.getElementById('pw1').value = '';
  document.getElementById('pw2').value = '';
  currentPasswordTarget = null;
}
function submitPasswordChange() {
  const pw1 = document.getElementById('pw1').value.trim();
  const pw2 = document.getElementById('pw2').value.trim();
  if (!pw1 || pw1 !== pw2) return alert('密碼不一致或為空');
  if (!currentPasswordTarget) return;
  fetch('/users/' + currentPasswordTarget + '/password', {
    method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ password: pw1 })
  }).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(() => { alert('修改成功'); closePasswordModal(); })
    .catch(() => alert('修改失敗'));
}

function openRoleModal(acc) {
  currentEditRoleTarget = acc;
  const u = allUsers.find(x => x.account === acc);
  if (u) document.getElementById('edit-role').value = u.role;
  document.getElementById('edit-role-modal').classList.remove('hidden');
}
function closeRoleModal() { document.getElementById('edit-role-modal').classList.add('hidden'); currentEditRoleTarget = null; }
function submitEditRole() {
  if (!currentEditRoleTarget) return;
  fetch('/users/' + currentEditRoleTarget + '/role', {
    method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ role: document.getElementById('edit-role').value })
  }).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(() => { alert('修改成功'); closeRoleModal(); toggleAdmin(); })
    .catch(() => alert('修改失敗'));
}

function deleteUser(acc) {
  if (!confirm('確定刪除 ' + acc + '？')) return;
  fetch('/users/' + acc, { method: 'DELETE', headers: authHeader() })
    .then(r => { if (!r.ok) throw new Error(); alert('刪除成功'); toggleAdmin(); })
    .catch(() => alert('刪除失敗'));
}

// ========== 初始化 ==========
window.onload = () => {
  document.getElementById('sidebar-toggle')?.addEventListener('click', toggleSidebar);
  document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
  
  applyTheme(localStorage.getItem('theme') || 'light');
  window.addEventListener('resize', handleResize);
  handleResize();
  
  // 輸入框自動調整高度
  const input = document.getElementById('input');
  if (input) {
    input.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }
  
  if (localStorage.getItem('token')) showChat();
};

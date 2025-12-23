// ========== 知識庫模組 v2 ==========
// 包含：多層級管理、個人筆記、業務日報

// ─────────────────────────────────────────────────────────
// 狀態
// ─────────────────────────────────────────────────────────

let kbState = {
  currentScope: 'public',     // public | department | personal
  currentCategory: 'technical', // technical | business | note
  pendingFiles: [],
  businessFile: null,
  notes: [],
  editingNoteId: null,
};

// ─────────────────────────────────────────────────────────
// 工具函數
// ─────────────────────────────────────────────────────────

function getUserInfo() {
  const token = localStorage.getItem('token');
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch { return null; }
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
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  
  if (diff < 60) return '剛剛';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分鐘前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前';
  if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
  return formatDate(isoStr);
}

// ─────────────────────────────────────────────────────────
// 知識庫頁面控制
// ─────────────────────────────────────────────────────────

function openKnowledgeBase() {
  document.getElementById('kb-page').classList.remove('hidden');
  initKnowledgeBase();
}

function closeKnowledgeBase() {
  document.getElementById('kb-page').classList.add('hidden');
}

function initKnowledgeBase() {
  setupDropZone();
  refreshKBStats();
  refreshFileList();
  loadPersonalNotes();
}

function setKBScope(scope) {
  kbState.currentScope = scope;
  document.querySelectorAll('.kb-scope-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.scope === scope);
  });
  refreshFileList();
}

function setKBCategory(category) {
  kbState.currentCategory = category;
  document.querySelectorAll('.kb-category-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.category === category);
  });
  refreshFileList();
}

// ─────────────────────────────────────────────────────────
// 統計資訊
// ─────────────────────────────────────────────────────────

async function refreshKBStats() {
  const user = getUserInfo();
  
  try {
    // 新版 API
    const params = new URLSearchParams();
    if (user) {
      params.set('user_account', user.sub || '');
      params.set('user_department', user.department || '');
    }
    
    const res = await fetch(`/kb/stats?${params}`, { headers: authHeader() });
    const data = await res.json();
    
    // 更新顯示
    const multiScope = data.multi_scope || {};
    const legacy = data.legacy || {};
    
    document.getElementById('stat-docs').textContent = 
      (legacy.technical_files || 0) + (multiScope.public?.total || 0);
    document.getElementById('stat-biz').textContent = legacy.business_records || 0;
    document.getElementById('stat-personal').textContent = multiScope.personal || 0;
    
    // 系統狀態
    const sysRes = await fetch('/system/status', { headers: authHeader() });
    const sys = await sysRes.json();
    document.getElementById('stat-chunks').textContent = sys.tech_chunks || 0;
    
  } catch (e) {
    console.error('Stats error:', e);
    // 退回舊版 API
    try {
      const res = await fetch('/knowledge/stats', { headers: authHeader() });
      const data = await res.json();
      document.getElementById('stat-docs').textContent = data.total_files || 0;
    } catch {}
  }
}

// ─────────────────────────────────────────────────────────
// 檔案列表
// ─────────────────────────────────────────────────────────

async function refreshFileList() {
  const el = document.getElementById('file-list');
  el.innerHTML = '<p class="text-sand-400 text-sm animate-pulse">載入中...</p>';
  
  const user = getUserInfo();
  
  try {
    // 嘗試新版 API
    const params = new URLSearchParams({
      scope: kbState.currentScope,
    });
    if (user) {
      params.set('user_account', user.sub || '');
      params.set('user_department', user.department || '');
    }
    
    const res = await fetch(`/kb/files?${params}`, { headers: authHeader() });
    const data = await res.json();
    
    // 根據範圍取得檔案
    let files = [];
    if (kbState.currentScope === 'personal') {
      files = data.personal || [];
    } else if (kbState.currentScope === 'department') {
      files = data.department || [];
    } else {
      // 公用庫 - 合併 technical 和 public
      files = [...(data.technical || []), ...(data.public || [])];
    }
    
    // 根據類別過濾
    if (kbState.currentCategory !== 'all') {
      files = files.filter(f => {
        if (kbState.currentCategory === 'business') {
          return f.category === 'business' || f.name.includes('business');
        }
        return f.category === kbState.currentCategory || !f.category;
      });
    }
    
    renderFileList(files);
    
  } catch (e) {
    console.error('File list error:', e);
    // 退回舊版 API
    try {
      const res = await fetch('/knowledge/files', { headers: authHeader() });
      const data = await res.json();
      const files = (data.files || []).filter(f => f.type === kbState.currentCategory);
      renderFileList(files);
    } catch {
      el.innerHTML = '<p class="text-red-500 text-sm">載入失敗</p>';
    }
  }
}

function renderFileList(files) {
  const el = document.getElementById('file-list');
  
  if (!files || files.length === 0) {
    el.innerHTML = `
      <div class="text-center py-8 text-sand-400">
        <svg class="w-12 h-12 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
        </svg>
        <p class="text-sm">尚無文件</p>
      </div>`;
    return;
  }
  
  el.innerHTML = files.map(f => `
    <div class="file-item flex items-center justify-between p-3 bg-sand-50 dark:bg-sand-700 rounded-lg group hover:bg-sand-100 dark:hover:bg-sand-600 transition">
      <div class="flex items-center gap-3 min-w-0">
        <span class="text-xl">${getFileIcon(f.name)}</span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-sand-700 dark:text-sand-300 truncate">${f.name}</p>
          <p class="text-xs text-sand-500">${formatFileSize(f.size)} · ${formatRelativeTime(f.modified)}</p>
        </div>
      </div>
      <button onclick="deleteKBFile('${f.name}', '${f.scope || kbState.currentScope}')" 
        class="opacity-0 group-hover:opacity-100 p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
        </svg>
      </button>
    </div>
  `).join('');
}

async function deleteKBFile(filename, scope) {
  if (!confirm(`確定要刪除「${filename}」？`)) return;
  
  const user = getUserInfo();
  const params = new URLSearchParams({
    scope: scope,
    category: kbState.currentCategory,
  });
  if (user) {
    params.set('user_account', user.sub || '');
    params.set('user_department', user.department || '');
  }
  
  try {
    const res = await fetch(`/kb/files/${encodeURIComponent(filename)}?${params}`, {
      method: 'DELETE',
      headers: authHeader()
    });
    
    if (!res.ok) throw new Error('刪除失敗');
    
    refreshFileList();
    refreshKBStats();
  } catch (e) {
    alert('刪除失敗: ' + e.message);
  }
}

// ─────────────────────────────────────────────────────────
// 檔案上傳
// ─────────────────────────────────────────────────────────

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
      kbState.pendingFiles = files;
      updateUploadList();
    }
  });
}

function handleFileSelect(e) {
  kbState.pendingFiles = Array.from(e.target.files);
  updateUploadList();
}

function updateUploadList() {
  const el = document.getElementById('upload-list');
  const files = kbState.pendingFiles;
  
  if (files.length) {
    el.innerHTML = files.map((f, i) => `
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
  const files = kbState.pendingFiles;
  if (!files.length) return;
  
  const btn = document.getElementById('upload-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 上傳中...';
  
  const user = getUserInfo();
  const results = [];
  
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const statusEl = document.querySelector(`[data-idx="${i}"] .upload-status`);
    if (statusEl) statusEl.innerHTML = '<span class="animate-spin">⏳</span>';
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('scope', kbState.currentScope);
      formData.append('category', kbState.currentCategory);
      formData.append('auto_convert', 'true');
      if (user) {
        formData.append('user_account', user.sub || '');
        formData.append('user_department', user.department || '');
      }
      
      const res = await fetch('/kb/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData
      });
      
      if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed');
      
      const data = await res.json();
      results.push({ success: true, file: file.name, data });
      
      if (statusEl) {
        statusEl.innerHTML = data.converted 
          ? '<span class="text-green-500">✅ 已轉換</span>'
          : '<span class="text-green-500">✅ 已上傳</span>';
      }
    } catch (e) {
      results.push({ success: false, file: file.name, error: e.message });
      if (statusEl) statusEl.innerHTML = `<span class="text-red-500">❌</span>`;
    }
  }
  
  btn.disabled = false;
  btn.innerHTML = '📤 開始上傳';
  
  const successes = results.filter(r => r.success).length;
  if (successes > 0) {
    setTimeout(() => {
      kbState.pendingFiles = [];
      updateUploadList();
      refreshFileList();
      refreshKBStats();
    }, 1500);
  }
  
  if (results.length - successes > 0) {
    alert(`上傳完成: ${successes} 成功, ${results.length - successes} 失敗`);
  }
}

// ─────────────────────────────────────────────────────────
// 業務日報
// ─────────────────────────────────────────────────────────

function handleBusinessFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  
  kbState.businessFile = file;
  document.getElementById('business-file-name').textContent = `📄 ${file.name} (${formatFileSize(file.size)})`;
  document.getElementById('upload-business-btn').disabled = false;
}

async function uploadBusinessReport() {
  const file = kbState.businessFile;
  if (!file) return;
  
  const btn = document.getElementById('upload-business-btn');
  const statusEl = document.getElementById('business-upload-status');
  const months = document.getElementById('months-to-keep').value;
  
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 處理中...';
  statusEl.classList.remove('hidden');
  statusEl.innerHTML = '<span class="text-sand-500">正在處理業務日報...</span>';
  
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('months_to_keep', months);
    formData.append('auto_reload', 'true');
    
    const res = await fetch('/kb/business/upload', {
      method: 'POST',
      headers: authHeader(),
      body: formData
    });
    
    if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed');
    
    const data = await res.json();
    const stats = data.stats || {};
    
    statusEl.innerHTML = `
      <div class="p-3 bg-green-50 dark:bg-green-900/20 rounded-lg text-green-700 dark:text-green-300">
        <p class="font-medium">✅ 處理完成！</p>
        <ul class="text-sm mt-2 space-y-1">
          <li>• 原始記錄: ${stats.raw_records || 0} 筆</li>
          <li>• 日期過濾: ${stats.filtered_by_date || 0} 筆</li>
          <li>• 最終記錄: ${stats.final_records || 0} 筆</li>
          ${data.reloaded ? '<li>• ✅ 索引已重建</li>' : ''}
        </ul>
      </div>
    `;
    
    kbState.businessFile = null;
    document.getElementById('business-file').value = '';
    document.getElementById('business-file-name').textContent = '點擊選擇業務日報檔案';
    
    refreshKBStats();
    
  } catch (e) {
    statusEl.innerHTML = `
      <div class="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600">
        <p class="font-medium">❌ 處理失敗</p>
        <p class="text-sm mt-1">${e.message}</p>
      </div>
    `;
  } finally {
    btn.disabled = !kbState.businessFile;
    btn.innerHTML = '🚀 處理並更新';
  }
}

// ─────────────────────────────────────────────────────────
// 個人筆記
// ─────────────────────────────────────────────────────────

async function loadPersonalNotes() {
  const user = getUserInfo();
  if (!user) return;
  
  const el = document.getElementById('notes-list');
  if (!el) return;
  
  el.innerHTML = '<p class="text-sand-400 text-sm animate-pulse">載入中...</p>';
  
  try {
    const res = await fetch(`/kb/notes?user_account=${user.sub || ''}`, { headers: authHeader() });
    const data = await res.json();
    
    kbState.notes = data.notes || [];
    renderNotesList();
  } catch (e) {
    el.innerHTML = '<p class="text-sand-500 text-sm">尚無筆記</p>';
  }
}

function renderNotesList() {
  const el = document.getElementById('notes-list');
  const notes = kbState.notes;
  
  if (!notes || notes.length === 0) {
    el.innerHTML = '<p class="text-sand-500 text-sm">尚無筆記，點擊上方新增</p>';
    return;
  }
  
  el.innerHTML = notes.map(n => `
    <div class="note-item p-3 bg-sand-50 dark:bg-sand-700 rounded-lg group hover:bg-sand-100 dark:hover:bg-sand-600 transition cursor-pointer"
         onclick="viewNote('${n.id}')">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-sand-700 dark:text-sand-300 truncate">${n.title}</p>
          <p class="text-xs text-sand-500 mt-1">${formatRelativeTime(n.updated_at)}</p>
          ${n.tags?.length ? `<div class="flex flex-wrap gap-1 mt-2">${n.tags.map(t => `<span class="text-xs px-2 py-0.5 bg-claude-100 dark:bg-claude-900 text-claude-600 dark:text-claude-300 rounded-full">${t}</span>`).join('')}</div>` : ''}
        </div>
        <button onclick="event.stopPropagation();deleteNote('${n.id}')" 
          class="opacity-0 group-hover:opacity-100 p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
    </div>
  `).join('');
}

function showNoteEditor(noteId = null) {
  kbState.editingNoteId = noteId;
  
  const modal = document.getElementById('note-editor-modal');
  modal.classList.remove('hidden');
  
  if (noteId) {
    // 編輯模式
    const note = kbState.notes.find(n => n.id === noteId);
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
  
  document.getElementById('note-title').focus();
}

function closeNoteEditor() {
  document.getElementById('note-editor-modal').classList.add('hidden');
  kbState.editingNoteId = null;
}

async function saveNote() {
  const user = getUserInfo();
  if (!user) return alert('請先登入');
  
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
    const isEdit = !!kbState.editingNoteId;
    const url = isEdit 
      ? `/kb/notes/${kbState.editingNoteId}?user_account=${user.sub}`
      : `/kb/notes?user_account=${user.sub}`;
    
    const res = await fetch(url, {
      method: isEdit ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ title, content, tags })
    });
    
    if (!res.ok) throw new Error((await res.json()).detail || '儲存失敗');
    
    closeNoteEditor();
    loadPersonalNotes();
    refreshKBStats();
    
  } catch (e) {
    alert('儲存失敗: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💾 儲存';
  }
}

async function viewNote(noteId) {
  const user = getUserInfo();
  if (!user) return;
  
  try {
    const res = await fetch(`/kb/notes/${noteId}?user_account=${user.sub}`, { headers: authHeader() });
    if (!res.ok) throw new Error('載入失敗');
    
    const note = await res.json();
    
    // 更新本地資料並開啟編輯器
    const idx = kbState.notes.findIndex(n => n.id === noteId);
    if (idx >= 0) {
      kbState.notes[idx] = { ...kbState.notes[idx], ...note };
    }
    
    showNoteEditor(noteId);
    document.getElementById('note-content').value = note.content || '';
    
  } catch (e) {
    alert('載入失敗: ' + e.message);
  }
}

async function deleteNote(noteId) {
  if (!confirm('確定要刪除此筆記？')) return;
  
  const user = getUserInfo();
  if (!user) return;
  
  try {
    const res = await fetch(`/kb/notes/${noteId}?user_account=${user.sub}`, {
      method: 'DELETE',
      headers: authHeader()
    });
    
    if (!res.ok) throw new Error('刪除失敗');
    
    loadPersonalNotes();
    refreshKBStats();
    
  } catch (e) {
    alert('刪除失敗: ' + e.message);
  }
}

// ─────────────────────────────────────────────────────────
// 索引重建
// ─────────────────────────────────────────────────────────

async function reloadIndex() {
  const btn = document.getElementById('reload-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 重建中...';
  
  try {
    const res = await fetch('/system/reload', { method: 'POST', headers: authHeader() });
    if (!res.ok) throw new Error('重建失敗');
    
    const data = await res.json();
    alert(`索引重建完成！\n文件: ${data.tech_files || 0}\nChunks: ${data.tech_chunks || 0}`);
    refreshKBStats();
  } catch (e) {
    alert('重建失敗: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔄 重建索引';
  }
}

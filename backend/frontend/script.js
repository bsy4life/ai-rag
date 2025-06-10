// ✅ PWA 的 Service Worker 註冊（路徑為 /frontend/sw.js）
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/frontend/sw.js')
    .then(reg => console.log('✅ Service Worker 註冊成功'))
    .catch(err => console.error('❌ Service Worker 註冊失敗', err));
}

// ============================================================
// 1. 帳號管理 & 修改密碼 相關函式
// ============================================================

// 暫存：目前要修改密碼或編輯權限的目標帳號
let currentPasswordTarget = null;
let currentEditRoleTarget = null;
let currentEditProfileTarget = null;

// 分頁 & 使用者資料暫存
let allUsers = [];
let currentPage = 1;
const pageSize = 15;
/**
 * A. 渲染使用者表格（分頁）
 *    根據目前登入者是否為 admin，決定「操作功能」哪些按鈕顯示
 */
function renderUserTable() {
  const table = document.getElementById('user-table');
  const pagination = document.getElementById('pagination');
  table.innerHTML = '';
  pagination.innerHTML = '';

  if (!allUsers || allUsers.length === 0) {
    table.innerHTML = `
      <tr>
        <td class="border dark:border-gray-600 p-2 text-center dark:text-gray-100" colspan="5">沒有任何使用者資料</td>
      </tr>`;
    return;
  }

  // 先解析出目前使用者是否為 admin
  const rawToken = localStorage.getItem('token');
  const payload = rawToken ? parseJwtPayload(rawToken) : null;
  const isAdmin = payload && payload.role === 'admin';

  // 分頁計算
  const start = (currentPage - 1) * pageSize;
  const pageData = allUsers.slice(start, start + pageSize);

  // 產生表格列
  table.innerHTML = pageData
    .map(u => {
      // 如果是 admin，就顯示所有操作按鈕；否則留空白
      let ops = '';
      if (isAdmin) {
        ops = `
        <button onclick="openProfileModal('${u.account}')" class="text-blue-500 dark:text-blue-300 hover:underline">修改個人資料</button>
        <button onclick="resetPasswordPrompt('${u.account}')" class="text-blue-500 dark:text-blue-300 hover:underline">修改密碼</button>
        <button onclick="openRoleModal('${u.account}')" class="text-green-500 dark:text-green-300 hover:underline">修改權限</button>
        <button onclick="deleteUser('${u.account}')" class="text-red-500 dark:text-red-400 hover:underline">刪除帳號</button>
      `;
      }
	return `
		<tr class="bg-white dark:bg-gray-800">
		<td class="border dark:border-gray-600 p-2 text-center dark:text-gray-100 break-words min-w-[4rem]">${u.account}</td>
		<td class="border dark:border-gray-600 p-2 text-center dark:text-gray-100 break-words min-w-[5.5rem]">${u.name}</td>
		<td class="border dark:border-gray-600 p-2 text-center dark:text-gray-100 break-words min-w-[5.5rem]">${u.department || ''}</td>
		<td class="border dark:border-gray-600 p-2 text-center dark:text-gray-100 break-words min-w-[3.5rem]">${u.role}</td>
		<td class="border dark:border-gray-600 p-2 space-x-2 text-center break-words min-w-[7rem] max-w-[8rem]">${ops}</td>
	  </tr>
	`;
    })
    .join('');

  renderPagination();
}

/**
 * B. 繪製分頁按鈕
 */
function renderPagination() {
  const pagination = document.getElementById('pagination');
  const totalPages = Math.ceil(allUsers.length / pageSize);
  if (totalPages <= 1) return;

  if (currentPage > 1) {
    const prevBtn = document.createElement('button');
    prevBtn.textContent = '←';
    prevBtn.className = 'px-2 py-1 border rounded font-bold text-black dark:text-white bg-white dark:bg-gray-800';
    prevBtn.onclick = () => {
      currentPage--;
      renderUserTable();
    };
    pagination.appendChild(prevBtn);
  }

  for (let i = 1; i <= totalPages; i++) {
    const btn = document.createElement('button');
    btn.textContent = i;
    btn.className = `px-2 py-1 border rounded font-semibold ${
  i === currentPage
    ? 'bg-blue-600 text-white dark:text-white'
    : 'text-gray-800 dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700'
}`;
    btn.onclick = () => {
      currentPage = i;
      renderUserTable();
    };
    pagination.appendChild(btn);
  }

  if (currentPage < totalPages) {
    const nextBtn = document.createElement('button');
    nextBtn.textContent = '→';
    nextBtn.className = 'px-2 py-1 border rounded font-bold text-black dark:text-white bg-white dark:bg-gray-800';
    nextBtn.onclick = () => {
      currentPage++;
      renderUserTable();
    };
    pagination.appendChild(nextBtn);
  }
}

/**
 * C. 切換到「帳號管理」畫面
 */
function toggleAdmin() {
  const rawToken = localStorage.getItem('token');
  if (!rawToken) {
    alert('❌ 請先登入');
    return;
  }

  // 解析 JWT，看是否為 admin
  const payload = parseJwtPayload(rawToken);
  if (!payload) {
    alert('❌ 無法解析 Token');
    return;
  }
  const role = payload.role;
  const account = payload.sub || payload.account;

  // 取得「新增使用者」按鈕的 DOM 參考
  const createBtn = document.getElementById('create-user-btn');

  if (role === 'admin') {
    // 管理者：顯示新增使用者按鈕，並取得所有使用者
    if (createBtn) createBtn.classList.remove('hidden');

    fetch('/users', {
      headers: { Authorization: 'Bearer ' + rawToken }
    })
      .then(r => {
        if (!r.ok) throw new Error('無法取得所有使用者');
        return r.json();
      })
      .then(allData => {
        allUsers = allData;
        currentPage = 1;
        renderUserTable();
        document.getElementById('chat-page').classList.add('hidden');
        document.getElementById('admin-page').classList.remove('hidden');
      })
      .catch(err => {
        alert('❌ 無法取得使用者清單：' + err.message);
      });
  } else {
    // 非管理者：隱藏「新增使用者」按鈕，只顯示自己
    if (createBtn) createBtn.classList.add('hidden');

    fetch(`/users/${account}`, {
      headers: { Authorization: 'Bearer ' + rawToken }
    })
      .then(r => {
        if (!r.ok) throw new Error('無法取得使用者資料');
        return r.json();
      })
      .then(userData => {
        allUsers = [
          {
            account: userData.account,
            name: userData.name,
            department: userData.department,
            role: userData.role
          }
        ];
        currentPage = 1;
        renderUserTable();
        document.getElementById('chat-page').classList.add('hidden');
        document.getElementById('admin-page').classList.remove('hidden');
      })
      .catch(err => {
        alert('❌ 取得個人資料失敗：' + err.message);
      });
  }
}

/**
 * D. 關閉「帳號管理」畫面，回到聊天
 */
function closeAdmin() {
  document.getElementById('admin-page').classList.add('hidden');
  document.getElementById('chat-page').classList.remove('hidden');
}

/**
 * E. 解析 JWT Token，取出 Payload
 */
function parseJwtPayload(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

/**
 * F. 修改自己密碼：按下時開啟 Modal
 */
function changeOwnPassword() {
  const account = localStorage.getItem('username');
  if (!account) {
    alert('❌ 請先登入');
    return;
  }
  openPasswordModal(account);
}

/**
 * G. 管理員重置別人密碼（在帳號管理表格按下時）
 */
function resetPasswordPrompt(account) {
  openPasswordModal(account);
}

/**
 * H. 開啟「修改密碼 Modal」
 */
function openPasswordModal(account) {
  currentPasswordTarget = account;
  document.getElementById('pw1').value = '';
  document.getElementById('pw2').value = '';
  document.getElementById('password-modal').classList.remove('hidden');
}

/**
 * I. 關閉「修改密碼 Modal」
 */
function closePasswordModal() {
  document.getElementById('password-modal').classList.add('hidden');
}

/**
 * J. 提交「修改密碼」請求
 */
function submitPasswordChange() {
  const pw1 = document.getElementById('pw1').value.trim();
  const pw2 = document.getElementById('pw2').value.trim();
  if (!pw1 || pw1.length < 6) {
    alert('❗ 密碼需至少 6 位數');
    return;
  }
  if (pw1 !== pw2) {
    alert('❗ 兩次輸入的密碼不一致');
    return;
  }

  fetch(`/users/${currentPasswordTarget}/password`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + localStorage.getItem('token')
    },
    body: JSON.stringify({ password: pw1 })
  })
    .then(res => {
      if (!res.ok) throw new Error('後端修改密碼失敗');
      alert('✅ 密碼已更新');
      closePasswordModal();
    })
    .catch(err => {
      alert('❌ 密碼更新失敗：' + err.message);
    });
}

// ------------------------------------------------------------
// 2. 帳號管理中新增 / 編輯 / 刪除 等相關函式
// ------------------------------------------------------------

/**
 * 開啟「新增使用者 Modal」
 */
function openCreateModal() {
  document.getElementById('create-modal').classList.remove('hidden');
}

/**
 * 關閉「新增使用者 Modal」
 */
function closeCreateModal() {
  document.getElementById('create-modal').classList.add('hidden');
}

/**
 * 送出「新增使用者」請求
 */
function submitCreateUser() {
  const account = document.getElementById('modal-acc').value.trim();
  const pw1 = document.getElementById('modal-pw1').value.trim();
  const pw2 = document.getElementById('modal-pw2').value.trim();
  const name = document.getElementById('modal-name').value.trim();
  const dept = document.getElementById('modal-dept').value;
  const role = document.getElementById('modal-role').value;

  if (!account || !pw1 || !pw2 || !name || !dept || !role) {
    alert('❗ 請填寫所有欄位');
    return;
  }
  if (pw1 !== pw2) {
    alert('❗ 兩次輸入的密碼不一致');
    return;
  }

  fetch('/users', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + localStorage.getItem('token')
    },
    body: JSON.stringify({
      account: account,
      password: pw1,
      name: name,
      department: dept,
      role: role
    })
  })
    .then(res => {
      if (!res.ok) throw new Error('後端新增使用者失敗');
      return res.json();
    })
    .then(data => {
      alert('✅ 使用者已新增');
      closeCreateModal();
      // 重新載入使用者列表
      toggleAdmin();
    })
    .catch(err => {
      alert('❌ 新增使用者失敗：' + err.message);
    });
}

/**
 * 開啟「編輯個人資料 Modal」
 */
function openProfileModal(account) {
  currentEditProfileTarget = account;
  // 先抓該使用者資料填進表單
  fetch(`/users/${account}`, {
    headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }
  })
    .then(res => {
      if (!res.ok) throw new Error('無法取得使用者資料');
      return res.json();
    })
    .then(data => {
      document.getElementById('edit-name').value = data.name || '';
      document.getElementById('edit-dept').value = data.department || '';
      document.getElementById('edit-profile-modal').classList.remove('hidden');
    })
    .catch(err => {
      alert('❌ 取得資料失敗：' + err.message);
    });
}

/**
 * 關閉「編輯個人資料 Modal」
 */
function closeProfileModal() {
  document.getElementById('edit-profile-modal').classList.add('hidden');
}

/**
 * 送出「修改個人資料」請求
 */
function submitEditProfile() {
  const newName = document.getElementById('edit-name').value.trim();
  const newDept = document.getElementById('edit-dept').value;
  if (!newName || !newDept) {
    alert('❗ 請填寫姓名與部門');
    return;
  }
  fetch(`/users/${currentEditProfileTarget}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + localStorage.getItem('token')
    },
    body: JSON.stringify({ name: newName, department: newDept })
  })
    .then(res => {
      if (!res.ok) throw new Error('後端修改資料失敗');
      alert('✅ 個人資料已更新');
      closeProfileModal();
      // 刷新帳號管理頁面
      toggleAdmin();
    })
    .catch(err => {
      alert('❌ 修改失敗：' + err.message);
    });
}

/**
 * 開啟「編輯權限 Modal」
 */
function openRoleModal(account) {
  currentEditRoleTarget = account;
  // 取得該使用者目前角色，並設為 select 的預設值
  fetch(`/users/${account}`, {
    headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }
  })
    .then(res => {
      if (!res.ok) throw new Error('無法取得使用者資料');
      return res.json();
    })
    .then(data => {
      document.getElementById('edit-role').value = data.role || 'user';
      document.getElementById('edit-role-modal').classList.remove('hidden');
    })
    .catch(err => {
      alert('❌ 取得資料失敗：' + err.message);
    });
}

/**
 * 關閉「編輯權限 Modal」
 */
function closeRoleModal() {
  document.getElementById('edit-role-modal').classList.add('hidden');
}

/**
 * 送出「修改權限」請求
 */
function submitEditRole() {
  const newRole = document.getElementById('edit-role').value;
  fetch(`/users/${currentEditRoleTarget}/role`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + localStorage.getItem('token')
    },
    body: JSON.stringify({ role: newRole })
  })
    .then(res => {
      if (!res.ok) throw new Error('後端修改權限失敗');
      alert('✅ 權限已更新');
      closeRoleModal();
      // 刷新帳號管理頁面
      toggleAdmin();
    })
    .catch(err => {
      alert('❌ 修改失敗：' + err.message);
    });
}

/**
 * 刪除使用者
 */
function deleteUser(account) {
  if (!confirm(`確定要刪除使用者 ${account} 嗎？`)) return;
  fetch(`/users/${account}`, {
    method: 'DELETE',
    headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }
  })
    .then(res => {
      if (!res.ok) throw new Error('後端刪除使用者失敗');
      alert('✅ 使用者已刪除');
      // 刷新帳號管理頁面
      toggleAdmin();
    })
    .catch(err => {
      alert('❌ 刪除失敗：' + err.message);
    });
}

// ============================================================
// 2. 聊天、登入登出、夜間模式 與 側邊欄 切換
// ============================================================

// 如果 localStorage 中沒有 chats，就先初始化
let chats = JSON.parse(localStorage.getItem('chats') || '{}');
let chatId = localStorage.getItem('chatId') || Date.now().toString();
if (!chats[chatId]) chats[chatId] = { title: '新對話', messages: [] };
localStorage.setItem('chatId', chatId);

const chatBox = document.getElementById('chat-box');
const input = document.getElementById('input');

/**
 * A. 插入訊息泡泡
 */
function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = role === 'user' ? 'text-right' : 'text-left';
  const bubble = document.createElement('div');
  bubble.className = `inline-block p-2 rounded-lg max-w-[75%] ${
    role === 'user'
      ? 'bg-blue-200 dark:bg-blue-800 text-gray-800 dark:text-gray-100'
      : 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
  }`;
  bubble.textContent = text;
  div.appendChild(bubble);
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

/**
 * B. 渲染聊天歷史
 */
function renderChat() {
  const box = document.getElementById('chat-box');
  box.innerHTML = '';
  if (!chats[chatId]) return;
  for (const msg of chats[chatId].messages) {
    appendMessage(msg.role, msg.text);
  }
}

/**
 * C. 渲染對話列表（sidebar）
 */
function renderChatList() {
  const list = document.getElementById('chat-list');
  list.innerHTML = '';

  // 行動版：沒有任何對話時隱藏「＋ 新對話」按鈕
  const newBtn = document.getElementById('mobile-new-chat-btn');
  if (Object.keys(chats).length === 0) {
    newBtn.classList.add('hidden');
  } else {
    newBtn.classList.remove('hidden');
  }

  for (const id in chats) {
    const btn = document.createElement('button');
    btn.className = `block w-full text-left px-2 py-1 rounded text-gray-800 dark:text-white ${id === chatId ? 'bg-blue-100 dark:bg-blue-900' : 'hover:bg-gray-200 dark:hover:bg-gray-700'}`;
    btn.innerHTML = `
      <span class="truncate">${chats[id].title || '新對話'}</span>
      <button onclick="renameChat('${id}')" class="ml-1 text-xs text-blue-500 dark:text-blue-300 hover:underline">✏️</button>
      <button onclick="deleteChat('${id}')" class="ml-1 text-xs text-red-500 dark:text-red-400 hover:underline">🗑️</button>
    `;
    btn.onclick = () => {
      chatId = id;
      localStorage.setItem('chatId', chatId);
      renderChat();
      renderChatList();
      closeSidebar(); // 切換對話後，行動版自動關閉側邊欄
    };
    list.appendChild(btn);
  }
}

/**
 * D. 新增一筆空對話
 */
function newChat() {
  chatId = Date.now().toString();
  chats[chatId] = { title: '新對話', messages: [] };
  localStorage.setItem('chatId', chatId);
  renderChat();
  renderChatList();
  closeSidebar(); // 創建後，行動版自動關閉側邊欄
}

/**
 * E. 重新命名對話
 */
function renameChat(id) {
  const newTitle = prompt("請輸入新標題：", chats[id].title);
  if (!newTitle) return;
  chats[id].title = newTitle;
  localStorage.setItem("chats", JSON.stringify(chats));
  renderChatList();
  fetch(`/chat_logs/${id}/title`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + localStorage.getItem("token")
    },
    body: JSON.stringify({ title: newTitle })
  })
    .then(res => {
      if (!res.ok) throw new Error("更新失敗");
      return res.json();
    })
    .then(data => console.log("✅ 標題已更新", data))
    .catch(err => alert("❌ 標題更新失敗"));
}

/**
 * F. 刪除對話
 */
async function deleteChat(id) {
  if (!confirm("確定要刪除此對話？")) return;
  try {
    const res = await fetch(`/chat_logs/${id}`, {
      method: 'DELETE',
      headers: {
        'Authorization': 'Bearer ' + localStorage.getItem('token')
      }
    });
    if (!res.ok) throw new Error("刪除失敗");
    delete chats[id];
    if (chatId === id) {
      const keys = Object.keys(chats);
      if (keys.length > 0) {
        chatId = keys[keys.length - 1];
      } else {
        chatId = Date.now().toString();
        chats[chatId] = { title: '新對話', messages: [] };
      }
    }
    localStorage.setItem("chats", JSON.stringify(chats));
    localStorage.setItem("chatId", chatId);
    renderChat();
    renderChatList();
    alert("✅ 對話已刪除");
  } catch (err) {
    alert("❌ 無法刪除對話，請稍後再試");
    console.error(err);
  }
}

/**
 * G. 傳送訊息給後端
 */
async function sendMessage() {
  const text = document.getElementById('input').value.trim();
  if (!text) return;
  if (!chats[chatId]) {
    chatId = Date.now().toString();
    chats[chatId] = { title: '新對話', messages: [] };
    localStorage.setItem("chatId", chatId);
    renderChatList();
  }
  chats[chatId].messages.push({ role: 'user', text });
  document.getElementById('input').value = '';
  appendMessage('user', text);
  appendMessage('ai', '🤖 思考中...');
  try {
    const token = localStorage.getItem('token');
    const username = localStorage.getItem('username');
    const res = await fetch('/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ question: text, chat_id: chatId, user: username })
    });
    if (res.status === 401) {
      localStorage.removeItem('token');
      alert("登入已過期，請重新登入");
      location.reload();
      return;
    }
    const data = await res.json();
    const aiResponseBubble = chatBox.lastChild.querySelector('div');
    aiResponseBubble.textContent = data.answer || '（無回應）';
    if (data.sources?.length) {
      const note = document.createElement('div');
      note.className = 'text-xs text-gray-500 dark:text-gray-400 mt-1';
      note.textContent = `📎 參考資料：${data.sources.join(', ')}`;
      aiResponseBubble.appendChild(document.createElement('br'));
      aiResponseBubble.appendChild(note);
    }
    chats[chatId].messages.push({ role: 'ai', text: data.answer });
    if ((!chats[chatId].title || chats[chatId].title === '新對話') && data.title) {
      chats[chatId].title = data.title;
      renderChatList();
    }
  } catch {
    const aiResponseBubble = chatBox.lastChild.querySelector('div');
    aiResponseBubble.textContent = '❌ 錯誤：無法取得回應';
    chats[chatId].messages.push({ role: 'ai', text: '❌ 錯誤：無法取得回應' });
  }
  localStorage.setItem('chats', JSON.stringify(chats));
}

/**
 * H. 登入
 */
function login() {
  const account = document.getElementById('login-account').value.trim();
  const password = document.getElementById('login-password').value.trim();
  const err = document.getElementById('login-error');
  fetch('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password })
  })
    .then(res => {
      if (!res.ok) throw new Error();
      return res.json();
    })
    .then(data => {
      localStorage.setItem('token', data.token);
      localStorage.setItem('username', account);
      localStorage.setItem('name', data.name);
      err.classList.add('hidden');
      showChat();
      // 預先設定「夜間模式」樣式
      applyTheme(localStorage.getItem('theme') || 'light');
    })
    .catch(() => err.classList.remove('hidden'));
}

/**
 * I. 登出
 */
function logout() {
  localStorage.clear();
  location.reload();
}

/**
 * J. 顯示聊天畫面並載入歷史對話
 */
async function showChat() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('chat-page').classList.remove('hidden');
  chats = {};
  try {
    const res = await fetch('/chat_ids/me', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }
    });
    const chatList = await res.json();
    for (const item of chatList) {
      const chatRes = await fetch(`/chat_logs/${item.chat_id}`, {
        headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }
      });
      const logs = await chatRes.json();
      chats[item.chat_id] = {
        title: item.title || `對話 ${Object.keys(chats).length + 1}`,
        messages: logs.flatMap(log => [
          { role: "user", text: log.question },
          { role: "ai", text: log.answer }
        ])
      };
    }
    chatId = Object.keys(chats).pop() || Date.now().toString();
    localStorage.setItem("chats", JSON.stringify(chats));
    localStorage.setItem("chatId", chatId);
  } catch (err) {
    console.warn("⚠️ 無法載入歷史紀錄", err);
  }
  renderChat();
  renderChatList();
  document.getElementById('user-info-dropdown').textContent = localStorage.getItem('name') || '';
}

/**
 * K. 切換使用者下拉選單
 */
function toggleDropdown() {
  const dd = document.getElementById('user-dropdown');
  dd.classList.toggle('hidden');
}

// ============================================================
// 3. 側邊欄（Drawer）開關 & 遮罩 & 夜間模式
// ============================================================

/**
 * 打開/關閉側邊欄（行動版 <768px 有動畫，桌機版 ≥768px 永遠展開）
 */
function toggleSidebar() {
  console.log("toggleSidebar() 被呼叫");
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (sidebar.classList.contains("-translate-x-full")) {
    // 隱藏 → 開啟
    sidebar.classList.remove("-translate-x-full");
    backdrop.classList.remove("hidden");
  } else {
    // 開啟 → 隱藏
    sidebar.classList.add("-translate-x-full");
    backdrop.classList.add("hidden");
  }
}

/**
 * 點擊遮罩收回側邊欄
 */
function closeSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  sidebar.classList.add("-translate-x-full");
  backdrop.classList.add("hidden");
}

/**
 * 監聽視窗大小變動：桌機版 (≥768px) 時側邊欄永遠展開、遮罩隱藏
 */
function handleResize() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (window.innerWidth >= 768) {
    sidebar.classList.remove("-translate-x-full");
    backdrop.classList.add("hidden");
  }
}
/**
 * 切換夜間模式：light <-> dark
 */
function toggleTheme() {
  const htmlEl = document.documentElement;
  if (htmlEl.classList.contains('dark')) {
    applyTheme('light');
  } else {
    applyTheme('dark');
  }
}

/**
 * 根據 theme 參數 ( 'light' 或 'dark' )，套用樣式並記到 localStorage
 */
function applyTheme(theme) {
  const htmlEl = document.documentElement;
  const themeToggleBtn = document.getElementById('theme-toggle');
  if (theme === 'dark') {
    htmlEl.classList.add('dark');
    localStorage.setItem('theme', 'dark');
    themeToggleBtn.textContent = '☀️';
  } else {
    htmlEl.classList.remove('dark');
    localStorage.setItem('theme', 'light');
    themeToggleBtn.textContent = '🌙';
  }
}
// ============================================================
// 4. 初始化：綁定按鈕與載入
// ============================================================

window.onload = () => {
  // 綁定「☰」按鈕
  const toggleBtn = document.getElementById("sidebar-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", toggleSidebar);

  // 綁定「夜間模式」切換按鈕
  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", toggleTheme);
  // 預設套用 user 偏好
  applyTheme(localStorage.getItem('theme') || 'light');

  // 監聽視窗 resize，確保桌機版側邊欄展開
  //window.addEventListener("resize", handleResize);
  //handleResize();

  // 綁定使用者下拉選單裡的項目
  const adminBtn = document.querySelector('[onclick="toggleAdmin()"]');
  if (adminBtn) adminBtn.onclick = toggleAdmin;

  const pwdBtn = document.querySelector('[onclick="changeOwnPassword()"]');
  if (pwdBtn) pwdBtn.onclick = changeOwnPassword;

  const closePwdBtn = document.querySelector('[onclick="closePasswordModal()"]');
  if (closePwdBtn) closePwdBtn.onclick = closePasswordModal;

  const submitPwdBtn = document.querySelector('[onclick="submitPasswordChange()"]');
  if (submitPwdBtn) submitPwdBtn.onclick = submitPasswordChange;

  // 登入後自動載入聊天
  const token = localStorage.getItem('token');
  if (token) showChat();
};
// ✅ 監聽 PWA 可安裝事件
window.addEventListener('beforeinstallprompt', (e) => {
  console.log('📦 PWA 可安裝，Chrome 將自動處理提示');
  // ✅ 不再使用 preventDefault()，讓瀏覽器自己跳出提示
});

window.addEventListener('appinstalled', () => {
  console.log('✅ PWA 已成功安裝');
});
/*let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  console.log('📦 beforeinstallprompt 被觸發');
  e.preventDefault();
  deferredPrompt = e;

  const installBtn = document.getElementById('install-btn');
  installBtn.style.display = 'inline-block';

  installBtn.addEventListener('click', () => {
    console.log('🖱️ 使用者點了安裝');

    // ⚠️ 安全檢查：已經失效就不呼叫 prompt
    if (!deferredPrompt || typeof deferredPrompt.prompt !== 'function') {
      console.warn('⚠️ prompt() 不可用（可能已被瀏覽器自動觸發）');
      return;
    }

    deferredPrompt.prompt(); // ✅ 只會執行一次

    deferredPrompt.userChoice.then((choiceResult) => {
      console.log('📥 使用者選擇:', choiceResult.outcome);
      if (choiceResult.outcome === 'accepted') {
        console.log('🎉 使用者接受安裝');
      } else {
        console.log('❌ 使用者拒絕安裝');
      }
      deferredPrompt = null;
      installBtn.style.display = 'none';
    }).catch((err) => {
      console.error('❌ prompt 錯誤:', err);
    });
  }, { once: true });
});
window.addEventListener('appinstalled', () => {
  console.log('✅ PWA 安裝成功！');
});
const installBtn = document.getElementById('install-btn');
if (installBtn) {
  installBtn.style.display = 'block';
  installBtn.addEventListener('click', () => {
    // 自訂安裝邏輯
  });
}*/
// 自動滾動輸入欄位到可見範圍（避免被鍵盤遮住）
document.querySelectorAll('input').forEach(input => {
  input.addEventListener('focus', () => {
    setTimeout(() => {
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 300);
  });
});


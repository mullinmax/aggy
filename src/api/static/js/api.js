// API client for Aggy
const api = {
  getToken() {
    return localStorage.getItem('aggy_token');
  },

  async request(method, path, body, isForm) {
    const headers = {};
    const token = this.getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const opts = { method, headers };

    if (body && isForm) {
      const formData = new URLSearchParams();
      for (const [k, v] of Object.entries(body)) formData.append(k, v);
      opts.body = formData;
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    } else if (body) {
      opts.body = JSON.stringify(body);
      headers['Content-Type'] = 'application/json';
    }

    const resp = await fetch(path, opts);
    if (resp.status === 401) {
      localStorage.removeItem('aggy_token');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${resp.status})`);
    }
    if (resp.status === 204) return null;
    return resp.json();
  },

  // Auth
  login(username, password) {
    return this.request('POST', '/auth/form_login', { username, password }, true);
  },

  signup(username, password) {
    return this.request('POST', '/auth/signup', { username, password });
  },

  userInfo() {
    return this.request('GET', '/auth/user_info');
  },

  // Feeds
  listFeeds() {
    return this.request('GET', '/feed/list');
  },

  createFeed(name) {
    return this.request('POST', `/feed/create?feed_name=${encodeURIComponent(name)}`);
  },

  deleteFeed(hash) {
    return this.request('DELETE', `/feed/delete?feed_name_hash=${encodeURIComponent(hash)}`);
  },

  getFeedItems(hash, skip, limit) {
    let url = `/feed/items?feed_name_hash=${encodeURIComponent(hash)}`;
    if (skip != null) url += `&skip=${skip}`;
    if (limit != null) url += `&limit=${limit}`;
    return this.request('GET', url);
  },

  getFeedSources(hash) {
    return this.request('GET', `/feed/sources?feed_name_hash=${encodeURIComponent(hash)}`);
  },

  // Sources
  createSource(feedHash, name, url) {
    return this.request('POST',
      `/source/create?feed_name_hash=${encodeURIComponent(feedHash)}&source_name=${encodeURIComponent(name)}&source_url=${encodeURIComponent(url)}`
    );
  },

  deleteSource(feedHash, sourceHash) {
    return this.request('DELETE',
      `/source/delete?feed_name_hash=${encodeURIComponent(feedHash)}&source_name_hash=${encodeURIComponent(sourceHash)}`
    );
  },

  // Source Templates
  searchTemplates(query, skip, limit) {
    let url = `/source_template/search?query=${encodeURIComponent(query)}`;
    if (skip != null) url += `&skip=${skip}`;
    if (limit != null) url += `&limit=${limit}`;
    return this.request('GET', url);
  },

  getTemplate(hash) {
    return this.request('GET', `/source_template/get?name_hash=${encodeURIComponent(hash)}`);
  },

  createSourceFromTemplate(templateHash, feedHash, sourceName, params) {
    return this.request('POST', '/source_template/create', {
      source_template_name_hash: templateHash,
      feed_hash: feedHash,
      source_name: sourceName,
      parameters: params
    });
  },

  // Items
  setItemState(feedHash, itemUrlHash, score, isRead) {
    let url = `/item/set_state?feed_hash=${encodeURIComponent(feedHash)}&item_url_hash=${encodeURIComponent(itemUrlHash)}`;
    if (score != null) url += `&score=${score}`;
    if (isRead != null) url += `&is_read=${isRead}`;
    return this.request('POST', url);
  },

  getItemState(feedHash, itemUrlHash) {
    return this.request('GET',
      `/item/get_state?feed_hash=${encodeURIComponent(feedHash)}&item_url_hash=${encodeURIComponent(itemUrlHash)}`
    );
  }
};

// Toast notifications
function toast(message, type = 'success') {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => { el.remove(); }, 3500);
}

// Modal helpers
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

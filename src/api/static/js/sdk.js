// Auto-generated from OpenAPI spec — do not edit by hand.
// Regenerate: cd src/api && python generate_sdk.py

class AggySDK {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
    this.token = null;
  }

  setToken(token) {
    this.token = token;
  }

  async _request(method, path, { query, body, form } = {}) {
    const headers = {};
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;

    let url = this.baseUrl + path;
    if (query) {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v != null) p.append(k, String(v));
      }
      const qs = p.toString();
      if (qs) url += '?' + qs;
    }

    const opts = { method, headers };
    if (form) {
      opts.body = new URLSearchParams(form);
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    } else if (body) {
      opts.body = JSON.stringify(body);
      headers['Content-Type'] = 'application/json';
    }

    const resp = await fetch(url, opts);
    if (!resp.ok) {
      if (resp.status === 401) this.token = null;
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${resp.status})`);
    }
    const text = await resp.text();
    if (!text) return null;
    return JSON.parse(text);
  }

  /** Login via OAuth form */
  async authFormLogin({ formData }) {
    return this._request("POST", "/auth/form_login", { form: formData });
  }

  /** Login with AuthUser */
  async authLogin({ body }) {
    return this._request("POST", "/auth/login", { body });
  }

  /** Create a user */
  async authSignup({ body }) {
    return this._request("POST", "/auth/signup", { body });
  }

  /** Confirm token is valid */
  async authTokenCheck() {
    return this._request("GET", "/auth/token_check");
  }

  /** Get username from token */
  async authUserInfo() {
    return this._request("GET", "/auth/user_info");
  }

  /** Create a feed */
  async feedCreate({ feed_name }) {
    return this._request("POST", "/feed/create", { query: { feed_name } });
  }

  /** Delete a feed */
  async feedDelete({ feed_name_hash }) {
    return this._request("DELETE", "/feed/delete", { query: { feed_name_hash } });
  }

  /** Get a feed */
  async feedGet({ feed_name_hash }) {
    return this._request("GET", "/feed/get", { query: { feed_name_hash } });
  }

  /** List all items in a feed */
  async feedItems({ feed_name_hash, skip, limit }) {
    return this._request("GET", "/feed/items", { query: { feed_name_hash, skip, limit } });
  }

  /** List feeds a user has created */
  async feedList() {
    return this._request("GET", "/feed/list");
  }

  /** List all sources in a feed */
  async feedSources({ feed_name_hash }) {
    return this._request("GET", "/feed/sources", { query: { feed_name_hash } });
  }

  /** Health */
  async health() {
    return this._request("GET", "/health");
  }

  /** Get State */
  async itemGetState({ feed_hash, item_url_hash }) {
    return this._request("GET", "/item/get_state", { query: { feed_hash, item_url_hash } });
  }

  /** Set State */
  async itemSetState({ feed_hash, item_url_hash, score, is_read }) {
    return this._request("POST", "/item/set_state", { query: { feed_hash, item_url_hash, score, is_read } });
  }

  /** Create a source (within a feed) */
  async sourceCreate({ feed_name_hash, source_name, source_url }) {
    return this._request("POST", "/source/create", { query: { feed_name_hash, source_name, source_url } });
  }

  /** Delete a source */
  async sourceDelete({ feed_name_hash, source_name_hash }) {
    return this._request("DELETE", "/source/delete", { query: { feed_name_hash, source_name_hash } });
  }

  /** Get all items in a source */
  async sourceItems({ feed_name_hash, source_name_hash, skip, limit }) {
    return this._request("GET", "/source/items", { query: { feed_name_hash, source_name_hash, skip, limit } });
  }

  /** Create a source from a template */
  async sourceTemplateCreate({ body }) {
    return this._request("POST", "/source_template/create", { body });
  }

  /** Get a source template */
  async sourceTemplateGet({ name_hash }) {
    return this._request("GET", "/source_template/get", { query: { name_hash } });
  }

  /** List all source templates */
  async sourceTemplateListAll() {
    return this._request("GET", "/source_template/list_all");
  }

  /** Search for a template */
  async sourceTemplateSearch({ query, skip, limit }) {
    return this._request("GET", "/source_template/search", { query: { query, skip, limit } });
  }

  /** Get Version */
  async version() {
    return this._request("GET", "/version");
  }
}

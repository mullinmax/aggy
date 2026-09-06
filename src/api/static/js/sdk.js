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

  /** Create the source behind a recommended option */
  async extensionCreateSource({ body }) {
    return this._request("POST", "/extension/create_source", { body });
  }

  /** Extract a single page's article content without saving it */
  async extensionPreviewItem({ body }) {
    return this._request("POST", "/extension/preview_item", { body });
  }

  /** Preview the items a recommended option would produce */
  async extensionPreviewSource({ body }) {
    return this._request("POST", "/extension/preview_source", { body });
  }

  /** Rank the ways a page could become a source */
  async extensionRecommend({ body }) {
    return this._request("POST", "/extension/recommend", { body });
  }

  /** Save a single page into a feed as an article */
  async extensionSaveItem({ body }) {
    return this._request("POST", "/extension/save_item", { body });
  }

  /** What aggy already knows about this page and its site */
  async extensionStatus({ url }) {
    return this._request("GET", "/extension/status", { query: { url } });
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

  /** Explain why an item got its predicted score */
  async feedItemExplanation({ feed_name_hash, item_url_hash }) {
    return this._request("GET", "/feed/item_explanation", { query: { feed_name_hash, item_url_hash } });
  }

  /** List all items in a feed */
  async feedItems({ feed_name_hash, skip, limit, sort, include_read, sources, post_types, max_age }) {
    return this._request("GET", "/feed/items", { query: { feed_name_hash, skip, limit, sort, include_read, sources, post_types, max_age } });
  }

  /** List feeds a user has created */
  async feedList() {
    return this._request("GET", "/feed/list");
  }

  /** Vote-prediction model performance for a feed */
  async feedRankingStats({ feed_name_hash }) {
    return this._request("GET", "/feed/ranking_stats", { query: { feed_name_hash } });
  }

  /** Rename a feed */
  async feedRename({ feed_name_hash, new_name }) {
    return this._request("POST", "/feed/rename", { query: { feed_name_hash, new_name } });
  }

  /** Start re-evaluating prediction models and re-ranking a feed */
  async feedRerank({ feed_name_hash }) {
    return this._request("POST", "/feed/rerank", { query: { feed_name_hash } });
  }

  /** List all sources in a feed */
  async feedSources({ feed_name_hash }) {
    return this._request("GET", "/feed/sources", { query: { feed_name_hash } });
  }

  /** Progress of a feed's model training, and how stale its models are */
  async feedTrainingStatus({ feed_name_hash }) {
    return this._request("GET", "/feed/training_status", { query: { feed_name_hash } });
  }

  /** Health */
  async health() {
    return this._request("GET", "/health");
  }

  /** Create many sources at once, each in its chosen feed */
  async importCreate({ body }) {
    return this._request("POST", "/import/create", { body });
  }

  /** Parse subscription data (export file, pasted list, or username) into source candidates */
  async importParse({ body }) {
    return this._request("POST", "/import/parse", { body });
  }

  /** Get State */
  async itemGetState({ feed_hash, item_url_hash }) {
    return this._request("GET", "/item/get_state", { query: { feed_hash, item_url_hash } });
  }

  /** Set State */
  async itemSetState({ feed_hash, item_url_hash, score, is_read }) {
    return this._request("POST", "/item/set_state", { query: { feed_hash, item_url_hash, score, is_read } });
  }

  /** Resolve a currently-playable media URL for a video item */
  async itemStreamUrl({ item_url_hash }) {
    return this._request("GET", "/item/stream_url", { query: { item_url_hash } });
  }

  /** A picture for a video item that loads right now */
  async itemThumbnail({ item_url_hash }) {
    return this._request("GET", "/item/thumbnail", { query: { item_url_hash } });
  }

  /** Create a list */
  async listCreate({ list_name }) {
    return this._request("POST", "/list/create", { query: { list_name } });
  }

  /** Delete a list */
  async listDelete({ list_name_hash }) {
    return this._request("DELETE", "/list/delete", { query: { list_name_hash } });
  }

  /** Get a list */
  async listGet({ list_name_hash }) {
    return this._request("GET", "/list/get", { query: { list_name_hash } });
  }

  /** List the items in a list */
  async listItems({ list_name_hash }) {
    return this._request("GET", "/list/items", { query: { list_name_hash } });
  }

  /** List a user's lists */
  async listList({ item_url_hash }) {
    return this._request("GET", "/list/list", { query: { item_url_hash } });
  }

  /** Set which of the user's lists an item belongs to */
  async listSetItemLists({ item_url_hash, list_hashes }) {
    return this._request("POST", "/list/set_item_lists", { query: { item_url_hash, list_hashes } });
  }

  /** Create a source (within a feed) */
  async sourceCreate({ feed_name_hash, source_name, source_url }) {
    return this._request("POST", "/source/create", { query: { feed_name_hash, source_name, source_url } });
  }

  /** Add another feed as a source (shares its items and votes) */
  async sourceCreateFeed({ feed_name_hash, source_feed_name_hash }) {
    return this._request("POST", "/source/create_feed", { query: { feed_name_hash, source_feed_name_hash } });
  }

  /** Create a source that scrapes a web page with CSS selectors */
  async sourceCreateScraped({ body }) {
    return this._request("POST", "/source/create_scraped", { body });
  }

  /** Delete a source */
  async sourceDelete({ feed_name_hash, source_name_hash }) {
    return this._request("DELETE", "/source/delete", { query: { feed_name_hash, source_name_hash } });
  }

  /** Get all items in a source */
  async sourceItems({ feed_name_hash, source_name_hash, skip, limit }) {
    return this._request("GET", "/source/items", { query: { feed_name_hash, source_name_hash, skip, limit } });
  }

  /** Re-scrape a source's items for content, media, and embeddings */
  async sourceRescrape({ feed_name_hash, source_name_hash }) {
    return this._request("POST", "/source/rescrape", { query: { feed_name_hash, source_name_hash } });
  }

  /** Update a source's name, URL, or template parameters */
  async sourceUpdate({ body }) {
    return this._request("POST", "/source/update", { body });
  }

  /** Detect whether a URL is an RSS/Atom feed or an HTML page to scrape */
  async sourceAnalyzeDetect({ body }) {
    return this._request("POST", "/source_analyze/detect", { body });
  }

  /** Preview the feed produced by a set of CSS selectors */
  async sourceAnalyzePreview({ body }) {
    return this._request("POST", "/source_analyze/preview", { body });
  }

  /** Start analyzing a website to suggest CSS selectors for a feed */
  async sourceAnalyzeSuggest({ body }) {
    return this._request("POST", "/source_analyze/suggest", { body });
  }

  /** Poll a website-analysis job for its result */
  async sourceAnalyzeSuggestResult({ job_id }) {
    return this._request("GET", "/source_analyze/suggest_result", { query: { job_id } });
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

  /** Summary stats for every article the user has collected */
  async statsArticles({ timeline_days }) {
    return this._request("GET", "/stats/articles", { query: { timeline_days } });
  }

  /** How reliably each site has been answering this user's sources */
  async statsSources({ days }) {
    return this._request("GET", "/stats/sources", { query: { days } });
  }

  /** Get Version */
  async version() {
    return this._request("GET", "/version");
  }
}

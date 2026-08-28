// The popup: sign in, then either file this page as an article or start
// following the site it came from.

import * as api from "./lib/api.js";
import { preferredUrl, readPage } from "./lib/page.js";
import { getSettings, normalizeInstanceUrl, setSettings } from "./lib/storage.js";

const $ = (id) => document.getElementById(id);

const state = {
  settings: null,
  page: null,
  url: "",
  feeds: [],
  options: [],
  selectedOption: null,
  // selectors approved in a scrape preview, ready for create_source
  analysis: null,
};

function setStatus(message, kind) {
  const el = $("status");
  el.textContent = message || "";
  el.className = `status ${kind || ""}`;
  el.hidden = !message;
}

function showError(error) {
  console.error(error);
  setStatus(error?.message || String(error), "bad");
  if (error instanceof api.AuthError) showSignIn();
}

function showSignIn() {
  $("signin").hidden = false;
  $("main").hidden = true;
  $("instance-url").value = state.settings?.instanceUrl || "";
}

/** The Cookie header to send with this request, or "" when not opted in. */
async function cookieHeader() {
  if (!$("share-cookies").checked) return "";
  return api.cookieHeaderFor(state.url);
}

// ---------------------------------------------------------------------------
// Sign in
// ---------------------------------------------------------------------------

async function signIn() {
  const instanceUrl = normalizeInstanceUrl($("instance-url").value);
  const username = $("username").value.trim();
  const password = $("password").value;
  const error = $("signin-error");
  error.hidden = true;

  if (!instanceUrl || !username || !password) {
    error.textContent = "Instance URL, username, and password are all needed.";
    error.hidden = false;
    return;
  }

  $("signin-button").disabled = true;
  try {
    const token = await api.login(instanceUrl, username, password);
    state.settings = await setSettings({ instanceUrl, token, username });
    $("password").value = "";
    $("signin").hidden = true;
    await start();
  } catch (e) {
    error.textContent =
      e.status === 401 ? "That username and password didn't work." : e.message;
    error.hidden = false;
  } finally {
    $("signin-button").disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Feeds
// ---------------------------------------------------------------------------

async function loadFeeds() {
  state.feeds = await api.listFeeds();
  const select = $("feed-select");
  select.innerHTML = "";

  if (!state.feeds.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No feeds yet — create one in aggy";
    select.appendChild(option);
    select.disabled = true;
    return;
  }

  select.disabled = false;
  for (const feed of state.feeds) {
    const option = document.createElement("option");
    option.value = feed.feed_name_hash ?? feed.name_hash;
    option.textContent = feed.feed_name ?? feed.name;
    select.appendChild(option);
  }

  const remembered = state.settings.defaultFeedHash;
  if (remembered && [...select.options].some((o) => o.value === remembered)) {
    select.value = remembered;
  }
  rememberFeed();
}

function currentFeed() {
  const select = $("feed-select");
  return {
    hash: select.value,
    name: select.selectedOptions[0]?.textContent || "",
  };
}

async function rememberFeed() {
  const feed = currentFeed();
  if (!feed.hash) return;
  state.settings = await setSettings({
    defaultFeedHash: feed.hash,
    defaultFeedName: feed.name,
  });
}

// ---------------------------------------------------------------------------
// "aggy already knows this"
// ---------------------------------------------------------------------------

function voteWord(score) {
  if (score > 0) return "upvoted";
  if (score < 0) return "downvoted";
  return "saved";
}

async function loadKnown() {
  const box = $("known");
  try {
    const status = await api.pageStatus(state.url);
    const lines = [];

    for (const feed of status.item_feeds) {
      lines.push(
        `📄 Already in <b>${escapeHtml(feed.feed_name)}</b>${
          feed.score === null || feed.score === undefined
            ? ""
            : ` — you ${voteWord(feed.score)} it`
        }`,
      );
    }
    for (const source of status.site_sources.slice(0, 3)) {
      lines.push(
        `📡 Following <b>${escapeHtml(source.source_name)}</b> from this site in ` +
          `<b>${escapeHtml(source.feed_name)}</b>`,
      );
    }

    box.innerHTML = lines.join("<br />");
    box.hidden = !lines.length;

    if (status.item_saved) {
      $("save-plain").textContent = "Save again";
    }
  } catch (e) {
    // Knowing this is a nicety; a failure here must not block saving.
    box.hidden = true;
    if (e instanceof api.AuthError) throw e;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Save this page
// ---------------------------------------------------------------------------

function renderItemPreview(item) {
  const box = $("item-preview");
  box.innerHTML = "";

  if (item.image) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = item.image;
    img.alt = "";
    box.appendChild(img);
  }

  const title = document.createElement("h3");
  title.textContent = item.title || state.url;
  box.appendChild(title);

  const excerpt = document.createElement("p");
  excerpt.textContent = item.excerpt || "No article text found on this page.";
  box.appendChild(excerpt);
}

async function loadItemPreview() {
  try {
    const preview = await api.previewItem({
      url: state.url,
      title: state.page.title || null,
      excerpt: state.page.excerpt || null,
      image_url: state.page.image || null,
      cookie: (await cookieHeader()) || null,
    });
    renderItemPreview(preview);
  } catch (e) {
    // The server couldn't read the page, but the browser did: show what we
    // have rather than an error, since saving still works.
    renderItemPreview({
      title: state.page.title,
      excerpt: state.page.excerpt,
      image: state.page.image,
    });
    if (e instanceof api.AuthError) throw e;
  }
}

async function save(score) {
  const feed = currentFeed();
  if (!feed.hash) {
    setStatus("Create a feed in aggy first.", "bad");
    return;
  }

  const buttons = [$("save-plain"), $("save-up"), $("save-down")];
  buttons.forEach((b) => (b.disabled = true));
  setStatus("Saving…");

  try {
    const result = await api.saveItem({
      url: state.url,
      feed_hash: feed.hash,
      title: state.page.title || null,
      excerpt: state.page.excerpt || null,
      image_url: state.page.image || null,
      score,
      cookie: (await cookieHeader()) || null,
    });
    const vote = score > 0 ? " 👍" : score < 0 ? " 👎" : "";
    setStatus(
      `${result.created ? "Saved" : "Already saved — re-filed"} to ${feed.name} ` +
        `under “${result.source_name}”${vote}`,
      "ok",
    );
    renderItemPreview(result.item);
    await loadKnown();
  } catch (e) {
    showError(e);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

// ---------------------------------------------------------------------------
// Follow this site
// ---------------------------------------------------------------------------

async function loadOptions() {
  const list = $("options-list");
  list.textContent = "Working out how to follow this page…";

  try {
    const result = await api.recommend({
      url: state.url,
      page_feeds: state.page.feeds,
      page_title: state.page.title || null,
      cookie: (await cookieHeader()) || null,
    });
    state.options = result.options;
    renderOptions(result.model_error);
  } catch (e) {
    list.textContent = "";
    showError(e);
  }
}

function renderOptions(modelError) {
  const list = $("options-list");
  list.innerHTML = "";

  for (const [index, option] of state.options.entries()) {
    const button = document.createElement("button");
    button.className = "option";
    button.type = "button";
    button.innerHTML =
      `<span class="badge ${escapeHtml(option.confidence)}">${escapeHtml(
        option.confidence,
      )}</span>` +
      `<span class="label">${escapeHtml(option.label)}</span>` +
      `<span class="reason">${escapeHtml(option.reason)}</span>`;
    button.addEventListener("click", () => chooseOption(index));
    list.appendChild(button);
  }

  if (modelError) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = modelError;
    list.appendChild(note);
  }
}

function showOptionList() {
  $("options-list").hidden = false;
  $("option-detail").hidden = true;
  state.selectedOption = null;
  state.analysis = null;
}

async function chooseOption(index) {
  const option = state.options[index];
  state.selectedOption = option;
  state.analysis = null;

  $("options-list").hidden = true;
  $("option-detail").hidden = false;
  $("source-name").value = option.suggested_source_name || "";
  $("create-source").disabled = true;
  setStatus("");

  const preview = $("source-preview");
  preview.innerHTML = `<p class="muted">${
    option.requires_analysis
      ? "Reading the page and working out its articles — this can take a minute…"
      : "Fetching a preview…"
  }</p>`;

  try {
    const cookie = (await cookieHeader()) || null;
    let result;

    if (option.requires_analysis) {
      const job = await api.startAnalysis({ url: state.url, cookie });
      const analysis = await api.waitForAnalysis(job.job_id);
      state.analysis = analysis;
      if (analysis.suggested_source_name && !$("source-name").value) {
        $("source-name").value = analysis.suggested_source_name;
      }
      result = await api.previewSelectors({
        parameters: analysis.defaults,
        rendered: analysis.rendered,
      });
    } else {
      result = await api.previewSource({ option, cookie });
    }

    renderSourcePreview(result);
    $("create-source").disabled = false;
  } catch (e) {
    preview.innerHTML = "";
    const note = document.createElement("p");
    note.className = "error";
    note.textContent = `No preview: ${e.message}`;
    preview.appendChild(note);
    // A preview that failed is a warning, not a veto — a feed can be empty
    // right now and fine tomorrow — except for a scrape, whose selectors are
    // exactly what the analysis was supposed to produce.
    $("create-source").disabled = Boolean(option.requires_analysis && !state.analysis);
    if (e instanceof api.AuthError) showError(e);
  }
}

function renderSourcePreview(preview) {
  const box = $("source-preview");
  box.innerHTML = "";

  const heading = document.createElement("h3");
  heading.textContent = preview.feed_title || "Preview";
  box.appendChild(heading);

  if (!preview.items?.length) {
    const empty = document.createElement("p");
    empty.textContent = "No items in this source right now.";
    box.appendChild(empty);
    return;
  }

  const list = document.createElement("ol");
  for (const item of preview.items.slice(0, 8)) {
    const li = document.createElement("li");
    li.textContent = item.title || item.url || "(untitled)";
    list.appendChild(li);
  }
  box.appendChild(list);
}

async function createSource() {
  const feed = currentFeed();
  const option = state.selectedOption;
  if (!feed.hash || !option) return;

  const name = $("source-name").value.trim();
  if (!name) {
    setStatus("Give the source a name.", "bad");
    return;
  }

  $("create-source").disabled = true;
  setStatus("Adding source…");

  try {
    await api.createSource({
      feed_hash: feed.hash,
      source_name: name,
      option,
      cookie: (await cookieHeader()) || null,
      parameters: state.analysis ? state.analysis.defaults : null,
      rendered: state.analysis ? state.analysis.rendered : false,
    });
    setStatus(`Added “${name}” to ${feed.name}. Fetching its first items now.`, "ok");
    await loadKnown();
  } catch (e) {
    showError(e);
  } finally {
    $("create-source").disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function selectTab(which) {
  const saving = which === "save";
  $("tab-save").classList.toggle("active", saving);
  $("tab-follow").classList.toggle("active", !saving);
  $("panel-save").hidden = !saving;
  $("panel-follow").hidden = saving;
  setStatus("");

  if (!saving && !state.options.length) loadOptions();
}

async function start() {
  $("main").hidden = false;
  $("account").textContent = state.settings.username || "";

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  state.page = await readPage(tab);
  state.url = preferredUrl(state.page);

  $("page-title").textContent = state.page.title || state.url;
  $("page-url").textContent = state.url;
  $("share-cookies").checked = state.settings.shareCookies;

  if (!/^https?:\/\//i.test(state.url)) {
    setStatus("This page can't be saved — open a normal web page.", "bad");
    $("save-plain").disabled = true;
    $("save-up").disabled = true;
    $("save-down").disabled = true;
    return;
  }

  try {
    await loadFeeds();
  } catch (e) {
    showError(e);
    return;
  }

  loadKnown().catch(showError);
  loadItemPreview().catch(showError);
}

document.addEventListener("DOMContentLoaded", async () => {
  state.settings = await getSettings();

  $("open-options").addEventListener("click", () => chrome.runtime.openOptionsPage());
  $("signin-button").addEventListener("click", signIn);
  $("password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") signIn();
  });
  $("feed-select").addEventListener("change", rememberFeed);
  $("tab-save").addEventListener("click", () => selectTab("save"));
  $("tab-follow").addEventListener("click", () => selectTab("follow"));
  $("save-plain").addEventListener("click", () => save(null));
  $("save-up").addEventListener("click", () => save(1));
  $("save-down").addEventListener("click", () => save(-1));
  $("back-to-options").addEventListener("click", showOptionList);
  $("create-source").addEventListener("click", createSource);
  $("share-cookies").addEventListener("change", async (e) => {
    state.settings = await setSettings({ shareCookies: e.target.checked });
    // The recommendation depends on what the server can fetch, so it is worth
    // redoing once the user changes their mind about cookies.
    state.options = [];
    if (!$("panel-follow").hidden) loadOptions();
  });

  if (state.settings.instanceUrl && state.settings.token) {
    await start();
  } else {
    showSignIn();
  }
});

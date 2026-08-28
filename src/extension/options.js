import * as api from "./lib/api.js";
import {
  clearToken,
  getSettings,
  normalizeInstanceUrl,
  setSettings,
} from "./lib/storage.js";

const $ = (id) => document.getElementById(id);

function setStatus(message, kind) {
  const el = $("status");
  el.textContent = message || "";
  el.className = `status ${kind || ""}`;
  el.hidden = !message;
}

async function loadFeeds(settings) {
  const select = $("feed-select");
  select.innerHTML = "";

  if (!settings.instanceUrl || !settings.token) {
    select.disabled = true;
    return;
  }

  try {
    const feeds = await api.listFeeds();
    select.disabled = false;
    for (const feed of feeds) {
      const option = document.createElement("option");
      option.value = feed.feed_name_hash;
      option.textContent = feed.feed_name;
      select.appendChild(option);
    }
    if (settings.defaultFeedHash) select.value = settings.defaultFeedHash;
  } catch (e) {
    select.disabled = true;
    setStatus(e.message, "bad");
  }
}

async function signIn() {
  const instanceUrl = normalizeInstanceUrl($("instance-url").value);
  const username = $("username").value.trim();
  const password = $("password").value;

  if (!instanceUrl || !username || !password) {
    setStatus("Instance URL, username, and password are all needed.", "bad");
    return;
  }

  $("save").disabled = true;
  try {
    const token = await api.login(instanceUrl, username, password);
    const settings = await setSettings({ instanceUrl, token, username });
    $("password").value = "";
    setStatus(`Signed in to ${instanceUrl} as ${username}.`, "ok");
    await loadFeeds(settings);
  } catch (e) {
    setStatus(e.status === 401 ? "That username and password didn't work." : e.message, "bad");
  } finally {
    $("save").disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const settings = await getSettings();
  $("instance-url").value = settings.instanceUrl;
  $("username").value = settings.username;
  $("share-cookies").checked = settings.shareCookies;
  await loadFeeds(settings);

  $("save").addEventListener("click", signIn);
  $("signout").addEventListener("click", async () => {
    await clearToken();
    setStatus("Signed out. Your instance URL is still here.", "ok");
    $("feed-select").innerHTML = "";
    $("feed-select").disabled = true;
  });
  $("feed-select").addEventListener("change", async (e) => {
    await setSettings({
      defaultFeedHash: e.target.value,
      defaultFeedName: e.target.selectedOptions[0]?.textContent || "",
    });
    setStatus("Default feed saved.", "ok");
  });
  $("share-cookies").addEventListener("change", async (e) => {
    await setSettings({ shareCookies: e.target.checked });
    setStatus(
      e.target.checked
        ? "Cookies will be shared with your instance when you save or follow a page."
        : "Cookie sharing is off.",
      "ok",
    );
  });
});

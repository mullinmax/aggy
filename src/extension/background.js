// Saving without opening the popup: the right-click menu and the keyboard
// shortcuts. Both file into the feed the popup last used, and report back on
// the toolbar badge, since a service worker has no UI of its own.

import * as api from "./lib/api.js";
import { preferredUrl, readPage } from "./lib/page.js";
import { getSettings } from "./lib/storage.js";

const MENUS = [
  { id: "save-page", title: "Save this page to Aggy", contexts: ["page"] },
  { id: "save-link", title: "Save this link to Aggy", contexts: ["link"] },
  {
    id: "save-page-upvote",
    title: "Save this page to Aggy 👍",
    contexts: ["page", "selection"],
  },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const menu of MENUS) chrome.contextMenus.create(menu);
  });
});

/** Flash a short result on the toolbar icon and clear it again. */
async function flashBadge(text, color, title) {
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text });
  if (title) await chrome.action.setTitle({ title });
  setTimeout(() => {
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Add to Aggy" });
  }, 4000);
}

async function saveFromBackground({ url, tab, score }) {
  const settings = await getSettings();

  if (!settings.instanceUrl || !settings.token) {
    await flashBadge("!", "#c0392b", "Open Aggy and sign in first");
    return;
  }
  if (!settings.defaultFeedHash) {
    await flashBadge("?", "#c0392b", "Open Aggy once to pick a feed");
    return;
  }

  // A link target has no DOM of its own; the page's own metadata would be the
  // wrong article for it, so only a page save reads the tab.
  const page = url ? null : await readPage(tab);
  const targetUrl = url || preferredUrl(page);

  if (!/^https?:\/\//i.test(targetUrl || "")) {
    await flashBadge("!", "#c0392b", "That isn't a page Aggy can save");
    return;
  }

  await flashBadge("…", "#3e9e55", "Saving to Aggy…");

  try {
    let cookie = null;
    if (settings.shareCookies) cookie = (await api.cookieHeaderFor(targetUrl)) || null;

    await api.saveItem({
      url: targetUrl,
      feed_hash: settings.defaultFeedHash,
      title: page?.title || null,
      excerpt: page?.selection || page?.excerpt || null,
      image_url: page?.image || null,
      score: score ?? null,
      cookie,
    });
    await flashBadge("✓", "#3e9e55", `Saved to ${settings.defaultFeedName}`);
  } catch (e) {
    console.error(e);
    await flashBadge("!", "#c0392b", `Aggy: ${e.message}`);
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  saveFromBackground({
    url: info.menuItemId === "save-link" ? info.linkUrl : null,
    tab,
    score: info.menuItemId === "save-page-upvote" ? 1 : null,
  });
});

chrome.commands.onCommand.addListener(async (command) => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  saveFromBackground({
    url: null,
    tab,
    score: command === "save-page-upvote" ? 1 : null,
  });
});

// Everything the extension remembers, in one place.
//
// chrome.storage.local (not sync): the token is a bearer credential for the
// user's own aggy instance, and syncing it across every browser signed into
// the same Google account is not what anyone asked for by installing this.

export const DEFAULTS = {
  // Base URL of the user's aggy instance, without a trailing slash.
  instanceUrl: "",
  token: "",
  username: "",
  // Feed the popup opens on, and the one the shortcuts and context menu save
  // into without asking.
  defaultFeedHash: "",
  defaultFeedName: "",
  // Send the current site's cookies with server-side fetches, so aggy sees the
  // page the way the signed-in user does. Off unless the user turns it on.
  shareCookies: false,
};

/**
 * The instance this copy of the extension was downloaded from.
 *
 * A build served by an aggy instance carries a config.json naming it, so the
 * user never has to type their own URL. A copy loaded straight from the
 * repository has none, and the field simply starts empty.
 */
async function bundledInstanceUrl() {
  try {
    const response = await fetch(chrome.runtime.getURL("config.json"));
    if (!response.ok) return "";
    const config = await response.json();
    return normalizeInstanceUrl(config.instanceUrl);
  } catch (e) {
    return "";
  }
}

export async function getSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const settings = { ...DEFAULTS, ...stored };
  if (!settings.instanceUrl) settings.instanceUrl = await bundledInstanceUrl();
  return settings;
}

export async function setSettings(patch) {
  await chrome.storage.local.set(patch);
  return getSettings();
}

export async function clearToken() {
  await chrome.storage.local.set({ token: "", username: "" });
}

/** Normalize what a user typed into an instance URL we can build paths on. */
export function normalizeInstanceUrl(raw) {
  let url = (raw || "").trim();
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
  return url.replace(/\/+$/, "");
}

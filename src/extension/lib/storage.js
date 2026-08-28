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

export async function getSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...stored };
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

// Thin client over the aggy API, shared by the popup, the options page, and
// the background worker.

import { clearToken, getSettings } from "./storage.js";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Thrown when the instance says the token is missing, expired, or wrong. */
export class AuthError extends ApiError {
  constructor(message = "Your aggy session has expired. Sign in again.") {
    super(message, 401);
    this.name = "AuthError";
  }
}

function buildUrl(instanceUrl, path, params) {
  const url = new URL(instanceUrl + path);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

async function errorFrom(response) {
  // FastAPI puts the human-readable half in `detail`, which is either a
  // string or a list of validation errors.
  let detail = "";
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      detail = body.detail.map((e) => e.msg).join("; ");
    }
  } catch (e) {
    detail = "";
  }
  return new ApiError(
    detail || `${response.status} ${response.statusText}`,
    response.status,
  );
}

export async function request(path, options = {}) {
  const { method = "GET", body, params, auth = true, instanceUrl } = options;
  const settings = await getSettings();
  const base = instanceUrl || settings.instanceUrl;

  if (!base) {
    throw new ApiError("Set your aggy instance URL first.", 0);
  }
  if (auth && !settings.token) {
    throw new AuthError("Sign in to your aggy instance first.");
  }

  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) headers.Authorization = `Bearer ${settings.token}`;

  let response;
  try {
    response = await fetch(buildUrl(base, path, params), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(
      `Couldn't reach ${base}. Check the instance URL and that it's running.`,
      0,
    );
  }

  if (response.status === 401 || response.status === 403) {
    // A stale token only ever gets more stale; drop it so the popup asks for
    // a password instead of failing every call from here on.
    if (auth) await clearToken();
    throw new AuthError();
  }
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return null;

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export async function login(instanceUrl, username, password) {
  const data = await request("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false,
    instanceUrl,
  });
  return data.access_token;
}

export const listFeeds = () => request("/feed/list");

export const createFeed = (feedName) =>
  request("/feed/create", { method: "POST", params: { feed_name: feedName } });

export const pageStatus = (url) => request("/extension/status", { params: { url } });

export const recommend = (payload) =>
  request("/extension/recommend", { method: "POST", body: payload });

export const previewSource = (payload) =>
  request("/extension/preview_source", { method: "POST", body: payload });

export const createSource = (payload) =>
  request("/extension/create_source", { method: "POST", body: payload });

export const previewItem = (payload) =>
  request("/extension/preview_item", { method: "POST", body: payload });

export const saveItem = (payload) =>
  request("/extension/save_item", { method: "POST", body: payload });

export const startAnalysis = (payload) =>
  request("/source_analyze/suggest", { method: "POST", body: payload });

export const analysisResult = (jobId) =>
  request("/source_analyze/suggest_result", { params: { job_id: jobId } });

export const previewSelectors = (payload) =>
  request("/source_analyze/preview", { method: "POST", body: payload });

/**
 * Poll a selector-analysis job until it finishes.
 *
 * The analysis is an LLM pass over the page and takes anywhere from seconds
 * to a couple of minutes on CPU, so the API runs it as a job and hands back
 * an id; this waits on it and returns the result.
 */
export async function waitForAnalysis(jobId, { intervalMs = 2000, timeoutMs = 240000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await analysisResult(jobId);
    if (status.status === "done") return status.result;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new ApiError("The page analysis is taking too long. Try again later.", 504);
}

/**
 * The site's cookies as a Cookie header, for fetches aggy makes server-side.
 *
 * Only called when the user has opted in: it hands their session for that one
 * site to their own instance, which is what makes a members-only page
 * readable, and is nobody's default.
 */
export async function cookieHeaderFor(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    return "";
  }
}

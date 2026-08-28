// What the browser can tell aggy about a page that a server-side fetch can't.

/**
 * Read the current page's identity out of the live DOM.
 *
 * Injected into the tab with chrome.scripting, so it has to be entirely
 * self-contained — no imports, no closure over anything here.
 */
export function collectPageInfo() {
  const meta = (selector, attribute = "content") => {
    const el = document.querySelector(selector);
    return el ? (el.getAttribute(attribute) || "").trim() : "";
  };

  const feeds = [];
  for (const link of document.querySelectorAll('link[rel~="alternate"][href]')) {
    const type = (link.getAttribute("type") || "").toLowerCase();
    if (type.includes("rss") || type.includes("atom")) {
      try {
        feeds.push(new URL(link.getAttribute("href"), document.baseURI).href);
      } catch (e) {
        /* a malformed href is simply not a feed we can offer */
      }
    }
  }

  const selection = (window.getSelection?.().toString() || "").trim();

  return {
    url: location.href,
    // og:url is the canonical form of pages that carry tracking parameters,
    // so saving from two different links doesn't produce two articles.
    canonicalUrl:
      meta('link[rel="canonical"]', "href") || meta('meta[property="og:url"]') || "",
    title: meta('meta[property="og:title"]') || document.title || "",
    excerpt:
      meta('meta[property="og:description"]') ||
      meta('meta[name="description"]') ||
      selection ||
      "",
    image: meta('meta[property="og:image"]') || meta('meta[name="twitter:image"]') || "",
    selection,
    feeds: [...new Set(feeds)],
  };
}

/** Run collectPageInfo() in a tab, falling back to what the tab itself says. */
export async function readPage(tab) {
  const fallback = {
    url: tab?.url || "",
    canonicalUrl: "",
    title: tab?.title || "",
    excerpt: "",
    image: "",
    selection: "",
    feeds: [],
  };

  if (!tab?.id || !/^https?:/i.test(tab.url || "")) return fallback;

  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectPageInfo,
    });
    return { ...fallback, ...(result?.result || {}) };
  } catch (e) {
    // chrome:// pages, the web store, and PDF viewers refuse injection; the
    // tab's own URL and title are still enough to save a link.
    return fallback;
  }
}

/** The URL to file: the page's canonical one when it has a sane one. */
export function preferredUrl(page) {
  const canonical = (page.canonicalUrl || "").trim();
  if (/^https?:\/\//i.test(canonical)) return canonical;
  return page.url;
}

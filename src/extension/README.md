# Aggy browser extension

A toolbar button for the page you're on: file it into one of your feeds as an
article (with an optional up- or downvote), or start following the site it
came from — as its subreddit, its channel, the feed it advertises, or, failing
all of those, a feed built out of the page itself.

Chrome, Edge, Brave, and anything else on Chromium (Manifest V3).

## Install (unpacked)

1. Open `chrome://extensions` and turn on **Developer mode**.
2. **Load unpacked** → pick this `src/extension` directory.
3. Click the Aggy icon, enter your instance URL (e.g. `https://aggy.example.com`)
   and your aggy username and password, and sign in.

The instance needs to allow the extension's origin. The API allows
`chrome-extension://` and `moz-extension://` origins out of the box; put a
reverse proxy in front of it that strips CORS headers and nothing will work,
so pass them through. `EXTRA_CORS_ORIGINS` (comma-separated) adds others.

## What it does

**Save this page.** Aggy extracts the page the way it does any article — Open
Graph tags, the reader-mode extractor, reddit's post JSON for a reddit link —
and shows you the title, image, and excerpt it got before you commit. Saving
files it under a per-feed **Saved Links** source, which is a normal source in
every way except that nothing polls it. 👍 / 👎 save and vote in one click,
which is a real signal for the ranking model, not just a bookmark.

**Follow this site.** The extension asks the instance how this page is best
read and shows the answers in confidence order:

- Sites aggy knows natively — subreddits, reddit users, YouTube channels,
  Bluesky profiles — are matched by rule and use their own feeds.
- Feeds the page advertises in its `<link rel="alternate">` tags. The
  extension reads these from the live DOM, so a feed that only exists after
  the page's JavaScript has run (or behind a login) is still found.
- Video listings, via the yt-dlp service, when one is configured.
- Otherwise, the local analysis model is asked to match the page to a template
  in the catalog for that domain, and the CSS-selector analyzer is offered as
  the fallback that works on anything.

Whichever you pick, you get a preview of the items it would actually produce
before the source is created.

**It tells you what aggy already knows.** The popup says when this exact URL
is already in a feed (and how you voted on it) and when you already follow
something from this site, so you re-vote instead of saving a second copy.

**Right-click and keyboard.** "Save this page/link to Aggy" on the page, link,
and selection context menus, `Alt+Shift+S` to save, and `Alt+Shift+U` to save
with an upvote. These file into the feed the popup last used, and report on
the toolbar badge. Rebind them at `chrome://extensions/shortcuts`.

**Cookie sharing (off by default).** Some pages only exist for a signed-in
reader. With the checkbox on, the extension reads the current site's cookies
and passes them to *your* instance as the `Cookie` header for its fetches, and
stores them on a scraped source so its later ingests keep working. They go to
the instance URL you configured and nowhere else, and only for the site you
are on. Leave it off unless you need it.

## Layout

```
manifest.json     MV3 manifest: popup, options page, worker, permissions
popup.html/.css/.js   the toolbar UI (both flows)
options.html/.js  instance URL, sign in, default feed, cookie sharing
background.js     context menus, keyboard shortcuts, badge feedback
lib/api.js        the aggy API client (shared by all three)
lib/page.js       what the live DOM knows: feeds, canonical URL, og: tags
lib/storage.js    settings in chrome.storage.local
```

The extension is plain ES modules — no build step, no bundler, no
dependencies. Edit a file and hit reload on `chrome://extensions`.

## Endpoints it uses

Everything the extension needs is under `/extension` on the API
(`src/api/routers/extension.py`), plus `/auth/login`, `/feed/list`, and the
selector analysis pair `/source_analyze/suggest` and `/source_analyze/preview`.

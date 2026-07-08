// Aggy PWA glue: register the service worker and, on mobile, prompt the user
// to install the app to their home screen.
//
// Two install paths exist because the platforms disagree:
//   * Chrome / Android fires `beforeinstallprompt`, which we capture and defer
//     so we can trigger the native prompt from our own "Install" button.
//   * iOS Safari has no such event — installing is a manual "Share → Add to
//     Home Screen" flow, so we show illustrated instructions instead.
//
// The modal only appears on mobile, only when the app isn't already installed,
// and stays dismissed for a while so we never nag.

'use strict';

(function () {
  // ---------- service worker ----------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* SW is a progressive enhancement; ignore registration failures. */
      });
    });
  }

  // ---------- install prompt ----------
  const DISMISS_KEY = 'aggy_pwa_install_dismissed';
  const DISMISS_DAYS = 14;

  const isStandalone = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

  const isMobile = () =>
    /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

  const isIOS = () =>
    /iPhone|iPad|iPod/i.test(navigator.userAgent) ||
    // iPadOS 13+ reports as a Mac but has touch support.
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  function recentlyDismissed() {
    const at = Number(localStorage.getItem(DISMISS_KEY) || 0);
    return at && Date.now() - at < DISMISS_DAYS * 24 * 60 * 60 * 1000;
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    const modal = document.getElementById('pwaInstallModal');
    if (modal && typeof modal.close === 'function') modal.close();
  }

  let deferredPrompt = null;

  function buildModal(mode) {
    // mode: 'native' (Android/Chrome button) or 'ios' (manual instructions)
    if (document.getElementById('pwaInstallModal')) return;

    const modal = document.createElement('dialog');
    modal.className = 'modal modal-bottom sm:modal-middle';
    modal.id = 'pwaInstallModal';

    const box = document.createElement('div');
    box.className = 'modal-box';

    const header = document.createElement('div');
    header.className = 'flex items-center gap-3 mb-3';
    const icon = document.createElement('img');
    icon.src = '/static/icons/icon-192.png';
    icon.alt = 'Aggy';
    icon.className = 'w-12 h-12 rounded-xl';
    const title = document.createElement('div');
    const h3 = document.createElement('h3');
    h3.className = 'text-lg font-bold';
    h3.textContent = 'Install Aggy';
    const sub = document.createElement('p');
    sub.className = 'text-xs text-base-content/60';
    sub.textContent = 'Add Aggy to your home screen for a faster, full-screen experience.';
    title.append(h3, sub);
    header.append(icon, title);
    box.append(header);

    if (mode === 'ios') {
      const steps = document.createElement('ol');
      steps.className = 'text-sm text-base-content/80 list-decimal list-inside space-y-2 my-4';
      const s1 = document.createElement('li');
      s1.append(
        document.createTextNode('Tap the '),
        strong('Share'),
        document.createTextNode(' button in the toolbar '),
        span('(the square with an arrow ⬆︎).')
      );
      const s2 = document.createElement('li');
      s2.append(
        document.createTextNode('Choose '),
        strong('Add to Home Screen'),
        document.createTextNode('.')
      );
      const s3 = document.createElement('li');
      s3.append(
        document.createTextNode('Tap '),
        strong('Add'),
        document.createTextNode(' to finish.')
      );
      steps.append(s1, s2, s3);
      box.append(steps);
    }

    const actions = document.createElement('div');
    actions.className = 'modal-action';

    const notNow = document.createElement('button');
    notNow.type = 'button';
    notNow.className = 'btn btn-ghost';
    notNow.textContent = 'Not now';
    notNow.addEventListener('click', dismiss);
    actions.append(notNow);

    if (mode === 'native') {
      const install = document.createElement('button');
      install.type = 'button';
      install.className = 'btn btn-primary';
      install.textContent = 'Install';
      install.addEventListener('click', async () => {
        if (!deferredPrompt) { dismiss(); return; }
        deferredPrompt.prompt();
        try { await deferredPrompt.userChoice; } catch (_) { /* ignore */ }
        deferredPrompt = null;
        dismiss();
      });
      actions.append(install);
    } else {
      const gotIt = document.createElement('button');
      gotIt.type = 'button';
      gotIt.className = 'btn btn-primary';
      gotIt.textContent = 'Got it';
      gotIt.addEventListener('click', dismiss);
      actions.append(gotIt);
    }

    box.append(actions);
    modal.append(box);

    const backdrop = document.createElement('form');
    backdrop.method = 'dialog';
    backdrop.className = 'modal-backdrop';
    const backdropBtn = document.createElement('button');
    backdropBtn.textContent = 'close';
    backdrop.append(backdropBtn);
    modal.append(backdrop);

    // Record a dismissal whenever the dialog closes (backdrop / Escape too).
    modal.addEventListener('close', () => {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    });

    document.body.append(modal);
    return modal;
  }

  function strong(text) {
    const el = document.createElement('strong');
    el.textContent = text;
    return el;
  }
  function span(text) {
    const el = document.createElement('span');
    el.className = 'text-base-content/50';
    el.textContent = text;
    return el;
  }

  function maybeShow(mode) {
    if (isStandalone() || recentlyDismissed()) return;
    const modal = buildModal(mode);
    if (modal && typeof modal.showModal === 'function') modal.showModal();
  }

  // Android / Chrome: defer the native mini-infobar and offer our own button.
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (isMobile()) maybeShow('native');
  });

  // iOS Safari: no event to hook, so show manual instructions after load.
  window.addEventListener('load', () => {
    if (isIOS() && !isStandalone()) {
      // Give the page a beat to settle before prompting.
      setTimeout(() => maybeShow('ios'), 1200);
    }
  });

  // Stop nagging once installed.
  window.addEventListener('appinstalled', () => {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    deferredPrompt = null;
  });
})();

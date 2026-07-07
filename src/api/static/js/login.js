// Login / signup page.

'use strict';

const sdk = new AggySDK();

if (auth.token()) {
  location.href = '/app';
}

document.addEventListener('DOMContentLoaded', () => {
  $('tabLogin').onclick = () => switchTab('login');
  $('tabSignup').onclick = () => switchTab('signup');
  $('loginForm').onsubmit = handleLogin;
  $('signupForm').onsubmit = handleSignup;
});

function switchTab(tab) {
  $('tabLogin').classList.toggle('tab-active', tab === 'login');
  $('tabSignup').classList.toggle('tab-active', tab === 'signup');
  $('loginForm').classList.toggle('hidden', tab !== 'login');
  $('signupForm').classList.toggle('hidden', tab !== 'signup');
  $('authError').classList.add('hidden');
}

function showError(message) {
  $('authErrorText').textContent = message;
  $('authError').classList.remove('hidden');
}

function setBusy(btn, busy, idleText, busyText) {
  btn.disabled = busy;
  if (busy) {
    render(btn, h('span', { class: 'loading loading-spinner loading-sm' }), ` ${busyText}`);
  } else {
    btn.textContent = idleText;
  }
}

async function handleLogin(e) {
  e.preventDefault();
  $('authError').classList.add('hidden');
  const btn = $('loginBtn');
  setBusy(btn, true, 'Sign In', 'Signing in...');
  try {
    const data = await sdk.authFormLogin({
      formData: {
        username: $('loginUser').value,
        password: $('loginPass').value,
      },
    });
    auth.save(data.access_token);
    location.href = '/app';
  } catch (err) {
    showError(err.message || 'Login failed');
  } finally {
    setBusy(btn, false, 'Sign In');
  }
}

async function handleSignup(e) {
  e.preventDefault();
  $('authError').classList.add('hidden');
  const password = $('signupPass').value;
  if (password !== $('signupPassConfirm').value) {
    showError('Passwords do not match');
    return;
  }
  const btn = $('signupBtn');
  setBusy(btn, true, 'Create Account', 'Creating account...');
  try {
    const username = $('signupUser').value;
    await sdk.authSignup({ body: { username, password } });
    const data = await sdk.authFormLogin({ formData: { username, password } });
    auth.save(data.access_token);
    location.href = '/app';
  } catch (err) {
    showError(err.message || 'Signup failed');
  } finally {
    setBusy(btn, false, 'Create Account');
  }
}

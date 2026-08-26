// FOSDEM Volunteers — app.js (vanilla ES6+, replaces jQuery/main.js)

(function () {
  'use strict';

  // ── Dark Mode ────────────────────────────────────────────────────────────
  const html = document.documentElement;

  function applyTheme(theme) {
    if (theme === 'dark') {
      html.classList.add('dark');
    } else {
      html.classList.remove('dark');
    }
  }

  // Apply saved theme immediately (also done inline in <head> to avoid flash)
  const savedTheme = localStorage.getItem('theme') || 'light';
  applyTheme(savedTheme);

  document.addEventListener('DOMContentLoaded', function () {
    // ── Theme Toggle ──────────────────────────────────────────────────────
    const toggleBtn = document.getElementById('theme-toggle');
    if (toggleBtn) {
      const updateIcon = (theme) => {
        toggleBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
        toggleBtn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
      };
      updateIcon(localStorage.getItem('theme') || 'light');

      toggleBtn.addEventListener('click', function () {
        const current = html.classList.contains('dark') ? 'dark' : 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem('theme', next);
        updateIcon(next);
      });
    }

    // ── Mobile Menu ───────────────────────────────────────────────────────
    const menuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    if (menuBtn && mobileMenu) {
      menuBtn.addEventListener('click', function () {
        const isOpen = !mobileMenu.classList.contains('hidden');
        mobileMenu.classList.toggle('hidden', isOpen);
        menuBtn.setAttribute('aria-expanded', String(!isOpen));
      });
    }

    // ── Dismiss alerts ────────────────────────────────────────────────────
    document.querySelectorAll('[data-dismiss-alert]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        btn.closest('[role="alert"]').remove();
      });
    });

    // ── Collapsible sections ──────────────────────────────────────────────
    document.querySelectorAll('[data-collapse-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const targetId = btn.getAttribute('data-collapse-toggle');
        const target = document.getElementById(targetId);
        if (!target) return;
        const hidden = target.classList.toggle('hidden');
        const icon = btn.querySelector('[data-collapse-icon]');
        if (icon) icon.textContent = hidden ? '▶' : '▼';
      });
    });

    // ── Privacy consent checkbox ──────────────────────────────────────────
    const privacyCheck = document.getElementById('privacy_agree');
    const agreeBtn = document.getElementById('agree_btn');
    if (privacyCheck && agreeBtn) {
      privacyCheck.addEventListener('change', function () {
        agreeBtn.disabled = !this.checked;
      });
    }

    // ── Select all / deselect toggles ────────────────────────────────────
    document.querySelectorAll('[data-select-all]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const groupName = btn.getAttribute('data-select-all');
        const checkboxes = document.querySelectorAll(`input[name="${groupName}"]`);
        const allChecked = Array.from(checkboxes).every((cb) => cb.checked);
        checkboxes.forEach((cb) => { if (!cb.disabled) cb.checked = !allChecked; });
      });
    });

    // ── Admin dropdown menu ──────────────────────────────────────────────
    const adminBtn = document.getElementById('admin-dropdown-btn');
    const adminMenu = document.getElementById('admin-dropdown-menu');
    if (adminBtn && adminMenu) {
      adminBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        adminMenu.classList.toggle('hidden');
      });
      // Close dropdown when clicking outside
      document.addEventListener('click', function (e) {
        if (!adminMenu.classList.contains('hidden') && !adminMenu.contains(e.target)) {
          adminMenu.classList.add('hidden');
        }
      });
    }
  });
})();

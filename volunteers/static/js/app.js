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
    const toggleBtns = [
      document.getElementById('theme-toggle-desktop'),
      document.getElementById('theme-toggle-mobile'),
    ].filter(Boolean);

    const updateIcons = (theme) => {
      const isDark = theme === 'dark';
      const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';
      toggleBtns.forEach((btn) => {
        const icon = btn.querySelector('[aria-hidden]');
        if (icon) icon.textContent = isDark ? '☀️' : '🌙';
        btn.setAttribute('aria-label', label);
      });
    };
    updateIcons(localStorage.getItem('theme') || 'light');

    toggleBtns.forEach((btn) => {
      btn.addEventListener('click', function () {
        const current = html.classList.contains('dark') ? 'dark' : 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem('theme', next);
        updateIcons(next);
      });
    });

    // ── Mobile Menu ───────────────────────────────────────────────────────
    const menuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    if (menuBtn && mobileMenu) {
      menuBtn.addEventListener('click', function () {
        const isOpen = !mobileMenu.classList.contains('hidden');
        mobileMenu.classList.toggle('hidden', isOpen);
        menuBtn.setAttribute('aria-expanded', String(!isOpen));
        const srLabel = menuBtn.querySelector('.sr-only');
        if (srLabel) srLabel.textContent = isOpen ? 'Open menu' : 'Close menu';
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
      // Set initial aria-expanded based on whether the target is currently hidden
      const initialTargetId = btn.getAttribute('data-collapse-toggle');
      const initialTarget = document.getElementById(initialTargetId);
      if (initialTarget) {
        btn.setAttribute('aria-expanded', String(!initialTarget.classList.contains('hidden')));
        btn.setAttribute('aria-controls', initialTargetId);
      }
      btn.addEventListener('click', function () {
        const targetId = btn.getAttribute('data-collapse-toggle');
        const target = document.getElementById(targetId);
        if (!target) return;
        const hidden = target.classList.toggle('hidden');
        btn.setAttribute('aria-expanded', String(!hidden));
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
        const expanding = adminMenu.classList.contains('hidden');
        adminMenu.classList.toggle('hidden');
        adminBtn.setAttribute('aria-expanded', String(expanding));
      });
      // Close dropdown when clicking outside
      document.addEventListener('click', function (e) {
        if (!adminMenu.classList.contains('hidden') && !adminMenu.contains(e.target)) {
          adminMenu.classList.add('hidden');
          adminBtn.setAttribute('aria-expanded', 'false');
        }
      });
      // Close on Escape
      [adminBtn, adminMenu].forEach(function(el) {
        el.addEventListener('keydown', function(e) {
          if (e.key === 'Escape') {
            adminMenu.classList.add('hidden');
            adminBtn.setAttribute('aria-expanded', 'false');
            adminBtn.focus();
          }
        });
      });
    }
  });
})();

// Auto-dismiss flash messages setelah beberapa detik
// PENTING: selector harus SPESIFIK ke wrapper flash message (.flash-messages),
// BUKAN class generik semacam '.mb-4' -- karena '.mb-4' cuma utility Tailwind
// (margin-bottom) yang lumrah dipakai di banyak card/elemen lain (mis. card
// info device di active_device_show_users.html). Sebelumnya, selector yang
// terlalu longgar bikin card-card lain ikut ke-fade-out padahal bukan
// notifikasi sama sekali.
document.addEventListener('DOMContentLoaded', () => {
  const alerts = document.querySelectorAll('.flash-messages > div');
  alerts.forEach((el) => {
    setTimeout(() => {
      el.style.transition = 'opacity .5s ease';
      el.style.opacity = '0';
    }, 4500);
  });
});

// Toggle tema dark/light lewat dropdown avatar. State disimpan di
// localStorage (key 'theme', nilai 'dark'/'light') supaya konsisten dipakai
// ulang di halaman lain -- dashboard ini server-rendered, bukan SPA, jadi
// tiap halaman baru mengecek localStorage sendiri (lihat script anti-flash
// di <head> base.html yang menerapkan class 'dark' SEBELUM body dirender).
document.addEventListener('DOMContentLoaded', () => {
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  const themeToggleIcon = document.getElementById('themeToggleIcon');
  const themeToggleLabel = document.getElementById('themeToggleLabel');

  function syncThemeToggleUI() {
    const isDark = document.documentElement.classList.contains('dark');
    if (themeToggleIcon) themeToggleIcon.textContent = isDark ? '☀️' : '🌙';
    if (themeToggleLabel) themeToggleLabel.textContent = isDark ? 'Light Mode' : 'Dark Mode';
  }
  syncThemeToggleUI();

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
      const isDarkNow = document.documentElement.classList.toggle('dark');
      try {
        localStorage.setItem('theme', isDarkNow ? 'dark' : 'light');
      } catch (e) { /* ignore (private mode / storage disabled) */ }
      syncThemeToggleUI();
    });
  }
});

// Sidebar collapse/expand toggle (state disimpan di localStorage supaya
// tetap konsisten walau pindah halaman, karena dashboard ini server-rendered
// bukan SPA).
document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  const toggleBtn = document.getElementById('sidebarToggleBtn');
  const toggleIcon = document.getElementById('sidebarToggleIcon');

  function syncIcon() {
    const collapsed = root.getAttribute('data-sidebar') === 'collapsed';
    if (toggleIcon) toggleIcon.textContent = collapsed ? '»' : '«';
  }
  syncIcon();

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const isCollapsed = root.getAttribute('data-sidebar') === 'collapsed';
      if (isCollapsed) {
        root.removeAttribute('data-sidebar');
      } else {
        root.setAttribute('data-sidebar', 'collapsed');
      }
      try {
        localStorage.setItem('sidebar_collapsed', isCollapsed ? '0' : '1');
      } catch (e) { /* ignore (private mode / storage disabled) */ }
      syncIcon();
    });
  }

  // Link yang memicu operasi lambat (mis. konek ke device fisik via pyzk)
  // ditandai class "show-loading-on-click" -> munculkan overlay loading
  // SEBELUM navigasi terjadi (browser tetap lanjut load halaman baru
  // seperti biasa, overlay ini cuma kasih kesan visual "sedang diproses"
  // selama jeda loading-nya).
  document.querySelectorAll('a.show-loading-on-click').forEach((link) => {
    link.addEventListener('click', () => {
      const overlay = document.getElementById('globalLoadingOverlay');
      if (overlay) overlay.classList.remove('hidden');
    });
  });

  // Submenu "Iclock Management" (expand/collapse)
  const iclockToggle = document.getElementById('iclockMenuToggle');
  const iclockSubmenu = document.getElementById('iclockSubmenu');
  const iclockChevron = document.getElementById('iclockMenuChevron');
  if (iclockToggle && iclockSubmenu) {
    iclockToggle.addEventListener('click', () => {
      const willShow = iclockSubmenu.classList.contains('hidden');
      iclockSubmenu.classList.toggle('hidden');
      if (iclockChevron) {
        iclockChevron.style.transform = willShow ? 'rotate(180deg)' : '';
      }
    });
  }

  // Submenu "Mobile Attendance" (expand/collapse) -- pola sama dgn Iclock Management
  const mclockToggle = document.getElementById('mclockMenuToggle');
  const mclockSubmenu = document.getElementById('mclockSubmenu');
  const mclockChevron = document.getElementById('mclockMenuChevron');
  if (mclockToggle && mclockSubmenu) {
    mclockToggle.addEventListener('click', () => {
      const willShow = mclockSubmenu.classList.contains('hidden');
      mclockSubmenu.classList.toggle('hidden');
      if (mclockChevron) {
        mclockChevron.style.transform = willShow ? 'rotate(180deg)' : '';
      }
    });
  }

  // Sidebar mobile (drawer/off-canvas): hamburger di header membuka,
  // tombol X / backdrop / Escape / klik link nav menutup. Tidak perlu
  // localStorage -- selalu mulai tertutup tiap halaman baru dimuat (wajar
  // untuk dashboard server-rendered, bukan SPA).
  const sidebarPanel = document.getElementById('sidebarPanel');
  const mobileBackdrop = document.getElementById('mobileSidebarBackdrop');
  const mobileOpenBtn = document.getElementById('mobileSidebarOpenBtn');
  const mobileCloseBtn = document.getElementById('mobileSidebarCloseBtn');

  function openMobileSidebar() {
    if (!sidebarPanel || !mobileBackdrop) return;
    sidebarPanel.classList.remove('-translate-x-full');
    sidebarPanel.classList.add('translate-x-0');
    mobileBackdrop.classList.remove('hidden');
    document.body.style.overflow = 'hidden'; // cegah scroll body di belakang drawer
  }

  function closeMobileSidebar() {
    if (!sidebarPanel || !mobileBackdrop) return;
    sidebarPanel.classList.add('-translate-x-full');
    sidebarPanel.classList.remove('translate-x-0');
    mobileBackdrop.classList.add('hidden');
    document.body.style.overflow = '';
  }

  if (mobileOpenBtn) mobileOpenBtn.addEventListener('click', openMobileSidebar);
  if (mobileCloseBtn) mobileCloseBtn.addEventListener('click', closeMobileSidebar);
  if (mobileBackdrop) mobileBackdrop.addEventListener('click', closeMobileSidebar);

  // Klik salah satu link navigasi di sidebar -> tutup drawer (halaman akan
  // pindah/reload penuh, tapi ini menghindari "kedip" drawer masih terbuka).
  if (sidebarPanel) {
    sidebarPanel.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', closeMobileSidebar);
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMobileSidebar();
  });

  // Kalau window di-resize dari mobile ke desktop (>=1024px) saat drawer
  // terbuka, reset supaya tidak ada state "terbuka" yang nyangkut.
  const desktopMediaQuery = window.matchMedia('(min-width: 1024px)');
  desktopMediaQuery.addEventListener('change', (event) => {
    if (event.matches) closeMobileSidebar();
  });

  // Dropdown aksi per-baris di tabel (Active Device, Employee, Show Device
  // User). Pakai elemen <details>/<summary> ASLI browser untuk buka/tutup --
  // bukan toggle custom lewat JS click handler. Ini jauh lebih reliable di
  // mobile (Safari/Chrome) karena buka/tutupnya ditangani browser sendiri,
  // tidak bergantung urutan event click/scroll/resize yang bisa beda-beda
  // antar browser mobile. JS di sini cuma buat: (1) reposisi jadi fixed
  // supaya tidak kepotong overflow-x-auto di tabel, (2) tutup dropdown row
  // lain saat satu dibuka, (3) tutup semua saat klik di luar / tekan Escape.
  const rowActionDetailsList = document.querySelectorAll('.row-action-details');

  function closeAllRowActionDetails(except) {
    rowActionDetailsList.forEach((d) => {
      if (d !== except) d.removeAttribute('open');
    });
  }

  rowActionDetailsList.forEach((details) => {
    const menu = details.querySelector('.row-action-menu-native');
    const summary = details.querySelector('summary');
    if (!menu || !summary) return;

    details.addEventListener('toggle', () => {
      if (!details.open) return;
      closeAllRowActionDetails(details);

      // Reposisi ke fixed relatif posisi tombol (summary) saat ini -- pada
      // titik 'toggle' event ini, konten sudah ter-render jadi offsetWidth akurat.
      const rect = summary.getBoundingClientRect();
      const menuWidth = menu.offsetWidth || 224;
      let left = rect.right - menuWidth;
      if (left < 8) left = 8;
      const maxLeft = window.innerWidth - menuWidth - 8;
      if (left > maxLeft) left = Math.max(8, maxLeft);
      menu.style.position = 'fixed';
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.left = `${left}px`;
      menu.style.right = 'auto';
      menu.style.marginTop = '0';
    });
  });

  if (rowActionDetailsList.length) {
    document.addEventListener('click', (event) => {
      if (!event.target.closest('.row-action-details')) {
        closeAllRowActionDetails();
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeAllRowActionDetails();
    });
  }

  // Dropdown menu user (pojok kanan atas): Profil Saya, Ubah Password, Logout
  const userMenuBtn = document.getElementById('userMenuBtn');
  const userMenuDropdown = document.getElementById('userMenuDropdown');

  if (userMenuBtn && userMenuDropdown) {
    userMenuBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      userMenuDropdown.classList.toggle('hidden');
    });

    document.addEventListener('click', (event) => {
      if (!userMenuDropdown.contains(event.target) && !userMenuBtn.contains(event.target)) {
        userMenuDropdown.classList.add('hidden');
      }
    });

    // Tutup dropdown pakai tombol Escape
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        userMenuDropdown.classList.add('hidden');
      }
    });
  }
});

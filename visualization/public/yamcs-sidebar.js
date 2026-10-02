// Yamcs Web exposes extraHeaderHTML but has no configuration option for a
// left-sidebar site link. Keep the extension limited to a normal anchor so it
// can open the separately served viewer without a Yamcs Web rebuild.
(() => {
  const replay = new URL(document.currentScript.src).searchParams.get('mode') === 'replay';
  const install = () => {
    const home = document.querySelector('ya-sidenav-item[routerlink="/instance"]');
    if (!home || !home.querySelector('a') || !home.querySelector('mat-icon') ||
        !home.querySelector('.item-content') ||
        home.parentElement?.querySelector('[data-shire-visual-link]')) return;
    const item = home.cloneNode(true);
    item.dataset.shireVisualLink = '';
    item.removeAttribute('routerlink');
    item.removeAttribute('activewhen');
    item.classList.remove('active');
    item.setAttribute('label', 'Visualization');
    const link = item.querySelector('a');
    link.href = replay ? '/visualization/?mode=replay' : '/visualization/';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', 'Open SHIRE Visualization in a new window');
    item.querySelector('mat-icon').textContent = 'public';
    item.querySelector('.item-content').textContent = 'Visualization';
    home.after(item);
  };
  new MutationObserver(install).observe(document.documentElement, {childList:true,subtree:true});
  install();
})();

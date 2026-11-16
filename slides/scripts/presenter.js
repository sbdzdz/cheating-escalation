(() => {
  const button = document.getElementById('rb-present');
  let presenting = false;
  let ownsFullscreen = false;
  const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement;
  function setPresenting(value) {
    presenting = value;
    document.documentElement.toggleAttribute('data-rb-presenting', value);
    window.postMessage({ __omelette_presenting: value }, '*');
    if (!value) button.focus({ preventScroll: true });
  }
  async function enter(useFullscreen = false) {
    if (!presenting) setPresenting(true);
    if (!useFullscreen) return;
    const root = document.documentElement;
    const request = root.requestFullscreen || root.webkitRequestFullscreen;
    if (!fullscreenElement() && request) {
      ownsFullscreen = true;
      try { await request.call(root); }
      catch (_) { ownsFullscreen = false; } // Keep a clean slide view if fullscreen is unavailable.
    }
  }
  async function leave() {
    setPresenting(false);
    if (ownsFullscreen && fullscreenElement()) {
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      try { if (exit) await exit.call(document); } catch (_) {}
    }
    ownsFullscreen = false;
  }
  button.addEventListener('click', () => enter());
  document.getElementById('rb-fullscreen').addEventListener('click', () => enter(true));
  window.addEventListener('keydown', (event) => {
    const target = event.composedPath()[0];
    if (event.key === 'Escape' && presenting) {
      event.preventDefault();
      event.stopImmediatePropagation();
      leave();
      return;
    }
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey ||
        target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName)) return;
    if (event.key.toLowerCase() === 'f') {
      event.preventDefault();
      if (event.shiftKey) enter(true);
      else if (presenting) leave(); else enter();
    }
  }, true);
  function syncFullscreen() {
    if (ownsFullscreen && !fullscreenElement()) {
      ownsFullscreen = false;
      if (presenting) setPresenting(false);
    }
  }
  document.addEventListener('fullscreenchange', syncFullscreen);
  document.addEventListener('webkitfullscreenchange', syncFullscreen);
})();

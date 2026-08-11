async (page) => {
  const { readFileSync } = await import('fs');
  const token = readFileSync('/tmp/recaptcha_token.txt', 'utf8').trim();
  return await page.evaluate((token) => {
    document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => { el.value = token; el.style.display = 'block'; });
    if (window.___grecaptcha_cfg) {
      const clients = window.___grecaptcha_cfg.clients;
      for (const key in clients) {
        const walk = (obj, d) => {
          if (d > 4 || !obj) return;
          for (const k in obj) {
            if (typeof obj[k] === 'function' && k.length < 3) try { obj[k](token); } catch(e) {}
            else if (typeof obj[k] === 'object') walk(obj[k], d+1);
          }
        };
        walk(clients[key], 0);
      }
    }
    const el = document.querySelector('[name="g-recaptcha-response"]');
    return { injected: true, len: el?.value?.length || 0 };
  }, token);
}

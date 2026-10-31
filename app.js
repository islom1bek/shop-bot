const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
try { // цвет шапки Telegram берём из дизайна: переменная --bg в design/style.css
  const c = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#05070f';
  tg?.setHeaderColor?.(c); tg?.setBackgroundColor?.(c); tg?.setBottomBarColor?.(c);
} catch (_) {}

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => new Intl.NumberFormat('ru-RU').format(n).replace(/\u00a0/g, ' ');
const money = n => fmt(n) + ' сум';
const when = iso => new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
const hap = (t = 'light') => tg?.HapticFeedback?.impactOccurred(t);

const CATS = [['stars', '⭐ Stars'], ['premium', '💎 Premium'], ['gifts', '🎁 Подарки']];
const ORDER_ST = {processing: ['В работе', 'wait'], done: ['Выдано', 'ok'], refunded: ['Возврат', 'bad']};
const TOPUP_ST = {pending: ['Ждём оплату', 'wait'], paid: ['Зачислено', 'ok'], expired: ['Истёк', ''], rejected: ['Отклонён', 'bad']};
const S = {tab: 'shop', cat: 'stars', method: 'uzcard', hist: 'orders', data: null, topup: null, tick: 0};

async function api(path, body) {
  try {
    const r = await fetch('/api' + path, {
      method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || ''},
      body: body ? JSON.stringify(body) : undefined,
    });
    return await r.json();
  } catch (_) { return {ok: false, error: 'network', message: 'Нет соединения. Проверьте интернет'}; }
}

async function load() {
  const j = await api('/bootstrap');
  if (!j.ok) {
    if (j.error === 'not_subscribed') renderSub(j); else $('#view').innerHTML = `<div class="empty">${esc(j.message)}</div>`;
    return false;
  }
  S.data = j;
  $('#hi').textContent = j.user.name;
  $('#ava').textContent = (j.user.name[0] || 'S').toUpperCase();
  $('#balChip').textContent = money(j.user.balance);
  return true;
}

/* ---------- модальные окна ---------- */
function sheet(html) { $('#sheet').innerHTML = html; document.body.classList.add('sheet-open'); }
function closeSheet() { document.body.classList.remove('sheet-open'); }
function toast(t) { const el = $('#toast'); el.textContent = t; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 1800); }
function errorSheet(code, message) {
  hap('medium');
  const extra = code === 'insufficient'
    ? `<button class="btn" data-act="close-goto" data-tab="topup">Пополнить баланс</button>`
    : code === 'service_disabled' ? `<button class="btn" data-act="support">Написать в поддержку</button>` : '';
  const title = code === 'insufficient' ? 'Недостаточно средств' : code === 'service_disabled' ? 'Сервис недоступен' : 'Не получилось';
  sheet(`<div class="big-em">${code === 'service_disabled' ? '🛠' : '⚠️'}</div><h3>${title}</h3>
    <div class="hint">${esc(message)}</div>${extra}<button class="btn ghost" data-act="close">Закрыть</button>`);
}
function openSupport() {
  const url = S.data?.support;
  if (!url) return toast('Поддержка пока не настроена');
  if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank');
}

/* ---------- магазин ---------- */
function gridHTML() {
  const items = S.data.products.filter(p => p.category === S.cat);
  if (!items.length) return '<div class="empty">Здесь пока ничего нет</div>';
  const off = !S.data.toggles[S.cat];
  return items.map(p => `<button class="card ${off ? 'off' : ''}" data-act="product" data-id="${p.id}">
    <span class="em">${p.emoji}</span><span class="t">${esc(p.title)}</span><span class="p">${money(p.price)}</span></button>`).join('');
}
function renderShop() {
  const i = CATS.findIndex(c => c[0] === S.cat);
  $('#view').innerHTML = `<h2>Магазин</h2>
    <div class="seg" id="catSeg" style="--i:${i}">${CATS.map(([k, l]) =>
      `<button class="${k === S.cat ? 'on' : ''}" data-act="cat" data-k="${k}">${l}</button>`).join('')}</div>
    <div class="grid" id="grid">${gridHTML()}</div>
    <p class="hint" style="margin-top:14px">Цена уже включает все комиссии. Выдача — вручную, обычно до 15 минут.</p>`;
}
function setCat(k) {
  S.cat = k;
  const seg = $('#catSeg'); seg.style.setProperty('--i', CATS.findIndex(c => c[0] === k));
  seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === k));
  $('#grid').innerHTML = gridHTML();
}
function openProduct(id) {
  const p = S.data.products.find(x => x.id == id); if (!p) return;
  if (!S.data.toggles[p.category]) return errorSheet('service_disabled', 'Сервис временно недоступен. Обратитесь в поддержку');
  const bal = S.data.user.balance, after = bal - p.price;
  sheet(`<div class="big-em">${p.emoji}</div><h3>${esc(p.title)}</h3>
    <label class="field"><span>Кому выдать (Telegram @username)</span>
      <input id="rcpt" placeholder="@username" autocapitalize="off" autocomplete="off" value="${esc(S.data.user.username ? '@' + S.data.user.username : '')}"></label>
    <div class="kv"><span>Цена</span><b>${money(p.price)}</b></div>
    <div class="kv"><span>Ваш баланс</span><b>${money(bal)}</b></div>
    <div class="kv"><span>После покупки</span><b style="color:${after < 0 ? 'var(--bad)' : 'inherit'}">${money(Math.max(after, 0))}</b></div>
    <button class="btn" id="buyBtn" data-act="buy" data-id="${p.id}">Купить за ${money(p.price)}</button>
    <button class="btn ghost" data-act="close">Отмена</button>`);
}
async function buy(id, btn) {
  const p = S.data.products.find(x => x.id == id);
  if (S.data.user.balance < p.price) return errorSheet('insufficient', `Не хватает ${money(p.price - S.data.user.balance)}. Пополните баланс и повторите покупку.`);
  btn.disabled = true; btn.textContent = 'Оформляем…';
  const j = await api('/buy', {product_id: id, recipient: $('#rcpt').value});
  if (!j.ok) { await load(); return errorSheet(j.error, j.message); }
  hap('heavy'); tg?.HapticFeedback?.notificationOccurred('success');
  S.data.user.balance = j.balance; $('#balChip').textContent = money(j.balance);
  sheet(`<div class="big-em">✅</div><h3>Заказ #${j.order.id} оформлен</h3>
    <div class="hint">${esc(j.order.title)} для @${esc(j.order.recipient)}. Мы выдадим его вручную и пришлём уведомление в бот.</div>
    <button class="btn" data-act="close-goto" data-tab="profile">К истории заказов</button>`);
  load();
}

/* ---------- пополнение ---------- */
function renderTopup() {
  const d = S.data, t = S.topup;
  if (t && t.status === 'pending') return renderPay();
  const m = S.method;
  $('#view').innerHTML = `<h2>Пополнение</h2>
    <div class="seg" id="mSeg" style="--n:2;--i:${m === 'uzcard' ? 0 : 1}">
      <button class="${m === 'uzcard' ? 'on' : ''}" data-act="method" data-k="uzcard">Uzcard</button>
      <button class="${m === 'humo' ? 'on' : ''}" data-act="method" data-k="humo">Humo</button></div>
    <label class="field"><span>Сумма в сумах (от ${fmt(d.limits.min)} до ${fmt(d.limits.max)})</span>
      <input id="amt" inputmode="numeric" placeholder="50 000" autocomplete="off"></label>
    <div class="quick">${[20000, 50000, 100000, 250000].map(v => `<button data-act="amt" data-v="${v}">${fmt(v)}</button>`).join('')}</div>
    <button class="btn" id="topBtn" data-act="topup">Получить реквизиты</button>
    <p class="hint" style="margin-top:14px">Деньги зачисляются автоматически в течение минуты после перевода.</p>`;
  $('#amt').addEventListener('input', e => { const v = e.target.value.replace(/\D/g, ''); e.target.value = v ? fmt(v) : ''; });
}
function renderPay() {
  const t = S.topup;
  $('#view').innerHTML = `<h2>Переведите ${t.method === 'humo' ? 'на Humo' : 'на Uzcard'}</h2>
    <div class="pay">
      <button class="copy sum" data-act="copy" data-v="${t.amount}"><span><small>Сумма — ровно столько</small><b>${money(t.amount)}</b></span><em>копировать</em></button>
      <button class="copy" data-act="copy" data-v="${esc(t.card.replace(/\s/g, ''))}"><span><small>Номер карты</small><b>${esc(t.card)}</b></span><em>копировать</em></button>
      <div class="copy"><span><small>Получатель</small><b style="font-size:17px">${esc(t.holder || '—')}</b></span></div>
      <ol class="steps"><li>Откройте банковское приложение и переведите <b>точную сумму</b> на карту.</li>
        <li>Не меняйте сумму: по ней мы находим ваш платёж.</li><li>Вернитесь сюда — баланс обновится сам.</li></ol>
      <div class="timer"><span><i class="pulse"></i>Ждём перевод</span><span id="left"></span></div>
    </div>
    <button class="btn ghost" style="margin-top:12px" data-act="cancelPay">Отменить</button>`;
  updateTimer();
}
async function createTopup(btn) {
  const amount = parseInt($('#amt').value.replace(/\D/g, ''), 10);
  if (!amount) return toast('Введите сумму');
  btn.disabled = true;
  const j = await api('/topup', {amount, method: S.method});
  btn.disabled = false;
  if (!j.ok) return errorSheet(j.error, j.message);
  S.topup = j.topup; renderTopup();
}
function updateTimer() {
  const t = S.topup, el = $('#left'); if (!t || !el) return;
  const s = Math.max(0, Math.floor((new Date(t.expires_at) - Date.now()) / 1000));
  el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  if (s === 0) { S.topup = null; toast('Время платежа истекло'); renderTopup(); }
}
async function pollTopup() {
  const t = S.topup; if (!t || S.tab !== 'topup') return;
  const j = await api('/topup/' + t.id);
  if (j.ok && j.status === 'paid') {
    S.topup = null; await load(); hap('heavy');
    sheet(`<div class="big-em">✅</div><h3>Баланс пополнен</h3><div class="hint">Сейчас на балансе ${money(j.balance)}</div>
      <button class="btn" data-act="close-goto" data-tab="shop">В магазин</button>`);
    renderTopup();
  }
}
setInterval(() => { if (S.topup && S.tab === 'topup') { updateTimer(); if (++S.tick % 5 === 0) pollTopup(); } }, 1000);

/* ---------- профиль ---------- */
function renderProfile() {
  const d = S.data, isO = S.hist === 'orders';
  const rows = isO ? d.orders.map(o => { const [l, c] = ORDER_ST[o.status] || [o.status, '']; return `<div class="row"><div class="l"><b>${esc(o.title)}</b><small>#${o.id} · ${when(o.created_at)}</small></div>
      <div class="r"><b>${money(o.price)}</b><br><span class="st ${c}">${l}</span></div></div>`; })
    : d.topups.map(t => { const [l, c] = TOPUP_ST[t.status] || [t.status, '']; return `<div class="row"><div class="l"><b>+${money(t.amount)}</b><small>${t.method === 'humo' ? 'Humo' : 'Uzcard'} · ${when(t.created_at)}</small></div>
      <div class="r"><span class="st ${c}">${l}</span></div></div>`; });
  $('#view').innerHTML = `<div class="hero"><div class="hint">Ваш баланс</div><div class="big">${money(d.user.balance)}</div>
      <button class="btn" data-act="goto" data-tab="topup">Пополнить</button></div>
    <div class="seg" style="--n:2;--i:${isO ? 0 : 1}"><button class="${isO ? 'on' : ''}" data-act="hist" data-k="orders">Покупки</button>
      <button class="${!isO ? 'on' : ''}" data-act="hist" data-k="topups">Пополнения</button></div>
    <div class="list">${rows.join('') || `<div class="empty">${isO ? 'Покупок пока нет — загляните в магазин' : 'Пополнений пока нет'}</div>`}</div>`;
}

/* ---------- подписка на каналы ---------- */
function renderSub(j) {
  const chans = (j.channels || []).map(c => c.link
    ? `<button class="row" data-act="link" data-url="${esc(c.link)}"><div class="l"><b>📢 ${esc(c.title)}</b><small>Нажмите, чтобы открыть</small></div><div class="r"><span class="st wait">Подписаться</span></div></button>`
    : `<div class="row"><div class="l"><b>📢 ${esc(c.title)}</b></div></div>`).join('');
  $('#view').innerHTML = `<div class="hero"><div style="font-size:42px">🔒</div><h2 style="margin:6px 0">Подпишитесь на каналы</h2>
    <p class="hint" style="margin:0">Чтобы пользоваться магазином, подпишитесь на каналы ниже и нажмите «Я подписался».</p></div>
    <div class="list">${chans}</div><button class="btn" style="margin-top:14px" data-act="resub">✅ Я подписался</button>`;
}

/* ---------- рефералы ---------- */
function renderRef() {
  const r = S.ref, so = n => fmt(n) + " so'm";
  const friends = r.friends.map(f => `<div class="row"><div class="l"><b>${esc(f.first_name || 'Do\'st')}${f.username ? ' · @' + esc(f.username) : ''}</b><small>${when(f.joined)}</small></div>
      <div class="r"><b>+${so(f.earned)}</b></div></div>`).join('');
  $('#view').innerHTML = `<h2>Do'stlarni taklif qilish</h2>
    <div class="refhero"><div class="refico">🎁</div><p>${esc(r.text)}</p></div>
    <div class="hint" style="margin:0 0 6px">Sizning havolangiz</div>
    <div class="linkbox"><code>${esc(r.link)}</code><button data-act="copy" data-v="${esc(r.link)}">Nusxalash</button></div>
    <button class="btn" style="margin-top:12px" data-act="share">Do'stlarni taklif qilish</button>
    <div class="stats"><div class="stat"><b>${fmt(r.invited)}</b><span>Taklif qilingan do'stlar</span></div>
      <div class="stat gold"><b>${so(r.earned)}</b><span>Daromad</span></div></div>
    <h3 class="sec">Takliflar ro'yxati</h3>
    <div class="list">${friends || '<div class="empty">Hali hech kim taklif qilinmagan</div>'}</div>`;
}

/* ---------- навигация и события ---------- */
function render() {
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === S.tab));
  ({shop: renderShop, topup: renderTopup, ref: renderRef, profile: renderProfile})[S.tab]();
  window.scrollTo(0, 0);
}
async function goto(tab) {
  S.tab = tab;
  if (tab !== 'shop' && !(await load())) return;
  if (tab === 'ref') { const j = await api('/referrals'); if (!j.ok) return errorSheet(j.error, j.message); S.ref = j; }
  render();
}

document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const d = el.dataset; hap();
  switch (d.act) {
    case 'goto': return goto(d.tab);
    case 'close': return closeSheet();
    case 'close-goto': closeSheet(); return goto(d.tab);
    case 'support': closeSheet(); return openSupport();
    case 'cat': return setCat(d.k);
    case 'product': return openProduct(d.id);
    case 'buy': return buy(d.id, el);
    case 'method': S.method = d.k; return renderTopup();
    case 'amt': $('#amt').value = fmt(d.v); return;
    case 'topup': return createTopup(el);
    case 'cancelPay': S.topup = null; return renderTopup();
    case 'hist': S.hist = d.k; return renderProfile();
    case 'link': return tg?.openTelegramLink ? tg.openTelegramLink(d.url) : window.open(d.url, '_blank');
    case 'resub': if (await load()) { toast('Спасибо!'); render(); } else toast('Подписка не найдена'); return;
    case 'share': { const u = 'https://t.me/share/url?url=' + encodeURIComponent(S.ref.link) + '&text=' + encodeURIComponent("Stars, Premium va NFT sovg'alar — eng qulay narxlarda! 🚀");
      return tg?.openTelegramLink ? tg.openTelegramLink(u) : window.open(u, '_blank'); }
    case 'copy':
      try { await navigator.clipboard.writeText(d.v); } catch (_) {
        const t = document.createElement('textarea'); t.value = d.v; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
      return toast('Скопировано');
  }
});

(async () => { if (await load()) render(); })();

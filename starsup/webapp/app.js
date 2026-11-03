const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
try { // цвет шапки Telegram берём из дизайна: переменная --bg в design/style.css
  const c = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#05070f';
  tg?.setHeaderColor?.(c); tg?.setBackgroundColor?.(c); tg?.setBottomBarColor?.(c);
} catch (_) {}

const T0 = Date.now();
const REDUCED = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/* ======================= TILLAR / ЯЗЫКИ (uz · ru) =======================
   Yangi matn: ikkala tilga bir xil kalit bilan qo'shing. Matnda {nom} — o'zgaruvchi (tr('kalit', {nom: ...})).
   Server xatolari: e_<kod> kalitlari. Mahsulot nomlari serverda (i18n.py::loc_title) tarjima qilinadi. */
const TR = {
  uz: {
    cur: "so'm", sub: "Stars, Premium, sovg'alar", support: '🛟 Yordam', supportAria: 'Yordam',
    tab_shop: "Do'kon", tab_topup: "To'ldirish", tab_ref: "Do'stlar", tab_profile: 'Profil',
    cat_stars: '⭐ Stars', cat_premium: '💎 Premium', cat_gifts: "🎁 Sovg'alar",
    o_processing: 'Navbatda', o_delivering: 'Topshirilmoqda…', o_review: 'Tekshiruvda', o_done: 'Topshirildi', o_refunded: 'Qaytarildi',
    t_pending: "To'lov kutilmoqda", t_paid: 'Hisobga tushdi', t_expired: 'Muddati tugadi', t_rejected: 'Rad etildi',
    unavailable: 'Mavjud emas', close: 'Yopish', cancel: 'Bekor qilish', copied: 'Nusxalandi',
    err_title: 'Bajarilmadi', err_insufficient: "Mablag' yetarli emas", err_disabled: 'Xizmat mavjud emas',
    err_topup: "Balansni to'ldirish", err_support: 'Yordamga yozish',
    e_network: "Aloqa yo'q. Internetni tekshiring", e_auth: "Do'konni Telegram orqali oching",
    e_service_disabled: "Xizmat vaqtincha mavjud emas. Yordamga murojaat qiling", e_insufficient: "Mablag' yetarli emas",
    e_no_username: "Bu mahsulot uchun @username kerak: uni Telegram sozlamalarida o'rnating va qayta urinib ko'ring",
    e_bad_amount: "To'ldirish summasi: {lo} dan {hi} so'mgacha", e_bad_request: "Noto'g'ri so'rov",
    e_not_found: 'Topilmadi', e_busy: "Hozir to'lovlar ko'p, bir necha daqiqadan keyin urinib ko'ring",
    e_server: "Server xatosi. Keyinroq urinib ko'ring",
    support_none: 'Yordam hali sozlanmagan',
    shop: "Do'kon", shop_empty: "Bu yerda hozircha hech narsa yo'q",
    shop_hint: "Narx barcha komissiyalarni o'z ichiga oladi. Topshirish avtomatik, odatda bir daqiqagacha.",
    p_auto: 'Topshirish avtomatik — sizning akkauntingizga', price: 'Narxi', balance: 'Sizning balansingiz',
    after: 'Xariddan keyin', buy_for: 'Sotib olish — {sum}',
    short: "{sum} yetishmaydi. Balansni to'ldiring va xaridni takrorlang.", buying: 'Rasmiylashtirilmoqda…',
    ordered: 'Buyurtma #{id} rasmiylashtirildi',
    ordered_t: "«{title}» to'landi. Topshirish avtomatik — odatda bir daqiqagacha, xabar botga keladi.",
    to_orders: 'Buyurtmalar tarixiga',
    topup: "To'ldirish", amount_label: "Summa so'mda ({lo} dan {hi} gacha)", get_req: 'Rekvizitlarni olish',
    topup_hint: "Pul o'tkazmadan keyin bir daqiqa ichida avtomatik hisobga tushadi.", enter_sum: 'Summani kiriting',
    pay_to: "{card} kartasiga o'tkazing", pay_sum: 'Summa — aynan shuncha', copy: 'nusxalash', card_no: 'Karta raqami',
    holder: 'Qabul qiluvchi',
    step1: "Bank ilovasini oching va kartaga <b>aniq summani</b> o'tkazing.",
    step2: "Summani o'zgartirmang: to'lovingizni shu summa orqali topamiz.",
    step3: "Shu yerga qayting — balans o'zi yangilanadi.",
    waiting: "O'tkazma kutilmoqda", pay_expired: "To'lov vaqti tugadi",
    paid_title: "Balans to'ldirildi", paid_text: 'Hozir balansda {sum}', to_shop: "Do'konga",
    your_balance: 'Sizning balansingiz', topup_btn: "To'ldirish", orders: 'Xaridlar', topups: "To'ldirishlar",
    no_orders: "Hozircha xaridlar yo'q — do'konga kiring", no_topups: "Hozircha to'ldirishlar yo'q", language: 'Til',
    sub_title: "Kanallarga obuna bo'ling",
    sub_text: "Do'kondan foydalanish uchun quyidagi kanallarga obuna bo'ling va «Obuna bo'ldim» tugmasini bosing.",
    sub_open: 'Ochish uchun bosing', sub_go: "Obuna bo'lish", sub_done: "✅ Obuna bo'ldim", thanks: 'Rahmat!',
    sub_none: 'Obuna topilmadi',
    ref_title: "Do'stlarni taklif qilish", ref_link: 'Sizning havolangiz', ref_copy: 'Nusxalash',
    ref_invite: "Do'stlarni taklif qilish", ref_invited: "Taklif qilingan do'stlar", ref_income: 'Daromad',
    ref_list: "Takliflar ro'yxati", ref_empty: "Hali hech kim taklif qilinmagan", friend: "Do'st",
    pick_title: 'Tilni tanlang · Выберите язык',
  },
  ru: {
    cur: 'сум', sub: 'Stars, Premium, подарки', support: '🛟 Поддержка', supportAria: 'Поддержка',
    tab_shop: 'Магазин', tab_topup: 'Пополнить', tab_ref: 'Друзья', tab_profile: 'Профиль',
    cat_stars: '⭐ Stars', cat_premium: '💎 Premium', cat_gifts: '🎁 Подарки',
    o_processing: 'В очереди', o_delivering: 'Выдаём…', o_review: 'Проверка', o_done: 'Выдано', o_refunded: 'Возврат',
    t_pending: 'Ждём оплату', t_paid: 'Зачислено', t_expired: 'Истёк', t_rejected: 'Отклонён',
    unavailable: 'Недоступно', close: 'Закрыть', cancel: 'Отмена', copied: 'Скопировано',
    err_title: 'Не получилось', err_insufficient: 'Недостаточно средств', err_disabled: 'Сервис недоступен',
    err_topup: 'Пополнить баланс', err_support: 'Написать в поддержку',
    e_network: 'Нет соединения. Проверьте интернет', e_auth: 'Откройте магазин через Telegram',
    e_service_disabled: 'Сервис временно недоступен. Обратитесь в поддержку', e_insufficient: 'Недостаточно средств',
    e_no_username: 'Для этого товара нужен @username: задайте его в настройках Telegram и повторите',
    e_bad_amount: 'Сумма пополнения: от {lo} до {hi} сум', e_bad_request: 'Некорректный запрос',
    e_not_found: 'Не найдено', e_busy: 'Сейчас много платежей, попробуйте через пару минут',
    e_server: 'Ошибка сервера. Попробуйте позже',
    support_none: 'Поддержка пока не настроена',
    shop: 'Магазин', shop_empty: 'Здесь пока ничего нет',
    shop_hint: 'Цена уже включает все комиссии. Выдача автоматическая, обычно до минуты.',
    p_auto: 'Выдача автоматическая — на ваш аккаунт', price: 'Цена', balance: 'Ваш баланс',
    after: 'После покупки', buy_for: 'Купить за {sum}',
    short: 'Не хватает {sum}. Пополните баланс и повторите покупку.', buying: 'Оформляем…',
    ordered: 'Заказ #{id} оформлен',
    ordered_t: '«{title}» оплачен. Выдача автоматическая — обычно до минуты, уведомление придёт в бот.',
    to_orders: 'К истории заказов',
    topup: 'Пополнение', amount_label: 'Сумма в сумах (от {lo} до {hi})', get_req: 'Получить реквизиты',
    topup_hint: 'Деньги зачисляются автоматически в течение минуты после перевода.', enter_sum: 'Введите сумму',
    pay_to: 'Переведите на {card}', pay_sum: 'Сумма — ровно столько', copy: 'копировать', card_no: 'Номер карты',
    holder: 'Получатель',
    step1: 'Откройте банковское приложение и переведите <b>точную сумму</b> на карту.',
    step2: 'Не меняйте сумму: по ней мы находим ваш платёж.',
    step3: 'Вернитесь сюда — баланс обновится сам.',
    waiting: 'Ждём перевод', pay_expired: 'Время платежа истекло',
    paid_title: 'Баланс пополнен', paid_text: 'Сейчас на балансе {sum}', to_shop: 'В магазин',
    your_balance: 'Ваш баланс', topup_btn: 'Пополнить', orders: 'Покупки', topups: 'Пополнения',
    no_orders: 'Покупок пока нет — загляните в магазин', no_topups: 'Пополнений пока нет', language: 'Язык',
    sub_title: 'Подпишитесь на каналы',
    sub_text: 'Чтобы пользоваться магазином, подпишитесь на каналы ниже и нажмите «Я подписался».',
    sub_open: 'Нажмите, чтобы открыть', sub_go: 'Подписаться', sub_done: '✅ Я подписался', thanks: 'Спасибо!',
    sub_none: 'Подписка не найдена',
    ref_title: 'Пригласить друзей', ref_link: 'Ваша ссылка', ref_copy: 'Копировать',
    ref_invite: 'Пригласить друзей', ref_invited: 'Приглашённые друзья', ref_income: 'Доход',
    ref_list: 'Список приглашённых', ref_empty: 'Пока никого не приглашали', friend: 'Друг',
    pick_title: 'Tilni tanlang · Выберите язык',
  },
};

const S = {lang: null, tab: 'shop', cat: 'stars', method: 'uzcard', hist: 'orders', data: null, topup: null, tick: 0};
const tr = (k, v = {}) => (TR[S.lang || 'uz'][k] ?? TR.uz[k] ?? k).replace(/\{(\w+)\}/g, (_, n) => v[n] ?? '');
/* xato kodi -> tarjima; yo'q bo'lsa serverdan kelgan matn */
const errMsg = (code, fallback) => {
  const k = 'e_' + code, lim = S.data?.limits || {};
  return TR[S.lang || 'uz'][k] ? tr(k, {lo: fmt(lim.min || 0), hi: fmt(lim.max || 0)}) : (fallback || tr('e_server'));
};
function applyStatic() {
  document.documentElement.lang = S.lang || 'uz';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-aria]').forEach(el => el.setAttribute('aria-label', tr(el.dataset.i18nAria)));
}
function setLang(l) { S.lang = (l === 'uz' || l === 'ru') ? l : null; applyStatic(); }

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => new Intl.NumberFormat('ru-RU').format(n).replace(/\u00a0/g, ' ');
const money = n => fmt(n) + ' ' + tr('cur');
const when = iso => {
  const opts = {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'};
  try { return new Date(iso).toLocaleString(S.lang === 'ru' ? 'ru-RU' : 'uz-Latn-UZ', opts); }
  catch (_) { return new Date(iso).toLocaleString('ru-RU', opts); }
};
const hap = (t = 'light') => tg?.HapticFeedback?.impactOccurred(t);

const CATS = ['stars', 'premium', 'gifts'];
const ORDER_ST = {processing: 'wait', delivering: 'wait', review: 'wait', done: 'ok', refunded: 'bad'};
const TOPUP_ST = {pending: 'wait', paid: 'ok', expired: '', rejected: 'bad'};

async function api(path, body) {
  try {
    const r = await fetch('/api' + path, {
      method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || ''},
      body: body ? JSON.stringify(body) : undefined,
    });
    return await r.json();
  } catch (_) { return {ok: false, error: 'network', message: ''}; }
}

async function load() {
  const j = await api('/bootstrap');
  if (j.lang !== undefined) setLang(j.lang);             // null = til hali tanlanmagan
  if (j.lang === null) { renderLangPick(); return false; }
  document.body.classList.remove('picking');
  if (!j.ok) {
    if (j.error === 'not_subscribed') renderSub(j); else $('#view').innerHTML = `<div class="empty">${esc(errMsg(j.error, j.message))}</div>`;
    return false;
  }
  S.data = j;
  $('#hi').textContent = j.user.name;
  $('#balChip').textContent = money(j.user.balance);
  return true;
}

/* ---------- til tanlash (birinchi kirish) ---------- */
function renderLangPick() {
  document.body.classList.add('picking');
  $('#view').innerHTML = `<div class="hero" style="text-align:center"><div style="font-size:42px">🌐</div>
    <h2 style="margin:6px 0 16px">${tr('pick_title')}</h2>
    <button class="btn" data-act="pick" data-k="uz">🇺🇿 O'zbekcha</button>
    <button class="btn ghost" style="margin-top:10px" data-act="pick" data-k="ru">🇷🇺 Русский</button></div>`;
}

/* ---------- модальные окна ---------- */
function sheet(html) { $('#sheet').innerHTML = html; document.body.classList.add('sheet-open'); }
function closeSheet() { document.body.classList.remove('sheet-open'); }
function toast(t) { const el = $('#toast'); el.textContent = t; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 1800); }
function errorSheet(code, message) {
  hap('medium');
  const extra = code === 'insufficient'
    ? `<button class="btn" data-act="close-goto" data-tab="topup">${tr('err_topup')}</button>`
    : code === 'service_disabled' ? `<button class="btn" data-act="support">${tr('err_support')}</button>` : '';
  const title = code === 'insufficient' ? tr('err_insufficient') : code === 'service_disabled' ? tr('err_disabled') : tr('err_title');
  sheet(`<div class="big-em">${code === 'service_disabled' ? '🛠' : '⚠️'}</div><h3>${title}</h3>
    <div class="hint">${esc(errMsg(code, message))}</div>${extra}<button class="btn ghost" data-act="close">${tr('close')}</button>`);
}
function openSupport() {
  const url = S.data?.support;
  if (!url) return toast(tr('support_none'));
  if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank');
}

/* ---------- магазин ---------- */
function gridHTML() {
  const items = S.data.products.filter(p => p.category === S.cat);
  if (!items.length) return `<div class="empty">${tr('shop_empty')}</div>`;
  const off = !S.data.toggles[S.cat];
  return items.map(p => `<button class="card ${off ? 'off' : ''}" data-off="${tr('unavailable')}" data-act="product" data-id="${p.id}">
    <span class="em">${p.emoji}</span><span class="t">${esc(p.title)}</span><span class="p">${money(p.price)}</span></button>`).join('');
}
function renderShop() {
  const i = CATS.indexOf(S.cat);
  $('#view').innerHTML = `<h2>${tr('shop')}</h2>
    <div class="seg" id="catSeg" style="--i:${i}">${CATS.map(k =>
      `<button class="${k === S.cat ? 'on' : ''}" data-act="cat" data-k="${k}">${tr('cat_' + k)}</button>`).join('')}</div>
    <div class="grid" id="grid">${gridHTML()}</div>
    <p class="hint" style="margin-top:14px">${tr('shop_hint')}</p>`;
}
function setCat(k) {
  S.cat = k;
  const seg = $('#catSeg'); seg.style.setProperty('--i', CATS.indexOf(k));
  seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === k));
  $('#grid').innerHTML = gridHTML();
}
function openProduct(id) {
  const p = S.data.products.find(x => x.id == id); if (!p) return;
  if (!S.data.toggles[p.category]) return errorSheet('service_disabled');
  const bal = S.data.user.balance, after = bal - p.price;
  sheet(`<div class="big-em">${p.emoji}</div><h3>${esc(p.title)}</h3>
    <div class="hint" style="margin:6px 0 10px">${tr('p_auto')}${S.data.user.username ? ' (@' + esc(S.data.user.username) + ')' : ''}.</div>
    <div class="kv"><span>${tr('price')}</span><b>${money(p.price)}</b></div>
    <div class="kv"><span>${tr('balance')}</span><b>${money(bal)}</b></div>
    <div class="kv"><span>${tr('after')}</span><b style="color:${after < 0 ? 'var(--bad)' : 'inherit'}">${money(Math.max(after, 0))}</b></div>
    <button class="btn" id="buyBtn" data-act="buy" data-id="${p.id}">${tr('buy_for', {sum: money(p.price)})}</button>
    <button class="btn ghost" data-act="close">${tr('cancel')}</button>`);
}
async function buy(id, btn) {
  const p = S.data.products.find(x => x.id == id);
  if (S.data.user.balance < p.price) return errorSheet('insufficient', tr('short', {sum: money(p.price - S.data.user.balance)}));
  btn.disabled = true; btn.textContent = tr('buying');
  const j = await api('/buy', {product_id: id});
  if (!j.ok) { await load(); return errorSheet(j.error, j.message); }
  hap('heavy'); tg?.HapticFeedback?.notificationOccurred('success');
  S.data.user.balance = j.balance; $('#balChip').textContent = money(j.balance);
  sheet(`<div class="big-em">✅</div><h3>${tr('ordered', {id: j.order.id})}</h3>
    <div class="hint">${esc(tr('ordered_t', {title: p.title}))}</div>
    <button class="btn" data-act="close-goto" data-tab="profile">${tr('to_orders')}</button>`);
  load();
}

/* ---------- пополнение ---------- */
function renderTopup() {
  const d = S.data, t = S.topup;
  if (t && t.status === 'pending') return renderPay();
  const m = S.method;
  $('#view').innerHTML = `<h2>${tr('topup')}</h2>
    <div class="seg" id="mSeg" style="--n:2;--i:${m === 'uzcard' ? 0 : 1}">
      <button class="${m === 'uzcard' ? 'on' : ''}" data-act="method" data-k="uzcard">Uzcard</button>
      <button class="${m === 'humo' ? 'on' : ''}" data-act="method" data-k="humo">Humo</button></div>
    <label class="field"><span>${tr('amount_label', {lo: fmt(d.limits.min), hi: fmt(d.limits.max)})}</span>
      <input id="amt" inputmode="numeric" placeholder="50 000" autocomplete="off"></label>
    <div class="quick">${[20000, 50000, 100000, 250000].map(v => `<button data-act="amt" data-v="${v}">${fmt(v)}</button>`).join('')}</div>
    <button class="btn" id="topBtn" data-act="topup">${tr('get_req')}</button>
    <p class="hint" style="margin-top:14px">${tr('topup_hint')}</p>`;
  $('#amt').addEventListener('input', e => { const v = e.target.value.replace(/\D/g, ''); e.target.value = v ? fmt(v) : ''; });
}
function renderPay() {
  const t = S.topup;
  $('#view').innerHTML = `<h2>${tr('pay_to', {card: t.method === 'humo' ? 'Humo' : 'Uzcard'})}</h2>
    <div class="pay">
      <button class="copy sum" data-act="copy" data-v="${t.amount}"><span><small>${tr('pay_sum')}</small><b>${money(t.amount)}</b></span><em>${tr('copy')}</em></button>
      <button class="copy" data-act="copy" data-v="${esc(t.card.replace(/\s/g, ''))}"><span><small>${tr('card_no')}</small><b>${esc(t.card)}</b></span><em>${tr('copy')}</em></button>
      <div class="copy"><span><small>${tr('holder')}</small><b style="font-size:17px">${esc(t.holder || '—')}</b></span></div>
      <ol class="steps"><li>${tr('step1')}</li><li>${tr('step2')}</li><li>${tr('step3')}</li></ol>
      <div class="timer"><span><i class="pulse"></i>${tr('waiting')}</span><span id="left"></span></div>
    </div>
    <button class="btn ghost" style="margin-top:12px" data-act="cancelPay">${tr('cancel')}</button>`;
  updateTimer();
}
async function createTopup(btn) {
  const amount = parseInt($('#amt').value.replace(/\D/g, ''), 10);
  if (!amount) return toast(tr('enter_sum'));
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
  if (s === 0) { S.topup = null; toast(tr('pay_expired')); renderTopup(); }
}
async function pollTopup() {
  const t = S.topup; if (!t || S.tab !== 'topup') return;
  const j = await api('/topup/' + t.id);
  if (j.ok && j.status === 'paid') {
    S.topup = null; await load(); hap('heavy');
    sheet(`<div class="big-em">✅</div><h3>${tr('paid_title')}</h3><div class="hint">${tr('paid_text', {sum: money(j.balance)})}</div>
      <button class="btn" data-act="close-goto" data-tab="shop">${tr('to_shop')}</button>`);
    renderTopup();
  }
}
setInterval(() => { if (S.topup && S.tab === 'topup') { updateTimer(); if (++S.tick % 5 === 0) pollTopup(); } }, 1000);

/* ---------- профиль ---------- */
function renderProfile() {
  const d = S.data, isO = S.hist === 'orders';
  const rows = isO ? d.orders.map(o => { const c = ORDER_ST[o.status] ?? '', l = TR[S.lang].hasOwnProperty('o_' + o.status) ? tr('o_' + o.status) : o.status;
      return `<div class="row"><div class="l"><b>${esc(o.title)}</b><small>#${o.id} · ${when(o.created_at)}</small></div>
      <div class="r"><b>${money(o.price)}</b><br><span class="st ${c}">${l}</span></div></div>`; })
    : d.topups.map(t => { const c = TOPUP_ST[t.status] ?? '', l = TR[S.lang].hasOwnProperty('t_' + t.status) ? tr('t_' + t.status) : t.status;
      return `<div class="row"><div class="l"><b>+${money(t.amount)}</b><small>${t.method === 'humo' ? 'Humo' : 'Uzcard'} · ${when(t.created_at)}</small></div>
      <div class="r"><span class="st ${c}">${l}</span></div></div>`; });
  $('#view').innerHTML = `<div class="hero"><div class="hint">${tr('your_balance')}</div><div class="big">${money(d.user.balance)}</div>
      <button class="btn" data-act="goto" data-tab="topup">${tr('topup_btn')}</button></div>
    <div class="seg" style="--n:2;--i:${isO ? 0 : 1}"><button class="${isO ? 'on' : ''}" data-act="hist" data-k="orders">${tr('orders')}</button>
      <button class="${!isO ? 'on' : ''}" data-act="hist" data-k="topups">${tr('topups')}</button></div>
    <div class="list">${rows.join('') || `<div class="empty">${isO ? tr('no_orders') : tr('no_topups')}</div>`}</div>
    <h3 class="sec">🌐 ${tr('language')}</h3>
    <div class="seg" style="--n:2;--i:${S.lang === 'ru' ? 1 : 0}"><button class="${S.lang !== 'ru' ? 'on' : ''}" data-act="setlang" data-k="uz">🇺🇿 O'zbekcha</button>
      <button class="${S.lang === 'ru' ? 'on' : ''}" data-act="setlang" data-k="ru">🇷🇺 Русский</button></div>`;
}

/* ---------- подписка на каналы ---------- */
function renderSub(j) {
  const chans = (j.channels || []).map(c => c.link
    ? `<button class="row" data-act="link" data-url="${esc(c.link)}"><div class="l"><b>📢 ${esc(c.title)}</b><small>${tr('sub_open')}</small></div><div class="r"><span class="st wait">${tr('sub_go')}</span></div></button>`
    : `<div class="row"><div class="l"><b>📢 ${esc(c.title)}</b></div></div>`).join('');
  $('#view').innerHTML = `<div class="hero"><div style="font-size:42px">🔒</div><h2 style="margin:6px 0">${tr('sub_title')}</h2>
    <p class="hint" style="margin:0">${tr('sub_text')}</p></div>
    <div class="list">${chans}</div><button class="btn" style="margin-top:14px" data-act="resub">${tr('sub_done')}</button>`;
}

/* ---------- рефералы ---------- */
function renderRef() {
  const r = S.ref, so = n => fmt(n) + ' ' + tr('cur');
  const friends = r.friends.map(f => `<div class="row"><div class="l"><b>${esc(f.first_name || tr('friend'))}${f.username ? ' · @' + esc(f.username) : ''}</b><small>${when(f.joined)}</small></div>
      <div class="r"><b>+${so(f.earned)}</b></div></div>`).join('');
  $('#view').innerHTML = `<h2>${tr('ref_title')}</h2>
    <div class="refhero"><div class="refico">🎁</div><p>${esc(r.text)}</p></div>
    <div class="hint" style="margin:0 0 6px">${tr('ref_link')}</div>
    <div class="linkbox"><code>${esc(r.link)}</code><button data-act="copy" data-v="${esc(r.link)}">${tr('ref_copy')}</button></div>
    <button class="btn" style="margin-top:12px" data-act="share">${tr('ref_invite')}</button>
    <div class="stats"><div class="stat"><b>${fmt(r.invited)}</b><span>${tr('ref_invited')}</span></div>
      <div class="stat gold"><b>${so(r.earned)}</b><span>${tr('ref_income')}</span></div></div>
    <h3 class="sec">${tr('ref_list')}</h3>
    <div class="list">${friends || `<div class="empty">${tr('ref_empty')}</div>`}</div>`;
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
    case 'pick': {                                   // birinchi kirishda til tanlash
      const j = await api('/lang', {lang: d.k});
      if (!j.ok) return errorSheet(j.error, j.message);
      setLang(d.k); if (await load()) render(); return;
    }
    case 'setlang': {                                // profildan tilni almashtirish
      if (d.k === S.lang) return;
      const j = await api('/lang', {lang: d.k});
      if (!j.ok) return toast(errMsg(j.error, j.message));
      setLang(d.k); S.topup = null; if (await load()) render(); return;
    }
    case 'link': return tg?.openTelegramLink ? tg.openTelegramLink(d.url) : window.open(d.url, '_blank');
    case 'resub': if (await load()) { toast(tr('thanks')); render(); } else toast(tr('sub_none')); return;
    case 'share': { const u = 'https://t.me/share/url?url=' + encodeURIComponent(S.ref.link) + '&text=' + encodeURIComponent(S.ref.share_text || '');
      return tg?.openTelegramLink ? tg.openTelegramLink(u) : window.open(u, '_blank'); }
    case 'copy':
      try { await navigator.clipboard.writeText(d.v); } catch (_) {
        const t = document.createElement('textarea'); t.value = d.v; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
      return toast(tr('copied'));
  }
});

/* ======================= SPLASH: logotip animatsiyasi =======================
   Logo markazda paydo bo'ladi (pop + yaltirash + to'lqinlar), ma'lumot yuklangach tepadagi
   logotip (#ava) joyiga uchib boradi, keyin kontent chiqadi. Dizayn: design/style.css (.splash). */
function endSplash() {
  const sp = $('#splash'); if (!sp) return;
  const fly = $('#spFly'), dst = $('#ava');
  const done = () => {
    document.body.classList.remove('splash-on');
    dst.classList.add('landed');
    $('#view').classList.add('enter');
    sp.remove();
  };
  if (REDUCED || !fly || !dst) return done();
  const a = fly.getBoundingClientRect(), b = dst.getBoundingClientRect();
  const dx = (b.left + b.width / 2) - (a.left + a.width / 2);
  const dy = (b.top + b.height / 2) - (a.top + a.height / 2);
  sp.classList.add('leaving');
  fly.style.transform = `translate(${dx}px,${dy}px) scale(${b.width / a.width})`;
  setTimeout(done, 760);
}

(async () => {
  applyStatic();
  const ok = await load();
  if (ok) render();
  const wait = Math.max(0, (REDUCED ? 250 : 1900) - (Date.now() - T0));
  setTimeout(endSplash, wait);
})();

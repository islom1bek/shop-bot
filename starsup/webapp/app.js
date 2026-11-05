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
    c_to: 'Qabul qiluvchi', to_whom: 'Kimga?', to_me: "O'zimga", ph_user: '@username', pick_pack: "To'plamni tanlang",
    custom_row: "O'zim kiritaman", custom_range: '{lo} – {hi} ★', custom_ph: 'Stars miqdori',
    btn_rcp: 'Qabul qiluvchini kiriting', btn_qty: 'Miqdorni kiriting', btn_buy: 'Sotib olish · {sum}',
    shop_t_stars: 'Telegram Stars olish ⭐', shop_t_premium: 'Telegram Premium olish 💎', shop_t_gifts: "Sovg'a yuborish 🎁",
    shop_s_stars: "O'zingiz yoki yaqinlaringiz uchun — 1 ★ = {n} so'm", shop_s_premium: "O'zingiz yoki yaqinlaringiz uchun — {n} oydan boshlab",
    shop_s_gifts: "Do'stingizga Telegram sovg'asi — profilida ko'rinib turadi",
    e_bad_recipient: "@username noto'g'ri. Qabul qiluvchining Telegram username'ini kiriting",
    e_bad_qty: "Stars miqdori noto'g'ri (50 – 100 000)",
    e_recipient_unknown: "Bu foydalanuvchi botni ishga tushirmagan. Unga avval botga /start yuborishini ayting",
    months: '{n} oy', per_month: "≈ {sum} so'm/oy", pick_term: 'Muddatni tanlang', pick_gift: "Sovg'ani tanlang", btn_gift: "Sovg'ani tanlang",
    note_label: 'Izoh', note_ph: 'Izohingiz (ixtiyoriy)',
    prof_orders: 'Buyurtmalar', prof_spent: 'Jami sarflangan', prof_stars: 'Olingan Stars', prof_joined: "Ro'yxatdan o'tgan",
    prof_lang_sub: 'Bot va ilova tili', prof_support: "Qo'llab-quvvatlash", prof_support_sub: "Savol yoki muammo bo'lsa yozing", prof_hist: 'Tarix',
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
    c_to: 'Получатель', to_whom: 'Кому?', to_me: 'Себе', ph_user: '@username', pick_pack: 'Выберите пакет',
    custom_row: 'Своё количество', custom_range: '{lo} – {hi} ★', custom_ph: 'Количество Stars',
    btn_rcp: 'Укажите получателя', btn_qty: 'Введите количество', btn_buy: 'Купить · {sum}',
    shop_t_stars: 'Покупка Telegram Stars ⭐', shop_t_premium: 'Покупка Telegram Premium 💎', shop_t_gifts: 'Отправить подарок 🎁',
    shop_s_stars: 'Для себя или близких — 1 ★ = {n} сум', shop_s_premium: 'Для себя или близких — от {n} мес.',
    shop_s_gifts: 'Подарок другу — будет виден в его профиле',
    e_bad_recipient: 'Некорректный @username. Введите Telegram-username получателя',
    e_bad_qty: 'Некорректное количество Stars (50 – 100 000)',
    e_recipient_unknown: 'Этот пользователь не запускал бота. Попросите его сначала отправить боту /start',
    months: '{n} мес.', per_month: '≈ {sum} сум/мес', pick_term: 'Выберите срок', pick_gift: 'Выберите подарок', btn_gift: 'Выберите подарок',
    note_label: 'Комментарий', note_ph: 'Ваш комментарий (необязательно)',
    prof_orders: 'Заказы', prof_spent: 'Всего потрачено', prof_stars: 'Получено Stars', prof_joined: 'Дата регистрации',
    prof_lang_sub: 'Язык бота и приложения', prof_support: 'Поддержка', prof_support_sub: 'Есть вопрос или проблема — напишите', prof_hist: 'История',
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

/* ---------- магазин: получатель + список пакетов / сетка подарков ---------- */
const USERNAME_RE = /^@?[A-Za-z][A-Za-z0-9_]{3,31}$/;
S.sel = {};          // выбор по категориям: {id, custom}
S.qty = '';          // своё количество Stars (строка цифр)
S.rcp = '';          // @username получателя
S.note = '';         // комментарий к подарку

const pkgs = () => S.data.products.filter(p => p.category === S.cat).sort((a, b) => (a.qty || 0) - (b.qty || 0));
const canCustom = () => S.cat === 'stars' && (S.data.custom?.unit > 0);
const canRcp = () => !!S.data.recipient_ok?.[S.cat];
function sel() {                                   // текущий выбор (Stars/Premium — первый пакет; подарок — пока не выбран)
  const items = pkgs(); let c = S.sel[S.cat];
  const ok = c && (c.custom || (c.id === null && S.cat === 'gifts') || items.some(p => p.id === c.id));
  if (!ok) c = S.sel[S.cat] = {id: S.cat === 'gifts' ? null : (items[0]?.id ?? null), custom: false};
  return c;
}
function qtyVal() {
  const q = parseInt(String(S.qty).replace(/\D/g, ''), 10), cu = S.data.custom || {};
  return q >= cu.min && q <= cu.max ? q : 0;
}
function customPrice(q) { return q * S.data.custom.unit; }       // своё количество = количество × цена 1 Stars (как на сервере)
function unitLabel() { return S.data.custom?.unit || 0; }
const pile = q => `<span class="pile">${'⭐'.repeat(q >= 1000 ? 3 : q >= 250 ? 2 : 1)}</span>`;

function premHTML(items, c, off, offTxt) {        // Premium: срок + цена за месяц + скидка относительно самого короткого срока
  const base = items[0] ? items[0].price / (items[0].qty || 1) : 0;
  return items.map(p => {
    const m = p.qty || 1, disc = base ? Math.round((1 - (p.price / m) / base) * 100) : 0;
    return `<button class="pk ${c.id === p.id ? 'on' : ''} ${off ? 'off' : ''}" data-off="${offTxt}" data-act="pk" data-id="${p.id}">
      <i class="rd"></i><span class="pile one">💎</span>
      <span class="pk-t two"><span class="l1">${tr('months', {n: m})}${disc >= 1 ? `<em class="disc">-${disc}%</em>` : ''}</span>
        <small class="l2">${tr('per_month', {sum: fmt(Math.round(p.price / m))})}</small></span>
      <span class="pk-p"><b>${fmt(p.price)}</b> <small>${tr('cur')}</small></span></button>`;
  }).join('');
}
function giftsHTML(items, c, off, offTxt) {       // подарки: сетка 3 в ряд
  return `<div class="gf-grid">` + items.map(p => {
    const name = (p.title.match(/«(.+)»/) || [])[1] || p.title;
    return `<button class="gf ${c.id === p.id ? 'on' : ''} ${off ? 'off' : ''}" data-off="${offTxt}" data-act="pk" data-id="${p.id}">
      <span class="gf-em">${p.emoji}</span><b class="gf-n">${esc(name)}</b>
      <span class="gf-p">${fmt(p.price)} <small>${tr('cur')}</small></span></button>`;
  }).join('') + `</div>`;
}
function pkHTML() {
  const items = pkgs(), c = sel(), off = !S.data.toggles[S.cat], offTxt = esc(tr('unavailable'));
  if (!items.length) return `<div class="empty">${tr('shop_empty')}</div>`;
  if (S.cat === 'premium') return premHTML(items, c, off, offTxt);
  if (S.cat === 'gifts') return giftsHTML(items, c, off, offTxt);
  const rows = items.map(p => `<button class="pk ${!c.custom && c.id === p.id ? 'on' : ''} ${off ? 'off' : ''}" data-off="${offTxt}" data-act="pk" data-id="${p.id}">
    <i class="rd"></i>${pile(p.qty || 0)}
    <span class="pk-t">${esc(p.title)}</span><span class="pk-p"><b>${fmt(p.price)}</b> <small>${tr('cur')}</small></span></button>`).join('');
  let cust = '';
  if (canCustom()) {
    const q = qtyVal(), cu = S.data.custom;
    cust = `<div class="pk cust ${c.custom ? 'on' : ''} ${off ? 'off' : ''}" data-off="${offTxt}">
      <button class="pk-hd" data-act="cust"><i class="rd"></i><span class="pen">✎</span><span class="pk-t">${tr('custom_row')}</span>
        <span class="pk-r" id="cqRange">${c.custom && q ? money(customPrice(q)) : tr('custom_range', {lo: fmt(cu.min), hi: fmt(cu.max)})}</span></button>
      ${c.custom ? `<div class="cq"><input id="cq" inputmode="numeric" placeholder="${esc(tr('custom_ph'))}" value="${S.qty ? fmt(S.qty) : ''}" autocomplete="off" maxlength="9"></div>` : ''}</div>`;
  }
  return rows + cust;
}
function bar() {                                   // состояние нижней кнопки
  const c = sel();
  if (!S.data.toggles[S.cat]) return {t: tr('unavailable'), ok: false};
  if (S.cat === 'gifts' && c.id == null) return {t: tr('btn_gift'), ok: false};
  if (canRcp() && !USERNAME_RE.test(S.rcp.trim())) return {t: tr('btn_rcp'), ok: false};
  if (c.custom) { const q = qtyVal(); return q ? {t: tr('btn_buy', {sum: money(customPrice(q))}), ok: true} : {t: tr('btn_qty'), ok: false}; }
  const p = pkgs().find(x => x.id === c.id);
  return p ? {t: tr('btn_buy', {sum: money(p.price)}), ok: true} : {t: tr('btn_qty'), ok: false};
}
function updateBar() { const b = bar(), el = $('#goBtn'); if (!el) return; el.textContent = b.t; el.disabled = !b.ok; }

function renderShop() {
  const i = CATS.indexOf(S.cat), c = S.cat, items = pkgs();
  const minM = c === 'premium' && items.length ? (items[0].qty || 3) : 3;
  const rcpBlock = canRcp() ? `<div class="rcp-row"><b>${tr('to_whom')}</b><button class="selfbtn" data-act="self">${tr('to_me')}</button></div>
    <label class="rcp-in"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4.5-5.5 8-5.5s6.5 1.5 8 5.5"/></svg>
      <input id="rcp" placeholder="${esc(tr('ph_user'))}" value="${esc(S.rcp)}" autocapitalize="off" autocorrect="off" spellcheck="false" autocomplete="off" maxlength="33"></label>` : '';
  const noteBlock = c === 'gifts' ? `<div class="sec-label">${tr('note_label')}</div>
    <label class="rcp-in"><svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/></svg>
      <input id="note" placeholder="${esc(tr('note_ph'))}" value="${esc(S.note)}" autocomplete="off" maxlength="128"></label>` : '';
  const label = c === 'premium' ? tr('pick_term') : c === 'gifts' ? tr('pick_gift') : tr('pick_pack');
  $('#view').innerHTML = `<div class="seg" id="catSeg" style="--i:${i}">${CATS.map(k =>
      `<button class="${k === c ? 'on' : ''}" data-act="cat" data-k="${k}">${tr('cat_' + k)}</button>`).join('')}</div>
    <div class="shop-head"><h2>${tr('shop_t_' + c)}</h2><p>${tr('shop_s_' + c, {n: c === 'premium' ? minM : fmt(unitLabel())})}</p></div>
    ${rcpBlock}
    <div class="sec-label">${label}</div>
    <div class="pk-list" id="pkList">${pkHTML()}</div>
    ${noteBlock}
    <p class="hint" style="margin:12px 0 0">${tr('shop_hint')}</p>
    <div class="buybar"><button class="btn" id="goBtn" data-act="go" disabled></button></div>`;
  updateBar();
}
function refreshList() { $('#pkList').innerHTML = pkHTML(); updateBar(); }

function openConfirm() {
  if (!bar().ok) return;
  const c = sel(), custom = c.custom, p = custom ? null : pkgs().find(x => x.id === c.id), q = custom ? qtyVal() : 0;
  const price = custom ? customPrice(q) : p.price, title = custom ? `${fmt(q)} Stars` : p.title, emoji = custom ? '⭐' : p.emoji;
  const rcp = canRcp() ? S.rcp.trim().replace(/^@/, '') : '', note = S.cat === 'gifts' ? S.note.trim() : '';
  S.pending = {id: p?.id, qty: q, price, title, rcp, note};
  const bal = S.data.user.balance, after = bal - price, uname = S.data.user.username;
  sheet(`<div class="big-em">${emoji}</div><h3>${esc(title)}</h3>
    ${rcp ? `<div class="kv"><span>${tr('c_to')}</span><b>@${esc(rcp)}</b></div>`
          : `<div class="hint" style="margin:6px 0 10px">${tr('p_auto')}${uname ? ' (@' + esc(uname) + ')' : ''}.</div>`}
    ${note ? `<div class="kv"><span>${tr('note_label')}</span><b style="max-width:62%;text-align:right;word-break:break-word">${esc(note)}</b></div>` : ''}
    <div class="kv"><span>${tr('price')}</span><b>${money(price)}</b></div>
    <div class="kv"><span>${tr('balance')}</span><b>${money(bal)}</b></div>
    <div class="kv"><span>${tr('after')}</span><b style="color:${after < 0 ? 'var(--bad)' : 'inherit'}">${money(Math.max(after, 0))}</b></div>
    <button class="btn" id="buyBtn" data-act="buy">${tr('buy_for', {sum: money(price)})}</button>
    <button class="btn ghost" data-act="close">${tr('cancel')}</button>`);
}
async function buy(btn) {
  const P = S.pending; if (!P) return;
  if (S.data.user.balance < P.price) return errorSheet('insufficient', tr('short', {sum: money(P.price - S.data.user.balance)}));
  btn.disabled = true; btn.textContent = tr('buying');
  const body = P.id ? {product_id: P.id} : {custom_qty: P.qty};
  if (P.rcp) body.recipient = P.rcp;
  if (P.note) body.note = P.note;
  const j = await api('/buy', body);
  if (!j.ok) { await load(); return errorSheet(j.error, j.message); }
  hap('heavy'); tg?.HapticFeedback?.notificationOccurred('success');
  S.data.user.balance = j.balance; $('#balChip').textContent = money(j.balance);
  sheet(`<div class="big-em">✅</div><h3>${tr('ordered', {id: j.order.id})}</h3>
    <div class="hint">${esc(tr('ordered_t', {title: P.title}))}</div>
    <button class="btn" data-act="close-goto" data-tab="profile">${tr('to_orders')}</button>`);
  S.pending = null; load();
}

/* поля магазина: @username, комментарий к подарку и своё количество Stars */
document.addEventListener('input', e => {
  const el = e.target;
  if (el.id === 'rcp') {
    const v = el.value.replace(/[^A-Za-z0-9_]/g, '');
    S.rcp = v ? '@' + v : ''; el.value = S.rcp; updateBar();
  } else if (el.id === 'note') {
    S.note = el.value.slice(0, 128);
  } else if (el.id === 'cq') {
    const v = el.value.replace(/\D/g, '').slice(0, 7);
    S.qty = v; el.value = v ? fmt(v) : '';
    const q = qtyVal(), r = $('#cqRange'), cu = S.data.custom;
    if (r) r.textContent = q ? money(customPrice(q)) : tr('custom_range', {lo: fmt(cu.min), hi: fmt(cu.max)});
    updateBar();
  }
});

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
  const d = S.data, u = d.user, isO = S.hist === 'orders', st = u.stats || {orders: 0, spent: 0, stars: 0};
  const rows = isO ? d.orders.map(o => { const c = ORDER_ST[o.status] ?? '', l = TR[S.lang].hasOwnProperty('o_' + o.status) ? tr('o_' + o.status) : o.status;
      return `<div class="row"><div class="l"><b>${esc(o.title)}</b><small>#${o.id} · ${when(o.created_at)}</small></div>
      <div class="r"><b>${money(o.price)}</b><br><span class="st ${c}">${l}</span></div></div>`; })
    : d.topups.map(t => { const c = TOPUP_ST[t.status] ?? '', l = TR[S.lang].hasOwnProperty('t_' + t.status) ? tr('t_' + t.status) : t.status;
      return `<div class="row"><div class="l"><b>+${money(t.amount)}</b><small>${t.method === 'humo' ? 'Humo' : 'Uzcard'} · ${when(t.created_at)}</small></div>
      <div class="r"><span class="st ${c}">${l}</span></div></div>`; });
  const letter = ((u.name || u.username || 'S')[0] || 'S').toUpperCase();
  const photo = tg?.initDataUnsafe?.user?.photo_url;
  const jd = u.joined ? new Date(u.joined) : null, pad = n => String(n).padStart(2, '0');
  const joined = jd ? `${pad(jd.getDate())}.${pad(jd.getMonth() + 1)}.${jd.getFullYear()}` : '—';
  $('#view').innerHTML = `<div class="pf-top">
      <div class="pf-ava">${photo ? `<img id="pfImg" src="${esc(photo)}" alt="" referrerpolicy="no-referrer">` : `<span>${esc(letter)}</span>`}</div>
      <h2 class="pf-name">${esc(u.name || '')}</h2>
      ${u.username ? `<div class="pf-un">@${esc(u.username)}</div>` : ''}
      <button class="pf-id" data-act="copy" data-v="${u.id}">ID: ${u.id}<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/></svg></button></div>
    <div class="pf-bal"><div><small>${tr('your_balance')}</small><b>${money(u.balance)}</b></div>
      <button class="pf-plus" data-act="goto" data-tab="topup">+ ${tr('topup_btn')}</button></div>
    <div class="pf-stats">
      <div class="pf-st"><i>🛒</i><b>${fmt(st.orders)}</b><span>${tr('prof_orders')}</span></div>
      <div class="pf-st"><i>💰</i><b>${money(st.spent)}</b><span>${tr('prof_spent')}</span></div>
      <div class="pf-st"><i>⭐</i><b>${fmt(st.stars)}</b><span>${tr('prof_stars')}</span></div>
      <div class="pf-st"><i>📅</i><b>${joined}</b><span>${tr('prof_joined')}</span></div></div>
    <div class="pf-rows">
      <button class="pf-row" data-act="langsheet"><i>🌐</i><span class="pf-rt"><b>${tr('language')}</b><small>${tr('prof_lang_sub')}</small></span>
        <em>${S.lang === 'ru' ? '🇷🇺 Русский' : "🇺🇿 O'zbekcha"}</em><u>›</u></button>
      <button class="pf-row" data-act="support"><i>🧑‍💻</i><span class="pf-rt"><b>${tr('prof_support')}</b><small>${tr('prof_support_sub')}</small></span><u>›</u></button></div>
    <h3 class="sec">${tr('prof_hist')}</h3>
    <div class="seg" style="--n:2;--i:${isO ? 0 : 1}"><button class="${isO ? 'on' : ''}" data-act="hist" data-k="orders">${tr('orders')}</button>
      <button class="${!isO ? 'on' : ''}" data-act="hist" data-k="topups">${tr('topups')}</button></div>
    <div class="list">${rows.join('') || `<div class="empty">${isO ? tr('no_orders') : tr('no_topups')}</div>`}</div>`;
  $('#pfImg')?.addEventListener('error', e => { const s = document.createElement('span'); s.textContent = letter; e.target.replaceWith(s); });
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
    case 'cat': S.cat = d.k; return renderShop();
    case 'pk': { if (!S.data.toggles[S.cat]) return errorSheet('service_disabled'); S.sel[S.cat] = {id: +d.id, custom: false}; return refreshList(); }
    case 'cust': { if (!S.data.toggles[S.cat]) return errorSheet('service_disabled'); S.sel[S.cat] = {id: null, custom: true}; refreshList(); $('#cq')?.focus(); return; }
    case 'self': {
      const un = S.data.user.username;
      if (!un) return toast(tr('e_no_username'));
      S.rcp = '@' + un; const r = $('#rcp'); if (r) r.value = S.rcp; return updateBar();
    }
    case 'go': return openConfirm();
    case 'buy': return buy(el);
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
    case 'langsheet': return sheet(`<div class="big-em">🌐</div><h3>${tr('pick_title')}</h3>
      <button class="btn ${S.lang === 'ru' ? 'ghost' : ''}" data-act="setlang" data-k="uz">🇺🇿 O'zbekcha</button>
      <button class="btn ${S.lang === 'ru' ? '' : 'ghost'}" style="margin-top:10px" data-act="setlang" data-k="ru">🇷🇺 Русский</button>
      <button class="btn ghost" style="margin-top:10px" data-act="close">${tr('close')}</button>`);
    case 'setlang': {                                // profildan tilni almashtirish
      closeSheet();
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

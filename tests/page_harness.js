// Runs the page's real inline script in Node against a live server, with stubbed DOM and chart
// libraries, and drives it like a player would (clicks, keys, orders). Catches runtime errors in
// rendering and message handling without a browser. Needs Node 22+ (global WebSocket).
//   node tests/page_harness.js static/index.html 127.0.0.1:8000
// The server must be freshly started (paused, untouched account). Exits 1 if any check fails.
const fs = require('fs');
const vm = require('vm');

const elements = {};
function makeEl(id) {
  const el = {
    id, textContent: '', className: '', value: '', disabled: false, title: '', dataset: {}, step: '1', min: '1',
    _html: '', children: [], parent: null, lastElementChild: null, _first: { textContent: '' },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    get firstElementChild() { return this.children[0] || this._first; },
    insertAdjacentHTML(_, html) { this._html = html + this._html; },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
    remove() { if (this.parent) this.parent.removeChild(this); },
    addEventListener() {},
    focus() { document.activeElement = this; },
    blur() { if (document.activeElement === this) document.activeElement = null; },
    select() { this.selected = true; },
    closest() { return null; },
    getContext() { return {}; },
    classList: {
      set: new Set(),
      add(...c) { c.forEach(x => this.set.add(x)); }, remove(...c) { c.forEach(x => this.set.delete(x)); },
      toggle(c, on) { on ? this.set.add(c) : this.set.delete(c); },
      contains(c) { return this.set.has(c); },
    },
  };
  return el;
}
const docListeners = {};
const document = {
  activeElement: null,
  getElementById: (id) => (elements[id] ||= makeEl(id)),
  addEventListener: (type, fn) => (docListeners[type] ||= []).push(fn),
  createElement: () => makeEl('dynamic'),
};
elements['order-type'] = Object.assign(makeEl('order-type'), { value: 'MARKET' });
elements['trade-amount'] = Object.assign(makeEl('trade-amount'), { value: '1' });
['news-modal', 'end-game-modal'].forEach(id => { elements[id] = makeEl(id); elements[id].classList.add('hidden'); });

const chartCalls = { setData: 0, update: 0, lastTime: 0, errors: [] };
const series = {
  setData(d) {
    chartCalls.setData++;
    for (let i = 1; i < d.length; i++) if (d[i].time <= d[i - 1].time) chartCalls.errors.push('setData not ascending');
    chartCalls.lastTime = d.length ? d[d.length - 1].time : 0;
  },
  update(c) {
    chartCalls.update++;
    if (c.time < chartCalls.lastTime) chartCalls.errors.push(`update older than last bar ${c.time} < ${chartCalls.lastTime}`);
    chartCalls.lastTime = c.time;
  },
  priceScale: () => ({ applyOptions() {} }),
};
const LightweightCharts = {
  createChart: () => ({ addSeries: () => series, priceScale: () => ({ applyOptions() {} }) }),
  CandlestickSeries: {}, HistogramSeries: {}, CrosshairMode: { Normal: 0 },
};
let chartsMade = 0;
class Chart { constructor() { chartsMade++; } destroy() {} }

const errors = [];
const ctx = {
  document, LightweightCharts, Chart, console,
  location: { protocol: 'http:', host: process.argv[3] },
  WebSocket, setTimeout, clearTimeout, confirm: () => true,
  requestAnimationFrame: (f) => setTimeout(f, 0),
  localStorage: { getItem: () => null, setItem() {} },
};
ctx.window = ctx;
vm.createContext(ctx);
process.on('uncaughtException', (e) => errors.push(e.stack));

const original = 'ws.onmessage = (event) => handleMessage(JSON.parse(event.data));';
const html = fs.readFileSync(process.argv[2], 'utf8');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];  // skips <script src=...> libraries
let src = inline[inline.length - 1][1];
if (!src.includes(original)) throw new Error('onmessage hook not found');
src = src.replace(original,
  'ws.onmessage = (event) => { try { handleMessage(JSON.parse(event.data)); } catch (e) { __errors.push(e.stack); } };');
ctx.__errors = errors;
vm.runInContext(src, ctx);

const run = (code) => vm.runInContext(code, ctx);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const el = (id) => elements[id];
const toastTexts = () => el('toasts').children.map(c => c.textContent);
// Focus contexts for synthetic key events: page body, a generic text field, a trade number field, a <select>.
const BODY = { closest: () => null };
const TEXT = { closest: (sel) => (sel.startsWith('input') ? {} : null) };
const TRADE = { closest: (sel) => (sel.startsWith('input') || sel.startsWith('#trade-amount') ? {} : null) };
const SELECT = { closest: (sel) => (sel === 'select' ? {} : null) };
function key(type, opts = {}) {
  let prevented = false;
  const event = { code: 'Space', key: ' ', repeat: false, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false,
                  target: BODY, preventDefault: () => { prevented = true; }, ...opts };
  (docListeners[type] || []).forEach(fn => fn(event));
  return prevented;
}

(async () => {
  await wait(800);
  const results = [];
  const check = (cond, label) => results.push(`${cond ? 'PASS' : 'FAIL'} ${label}`);
  check(run('state.connected') && run('state.symbols.length') === 8, 'connected and got snapshot');
  check(el('btn-play-pause').title === 'Play (Space)' && el('status-pill').textContent === 'Paused', 'paused, Space hint on the play button');
  check(el('cash-display').textContent === '$10,000.00', `cash rendered ${el('cash-display').textContent}`);
  check(el('portfolio-list').innerHTML.includes('No positions yet') && el('portfolio-summary').innerHTML === '', 'empty portfolio state');
  check(el('trade-amount-label').textContent === 'Shares' && el('trade-available').textContent === 'Available cash: $10,000.00',
        `share asset: label and availability (${el('trade-available').textContent})`);

  // Space key
  check(key('keydown') === true, 'Space keydown is consumed (no scroll, no button click)');
  await wait(400);
  check(el('status-pill').textContent === 'Live', 'Space starts the market');
  check(key('keydown', { repeat: true }) === true && run('state.running') === true, 'held Space does not re-toggle');
  check(key('keydown', { target: TEXT }) === false, 'Space in a text field is left alone');
  check(key('keydown', { target: SELECT }) === false, 'Space on the order-type dropdown is left alone');
  check(key('keyup') === true, 'Space keyup is consumed too');
  await wait(1800);
  check(chartCalls.update > 0 && el('trade-tape').innerHTML.includes('@ $'), 'chart and tape update while live');

  run('executeTrade()');  // BUY 1 TCHN market
  await wait(400);
  check(el('order-status').textContent.startsWith('Bought 1 TCHN at avg'), `order status: ${el('order-status').textContent}`);
  check(toastTexts().some(t => /^▲ Bought 1 TCHN @ \$[\d,.]+$/.test(t)), `fill toast shown (${toastTexts()})`);
  check(el('portfolio-list').innerHTML.includes('data-symbol="TCHN"') && el('portfolio-list').innerHTML.includes('1 share'),
        'portfolio card for TCHN');
  check(/^Value \$[\d,.]+ · Cost \$[\d,.]+ · Unrealized/.test(el('portfolio-summary').innerHTML.replace(/<[^>]+>/g, '')),
        `portfolio summary (${el('portfolio-summary').innerHTML.replace(/<[^>]+>/g, '')})`);
  check(/^[+-]\$[\d,.]+ \([+-][\d.]+%\)$/.test(el('pf-pl-TCHN').textContent), `P/L updates in place (${el('pf-pl-TCHN').textContent})`);
  await wait(3600);
  check(toastTexts().length === 0, 'toast dismisses itself');

  el('order-type').value = 'LIMIT';
  run('toggleLimitInput()');
  el('limit-price').value = '1';
  run('updateOrderPreview()');
  check(el('preview-avg-label').textContent === 'Limit Price (or better)' && el('preview-total-container').firstElementChild.textContent === 'Max Total Cost',
        'limit buy preview labels are worst-case');
  run('executeTrade()');
  await wait(300);
  check(el('limit-order-list').innerHTML.includes('data-order-id') && toastTexts().length === 0, 'resting limit order: listed, no fill toast');
  check(el('reserved-display').textContent === '$6.00 reserved by orders', `reserved cash shown (${el('reserved-display').textContent})`);
  el('order-type').value = 'MARKET';
  run('toggleLimitInput()');

  // Fractional crypto
  run("switchTab('CRYPTO')");
  check(run('state.selectedSymbol') === 'BTC' && el('trade-amount-label').textContent === 'Quantity (BTC)'
        && el('trade-amount').value === '0.01' && el('trade-amount').step === 0.0001, `BTC: quantity label, step, default (${el('trade-amount').value})`);
  await wait(400);
  el('trade-amount').value = '1';
  run('updateOrderPreview()');
  check(el('preview-warning').textContent.startsWith('More than your available cash'), `over-cash warning (${el('preview-warning').textContent})`);
  el('trade-amount').value = '0.00005';
  run('updateOrderPreview()');
  check(el('preview-warning').textContent === 'Quantity must be in steps of 0.0001 BTC.', 'off-step quantity warning');
  run('executeTrade()');
  check(el('order-status').textContent === 'Enter a quantity in steps of 0.0001 BTC.', 'off-step quantity not sent');
  el('trade-amount').value = '0.0123';
  run('executeTrade()');
  await wait(400);
  check(el('order-status').textContent.startsWith('Bought 0.0123 BTC at avg'), `fractional buy (${el('order-status').textContent})`);
  check(toastTexts().some(t => t.startsWith('▲ Bought 0.0123 BTC @ $')), `fractional fill toast (${toastTexts()})`);
  check(el('portfolio-list').innerHTML.includes('0.0123 BTC'), 'portfolio shows 0.0123 BTC');
  run("setTradeMode('SELL')");
  run('fillMax()');
  check(el('trade-amount').value === '0.0123' && el('trade-available').textContent === 'Available to sell: 0.0123 BTC',
        `Max on sell fills the holding (${el('trade-amount').value}; ${el('trade-available').textContent})`);
  check(el('book-bids').innerHTML.includes('$') && !/>\d+\.\d{5,}</.test(el('book-bids').innerHTML), 'book sizes formatted to the step');
  run("setTradeMode('BUY')");

  // --- Shortcuts: 1-5, `, Tab, N ---
  const press = (k, code, opts = {}) => key('keydown', { key: k, code, ...opts });
  check(press('1', 'Digit1') && run('state.currentTab') === 'STOCK' && run('state.selectedSymbol') === 'TCHN', '1 -> Stocks');
  check(press('5', 'Digit5') && run('state.selectedSymbol') === 'US10Y', '5 -> Bonds');
  check(press('3', 'Digit3') && run('state.selectedSymbol') === 'BTC', '3 -> Crypto');
  check(!press('2', 'Digit2', { target: TRADE }) && run('state.currentTab') === 'CRYPTO', 'digits type normally in the quantity field');
  check(!press('2', 'Digit2', { ctrlKey: true }) && run('state.currentTab') === 'CRYPTO', 'Ctrl+2 left to the browser');
  check(!press('6', 'Digit6') && !press('!', 'Digit1', { shiftKey: true }), 'only 1-5 are tab keys');

  check(run('state.tradeMode') === 'BUY' && press('`', 'Backquote') && run('state.tradeMode') === 'SELL'
        && el('btn-execute-trade').textContent === 'Execute SELL', '` switches to sell');
  check(press('`', 'Backquote', { target: TRADE }) && run('state.tradeMode') === 'BUY', '` works from the quantity field too');

  document.activeElement = null;
  el('trade-amount').selected = false;
  check(press('Tab', 'Tab') && document.activeElement === el('trade-amount') && el('trade-amount').selected, 'Tab focuses quantity with the value selected');
  check(press('Tab', 'Tab', { target: TRADE }) && document.activeElement === el('trade-amount'), 'market order: Tab stays on quantity');
  el('order-type').value = 'LIMIT';
  run('toggleLimitInput()');
  el('limit-price').selected = false;
  check(press('Tab', 'Tab', { target: TRADE }) && document.activeElement === el('limit-price') && el('limit-price').selected, 'limit order: Tab -> limit price, selected');
  check(press('Tab', 'Tab', { target: TRADE }) && document.activeElement === el('trade-amount'), 'Tab cycles back to quantity');
  check(press('Tab', 'Tab', { target: TRADE, shiftKey: true }) && document.activeElement === el('limit-price'), 'Shift+Tab cycles backwards');
  el('order-type').value = 'MARKET';
  run('toggleLimitInput()');

  // Esc: back to "normal mode"
  el('trade-amount').focus();
  check(press('Escape', 'Escape', { target: TRADE }) && document.activeElement === null, 'Esc leaves the quantity field');
  check(press('2', 'Digit2') && run('state.currentTab') === 'ETF', 'after Esc, digits switch tabs again');
  check(!press('Escape', 'Escape'), 'Esc outside a trade field is left alone');
  press('3', 'Digit3');  // back to BTC for the checks below
  // Backslash: market <-> limit
  check(press('\\', 'Backslash') && el('order-type').value === 'LIMIT' && !el('limit-price-container').classList.contains('hidden'),
        'backslash switches to limit');
  el('limit-price').focus();
  el('trade-amount').selected = false;
  check(press('\\', 'Backslash', { target: TRADE }) && el('order-type').value === 'MARKET'
        && el('limit-price-container').classList.contains('hidden') && document.activeElement === el('trade-amount')
        && el('trade-amount').selected, 'backslash back to market moves focus from the hidden limit field to quantity');
  check(!press('\\', 'Backslash', { target: TEXT }) && el('order-type').value === 'MARKET', 'backslash in a text field is left alone');
  document.activeElement = null;

  el('order-status').textContent = '';
  check(press('Enter', 'Enter', { shiftKey: true }), 'Shift+Enter is consumed');
  await wait(400);
  check(el('order-status').textContent.startsWith('Bought 0.01 BTC at avg'), `Shift+Enter executes the order (${el('order-status').textContent})`);
  el('order-status').textContent = '';
  check(press('Enter', 'Enter', { shiftKey: true, repeat: true, target: TRADE }), 'held Shift+Enter is consumed from the quantity field');
  check(!press('Enter', 'Enter') && !press('Enter', 'Enter', { shiftKey: true, target: TEXT }), 'plain Enter and text fields are left alone');
  await wait(400);
  check(el('order-status').textContent === '', 'held / plain Enter sent no order');
  check(press('n', 'KeyN') && el('news-modal').classList.contains('hidden'), 'N with no headlines yet does nothing');
  const consumed = key('keydown', { target: TRADE });
  await wait(300);
  check(consumed && run('state.running') === false, 'Space works from the quantity field (pauses)');
  key('keydown', { target: TRADE });
  await wait(300);

  // News modal: N toggles, and blocks everything else
  const entry = `{id:1, headline:'Exchange Hacked', body:'B', target:'CRYPTO', impact:'CRASH', clock:'Day 2 - 10:00 AM', active:true}`;
  run(`handleMessage({type:'NEWS', news:${entry}, news_log:[${entry}]})`);
  check(press('N', 'KeyN', { shiftKey: true }) && el('news-modal').classList.contains('flex'), 'Shift+N opens the live headline');
  await wait(300);
  check(run('state.running') === false, 'news popup pauses');
  check(!press('4', 'Digit4') && run('state.currentTab') === 'CRYPTO' && !press('Tab', 'Tab') && !press('`', 'Backquote')
        && !press('Enter', 'Enter', { shiftKey: true }) && !press('\\', 'Backslash') && !press('Escape', 'Escape', { target: TRADE }),
        'other shortcuts wait while the news is open');
  check(press('n', 'KeyN') && el('news-modal').classList.contains('hidden'), 'N closes the news');
  await wait(300);
  check(run('state.running') === true, 'closing with N resumes');
  const ended = entry.replace('active:true', 'active:false');
  run(`handleMessage({type:'NEWS', news:null, news_log:[${ended}]})`);
  check(press('n', 'KeyN') && el('news-modal-meta').textContent.endsWith('Ended'), 'N with no live news opens the latest headline');
  press('n', 'KeyN');
  await wait(300);
  check(!press('n', 'KeyN', { target: TEXT }), 'N typed into a text field is left alone');

  // News modal blocks Space
  run(`handleMessage({type:'NEWS', news:${entry}, news_log:[${entry}]})`);
  run('openNewsModal()');
  await wait(300);
  check(run('state.running') === false, 'news modal pauses');
  check(key('keydown') === false && run('state.running') === false, 'Space ignored while a dialog is open');
  run('closeNewsModal()');
  await wait(300);
  check(run('state.running') === true, 'closing the modal resumes');

  run('fastForward()');
  await wait(400);
  check(chartsMade === 1 && el('end-game-modal').classList.contains('flex') && el('status-pill').textContent === 'Week over', 'end report shown');
  check(el('limit-order-list').innerHTML.includes('No pending orders'), 'week end cleared the resting order');
  run('newGame()');
  await wait(600);
  check(el('end-game-modal').classList.contains('hidden') && el('cash-display').textContent === '$10,000.00' && run('state.running'), 'play again resets');

  check(chartCalls.errors.length === 0, `chart data ordering ${chartCalls.errors.slice(0, 3).join('; ')}`);
  check(errors.length === 0, `no runtime errors\n${errors.join('\n')}`);
  console.log(results.join('\n'));
  const passed = results.every((r) => r.startsWith('PASS'));
  console.log(passed ? '\nALL PASSED' : '\nSOME FAILED');
  process.exit(passed ? 0 : 1);
})();

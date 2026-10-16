/* Portfolio Watch Desk: live dashboard client. Talks to the watcher over SSE + a small JSON API. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (x) => typeof x === "number" && isFinite(x);
  const money = (n, d = 2) => !num(n) ? "—" : (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const smoney = (n, d = 2) => !num(n) ? "—" : (n > 0 ? "+" : "") + money(n, d);
  const pct = (n, d = 2) => !num(n) ? "—" : (n > 0 ? "+" : "") + n.toFixed(d) + "%";
  const fx = (n, d = 2) => !num(n) ? "—" : n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const dir = (n) => !num(n) ? "flat" : n > 0.0001 ? "up" : n < -0.0001 ? "down" : "flat";
  const labelCls = (l) => ({ "Strong buy": "up", "Buy": "up", "Hold": "", "Reduce": "warn", "Sell": "down" }[l] ?? "");
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const ago = (t) => { if (!t) return "—"; const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + "m ago" : Math.round(s / 3600) + "h ago"; };
  const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };

  const ui = {
    snap: null, news: [], sel: store.get("wd-sel", null), tf: "1d", bb: store.get("wd-bb", true), marks: store.get("wd-marks", true),
    mine: false, prev: {}, loading: false, chartKey: null, connected: false,
  };

  // ------------------------------------------------------------ live connection
  function connect() {
    const es = new EventSource("api/stream");
    es.addEventListener("state", (e) => { ui.connected = true; renderState(JSON.parse(e.data)); });
    es.addEventListener("news", (e) => { ui.news = JSON.parse(e.data); renderNews(); });
    es.addEventListener("alerts", (e) => onAlerts(JSON.parse(e.data)));
    es.onerror = () => { ui.connected = false; setPill("bad", "Reconnecting…"); };
  }
  function setPill(cls, text) { const p = $("live-pill"); p.className = "pill " + cls; p.innerHTML = '<span class="dot"></span>' + esc(text); }

  setInterval(() => { if (ui.snap) renderStatus(ui.snap.status); }, 1000);

  function renderStatus(st) {
    if (!ui.connected) return;
    const age = Date.now() / 1000 - (st.last_tick || 0);
    const errs = Object.keys(st.errors || {}).length;
    if (!st.last_tick) setPill("stale", "Waiting for first prices");
    else if (age > st.interval * 3 + 20) setPill("bad", "No update for " + ago(st.last_tick).replace(" ago", ""));
    else setPill(errs ? "stale" : "ok", `Live · every ${Math.round(st.interval)}s${errs ? ` · ${errs} symbol${errs > 1 ? "s" : ""} failing` : ""}`);
    $("live-pill").title = errs ? Object.entries(st.errors).map(([k, v]) => k + ": " + v).join("\n") : `Provider: ${st.provider}`;
    const names = { open: "US market open", pre: "Pre-market", post: "After hours", closed: "US market closed" };
    const sp = $("session-pill"); sp.textContent = names[st.session] || st.session; sp.className = "pill" + (st.session === "open" ? " ok" : "");
    $("updated-pill").textContent = "Updated " + ago(st.last_tick);
  }

  function renderState(snap) {
    ui.snap = snap;
    renderStatus(snap.status);
    renderTape(snap.tape);
    renderPortfolio(snap.portfolio);
    renderWatch(snap.watchlist);
    renderAlertList(snap.alerts);
    const syms = snap.portfolio.rows.map((r) => r.symbol).concat(snap.watchlist.map((w) => w.symbol));
    if (!ui.sel || !syms.includes(ui.sel)) ui.sel = syms[0] || null;
    if (ui.sel) loadInstrument(false);
    renderNews();
  }

  function flash(el, key, price) {
    const p = ui.prev[key];
    if (num(p) && num(price) && p !== price) { el.classList.remove("flash-up", "flash-down"); void el.offsetWidth; el.classList.add(price > p ? "flash-up" : "flash-down"); }
    ui.prev[key] = price;
  }

  function renderTape(tape) {
    const row = $("tape");
    row.innerHTML = tape.map((t) => {
      const isYield = t.symbol === "^TNX";
      const v = !num(t.price) ? "—" : isYield ? fx(t.price, 2) + "%" : t.price > 1000 ? fx(t.price, 0) : fx(t.price, 2);
      return `<div class="tick" data-k="tape:${esc(t.symbol)}"><span class="lbl">${esc(t.label)}</span><span class="val">${v}</span><span class="chg ${dir(t.change_pct)}">${num(t.change_pct) ? (t.change_pct > 0 ? "▲ " : t.change_pct < 0 ? "▼ " : "") + pct(t.change_pct) : "&nbsp;"}</span></div>`;
    }).join("");
    row.querySelectorAll(".tick").forEach((el, i) => flash(el, el.dataset.k, tape[i].price));
  }

  function scoreCell(score, label) {
    if (!num(score)) return '<span class="flat">—</span>';
    const w = Math.abs(score) / 2, left = score >= 0 ? 50 : 50 - w;
    const color = score >= 20 ? "var(--up)" : score <= -20 ? "var(--down)" : "var(--warn)";
    return `<span class="score"><span class="bar"><i style="left:${left}%;width:${w}%;background:${color}"></i></span><span class="chip ${labelCls(label)}">${esc(label)} ${score > 0 ? "+" : ""}${Math.round(score)}</span></span>`;
  }

  function renderPortfolio(p) {
    $("kpis").innerHTML = `
      <div class="kpi"><span class="eyebrow">Total value</span><span class="v">${money(p.total)}</span><span class="s flat">${money(p.cash, 0)} cash</span></div>
      <div class="kpi"><span class="eyebrow">Today</span><span class="v ${dir(p.day_change)}">${smoney(p.day_change)}</span><span class="s ${dir(p.day_change)}">${pct(p.day_change_pct)}</span></div>
      <div class="kpi"><span class="eyebrow">Total P&amp;L</span><span class="v ${dir(p.pnl)}">${smoney(p.pnl)}</span><span class="s ${dir(p.pnl)}">${pct(p.basis ? p.pnl / p.basis * 100 : 0)}</span></div>
      <div class="kpi"><span class="eyebrow">Invested</span><span class="v">${money(p.invested)}</span><span class="s flat">cost ${money(p.basis, 0)}</span></div>`;
    const tb = $("rows");
    if (!p.rows.length) { tb.innerHTML = `<tr><td colspan="8" class="txt flat" style="padding:20px 12px">No holdings yet. Choose <b>Edit portfolio</b> to add your positions.</td></tr>`; return; }
    tb.innerHTML = p.rows.map((r) => `<tr data-sym="${esc(r.symbol)}" class="${r.symbol === ui.sel ? "sel" : ""}" tabindex="0">
      <td><span class="tk">${esc(r.symbol)}</span><span class="nm">${esc(r.error ? "⚠ " + r.error : r.name || `${fx(r.shares, 0)} sh @ ${money(r.cost)}`)}</span></td>
      <td class="px">${money(r.price)}${num(r.ext_price) ? `<br><small class="flat" title="Extended-hours price">ext ${money(r.ext_price)}</small>` : ""}</td>
      <td class="${dir(r.change_pct)}">${pct(r.change_pct)}<br><small>${smoney(r.day_change, 0)}</small></td>
      <td>${money(r.value, 0)}</td>
      <td class="${dir(r.pnl)}">${smoney(r.pnl, 0)}<br><small>${pct(r.pnl_pct, 1)}</small></td>
      <td>${num(r.weight) ? r.weight.toFixed(1) + "%" : "—"}</td>
      <td>${scoreCell(r.score, r.label)}</td>
      <td class="txt">${r.pattern ? `<span class="chip ${r.pattern_dir === "bullish" ? "up" : "down"}">${esc(r.pattern)}</span>` : '<span class="flat">—</span>'}</td>
    </tr>`).join("");
    tb.querySelectorAll("tr").forEach((tr, i) => flash(tr.querySelector(".px"), "pf:" + p.rows[i].symbol, p.rows[i].price));
  }

  function renderWatch(list) {
    const tb = $("watch");
    tb.innerHTML = list.length ? list.map((w) => `<tr data-sym="${esc(w.symbol)}" class="${w.symbol === ui.sel ? "sel" : ""}" tabindex="0">
      <td><span class="tk">${esc(w.symbol)}</span><span class="nm">${esc(w.error ? "⚠ " + w.error : w.name)}</span></td>
      <td class="px">${money(w.price)}</td><td class="${dir(w.change_pct)}">${pct(w.change_pct)}</td><td>${scoreCell(w.score, w.label)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="txt flat" style="padding:14px 12px">Add symbols to your watchlist to analyze them before you buy.</td></tr>`;
    tb.querySelectorAll("tr[data-sym]").forEach((tr, i) => flash(tr.querySelector(".px"), "w:" + list[i].symbol, list[i].price));
  }

  function selectFromRow(e) {
    const tr = e.target.closest("tr[data-sym]"); if (!tr) return;
    if (e.type === "keydown" && e.key !== "Enter") return;
    ui.sel = tr.dataset.sym; store.set("wd-sel", ui.sel); ui.chartKey = null;
    document.querySelectorAll("tr[data-sym]").forEach((x) => x.classList.toggle("sel", x.dataset.sym === ui.sel));
    loadInstrument(true);
    if (window.innerWidth < 1040) $("inst").scrollIntoView({ behavior: "smooth" });
  }
  ["rows", "watch"].forEach((id) => { $(id).addEventListener("click", selectFromRow); $(id).addEventListener("keydown", selectFromRow); });

  // ------------------------------------------------------------ alerts
  const sevCls = { critical: "critical", warn: "warn", info: "info" };
  function alertItem(a) {
    const when = new Date(a.time * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    return `<article class="item ${sevCls[a.severity] || ""}"><span class="stripe"></span><div>
      <div class="meta"><span class="chip ${a.severity === "critical" ? "down" : a.severity === "warn" ? "warn" : "acc"}">${esc(a.severity)}</span><span>${esc(a.kind)}</span><span>·</span><span class="num">${when}</span></div>
      <h3>${esc(a.title)}</h3><p>${esc(a.body)}</p>${a.data && a.data.link ? `<p><a href="${esc(a.data.link)}" target="_blank" rel="noopener">Read the story ↗</a></p>` : ""}</div></article>`;
  }
  function renderAlertList(list) {
    $("alerts").innerHTML = list.length ? list.map(alertItem).join("") : `<div class="empty">No alerts yet. The watcher checks every few seconds while the market is open.</div>`;
    $("alert-sub").textContent = list.length ? `${list.length} recent · newest first` : "Stops, targets, patterns, signal changes, big moves, news";
  }
  function onAlerts(list) {
    list.forEach((a) => {
      toast(a);
      if (store.get("wd-notify", false) && "Notification" in window && Notification.permission === "granted") {
        try { new Notification(a.title, { body: a.body, tag: a.key }); } catch {}
      }
    });
  }
  function toast(a) {
    const el = document.createElement("div");
    el.className = "toast " + (a.severity || "");
    el.innerHTML = `<b>${esc(a.title)}</b>${esc(a.body)}`;
    $("toasts").prepend(el);
    setTimeout(() => el.remove(), 9000);
    while ($("toasts").children.length > 4) $("toasts").lastChild.remove();
  }
  function renderNotifyBtn() {
    const on = store.get("wd-notify", false) && "Notification" in window && Notification.permission === "granted";
    $("notify-btn").textContent = on ? "Desktop alerts on" : "Turn on desktop alerts";
    $("notify-btn").setAttribute("aria-pressed", String(on));
  }
  $("notify-btn").addEventListener("click", async () => {
    if (!("Notification" in window)) { toast({ title: "Desktop alerts aren't supported", body: "This browser can't show notifications. Alerts still appear on this page.", severity: "warn" }); return; }
    if (store.get("wd-notify", false) && Notification.permission === "granted") { store.set("wd-notify", false); renderNotifyBtn(); return; }
    const p = await Notification.requestPermission();
    store.set("wd-notify", p === "granted");
    if (p !== "granted") toast({ title: "Desktop alerts are blocked", body: "Allow notifications for this site in your browser settings to get them.", severity: "warn" });
    renderNotifyBtn();
  });
  renderNotifyBtn();

  // ------------------------------------------------------------ news
  function renderNews() {
    const held = new Set((ui.snap?.portfolio.rows || []).map((r) => r.symbol).concat((ui.snap?.watchlist || []).map((w) => w.symbol)));
    const list = ui.news.filter((n) => !ui.mine || (n.symbols || []).some((s) => held.has(s)));
    $("news-sub").textContent = ui.news.length ? `${ui.news.length} headlines · ${ui.news.filter((n) => (n.symbols || []).some((s) => held.has(s))).length} about your symbols` : "Market-moving headlines, scored for sentiment and tagged by theme";
    $("news").innerHTML = list.length ? list.map((n) => newsItem(n, held)).join("") : `<div class="empty">${ui.news.length ? "No headlines match." : "Headlines load within a minute of starting."}</div>`;
  }
  function newsItem(n, held) {
    const s = n.sentiment || 0;
    const when = n.time ? new Date(n.time * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
    return `<article class="item ${s > 0 ? "pos" : s < 0 ? "neg" : ""}"><span class="stripe"></span><div>
      <div class="meta"><span class="chip ${s > 0 ? "up" : s < 0 ? "down" : ""}">${s > 0 ? "Positive" : s < 0 ? "Negative" : "Neutral"} ${s ? (s > 0 ? "+" : "") + s : ""}</span>
      ${(n.symbols || []).map((x) => `<span class="chip ${held && held.has(x) ? "acc" : ""}">${esc(x)}</span>`).join("")}
      ${(n.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}<span>${esc(n.source)}</span><span class="num">${when}</span></div>
      <h3>${n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title)}</h3>${n.summary ? `<p>${esc(n.summary)}</p>` : ""}</div></article>`;
  }
  $("mine-btn").addEventListener("click", () => { ui.mine = !ui.mine; $("mine-btn").setAttribute("aria-pressed", String(ui.mine)); renderNews(); });

  // ------------------------------------------------------------ chart
  let chart = null, rsiChart = null, S = {};
  const hasLib = typeof window.LightweightCharts !== "undefined";
  function chartOpts(height) {
    return {
      height, autoSize: true,
      layout: { background: { type: "solid", color: css("--surface") }, textColor: css("--muted"), fontFamily: css("--font-num") || "monospace", fontSize: 11 },
      grid: { vertLines: { color: css("--chart-grid") }, horzLines: { color: css("--chart-grid") } },
      rightPriceScale: { borderColor: css("--line") },
      timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t, type) => { const d = new Date(t * 1000); return type >= 3 ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString([], { month: "short", day: "numeric" }); } },
      localization: { timeFormatter: (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) },
      crosshair: { mode: 1 },
    };
  }
  function buildChart() {
    if (!hasLib || chart) return;
    $("chart").innerHTML = "";
    chart = LightweightCharts.createChart($("chart"), chartOpts(440));
    S.candle = chart.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down") });
    S.vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const line = (color, width = 1.5, style = 0) => chart.addLineSeries({ color, lineWidth: width, lineStyle: style, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    S.sma20 = line(css("--sma20")); S.sma50 = line(css("--sma50")); S.sma200 = line(css("--sma200"), 2);
    S.bbU = line(css("--band"), 1, 2); S.bbL = line(css("--band"), 1, 2); S.vwap = line(css("--sma20"), 2, 1);
    rsiChart = LightweightCharts.createChart($("rsi-chart"), chartOpts(110));
    S.rsi = rsiChart.addLineSeries({ color: css("--accent"), lineWidth: 1.5, priceLineVisible: false });
    S.rsi.createPriceLine({ price: 70, color: css("--down"), lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "70" });
    S.rsi.createPriceLine({ price: 30, color: css("--up"), lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "30" });
    let syncing = false;
    const sync = (from, to) => from.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (syncing || !r) return; syncing = true; to.timeScale().setVisibleLogicalRange(r); syncing = false; });
    sync(chart, rsiChart); sync(rsiChart, chart);
  }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!chart) return; chart.remove(); rsiChart.remove(); chart = rsiChart = null; S = {}; ui.chartKey = null; buildChart(); loadInstrument(false);
  });

  const smaArr = (v, n) => v.map((_, i) => i < n - 1 ? null : v.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n);
  function bands(v, n = 20, k = 2) {
    const m = smaArr(v, n);
    return m.map((mu, i) => { if (mu == null) return [null, null]; const w = v.slice(i - n + 1, i + 1); const sd = Math.sqrt(w.reduce((a, x) => a + (x - mu) ** 2, 0) / n); return [mu + k * sd, mu - k * sd]; });
  }
  function rsiArr(v, n = 14) {
    const out = v.map(() => null); if (v.length <= n) return out;
    let g = 0, l = 0;
    for (let i = 1; i <= n; i++) { const d = v[i] - v[i - 1]; g += Math.max(d, 0); l += Math.max(-d, 0); }
    g /= n; l /= n; out[n] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
    for (let i = n + 1; i < v.length; i++) { const d = v[i] - v[i - 1]; g = (g * (n - 1) + Math.max(d, 0)) / n; l = (l * (n - 1) + Math.max(-d, 0)) / n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); }
    return out;
  }
  const pts = (cs, vals) => cs.map((c, i) => vals[i] == null ? null : { time: c.t, value: vals[i] }).filter(Boolean);

  function drawChart(data) {
    if (!hasLib) { $("chart").innerHTML = '<div class="chart-msg">The chart library failed to load. Check that web/vendor is present.</div>'; return; }
    buildChart();
    const seen = new Set();
    const cs = data.candles.filter((c) => !seen.has(c.t) && seen.add(c.t)).sort((a, b) => a.t - b.t);
    if (!cs.length) { S.candle.setData([]); [S.vol, S.sma20, S.sma50, S.sma200, S.bbU, S.bbL, S.vwap, S.rsi].forEach((s) => s.setData([])); return; }
    const closes = cs.map((c) => c.c);
    S.candle.setData(cs.map((c) => ({ time: c.t, open: c.o, high: c.h, low: c.l, close: c.c })));
    const up = css("--up"), dn = css("--down");
    S.vol.setData(cs.map((c) => ({ time: c.t, value: c.v, color: (c.c >= c.o ? up : dn) + "55" })));
    const daily = data.tf === "1d";
    S.sma20.setData(daily ? pts(cs, smaArr(closes, 20)) : []);
    S.sma50.setData(daily ? pts(cs, smaArr(closes, 50)) : []);
    S.sma200.setData(daily ? pts(cs, smaArr(closes, 200)) : []);
    const b = bands(closes);
    S.bbU.setData(ui.bb ? pts(cs, b.map((x) => x[0])) : []); S.bbL.setData(ui.bb ? pts(cs, b.map((x) => x[1])) : []);
    if (!daily) { let pv = 0, vv = 0; S.vwap.setData(cs.map((c) => { pv += (c.h + c.l + c.c) / 3 * c.v; vv += c.v; return vv ? { time: c.t, value: pv / vv } : null; }).filter(Boolean)); } else S.vwap.setData([]);
    S.rsi.setData(pts(cs, rsiArr(closes)));
    S.candle.setMarkers(ui.marks && daily ? (data.markers || []).map((m) => ({
      time: m.t, position: m.direction === "bullish" ? "belowBar" : "aboveBar", shape: m.direction === "bullish" ? "arrowUp" : "arrowDown",
      color: m.direction === "bullish" ? up : dn, text: m.strength >= 3 && m.t >= cs[Math.max(0, cs.length - 40)].t ? m.name : "",
    })).sort((a, b2) => a.time - b2.time) : []);
    $("legend").innerHTML = daily
      ? `<span><i style="background:${css("--sma20")}"></i>SMA 20</span><span><i style="background:${css("--sma50")}"></i>SMA 50</span><span><i style="background:${css("--sma200")}"></i>SMA 200</span>${ui.bb ? `<span><i style="background:${css("--band")}"></i>Bollinger 20,2</span>` : ""}<span>RSI 14 below</span>`
      : `<span><i style="background:${css("--sma20")}"></i>VWAP</span>${ui.bb ? `<span><i style="background:${css("--band")}"></i>Bollinger 20,2</span>` : ""}<span>RSI 14 below</span>`;
    const key = data.symbol + ":" + data.tf;
    if (ui.chartKey !== key) {
      ui.chartKey = key;
      const n = cs.length;
      const range = daily ? { from: Math.max(0, n - 160), to: n + 3 } : { from: 0, to: n + 3 };
      chart.timeScale().setVisibleLogicalRange(range);
    }
  }

  $("tf-seg").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return; ui.tf = b.dataset.tf; ui.chartKey = null;
    [...$("tf-seg").children].forEach((x) => x.setAttribute("aria-pressed", String(x === b))); loadInstrument(true);
  });
  $("bb-btn").setAttribute("aria-pressed", String(ui.bb));
  $("mk-btn").setAttribute("aria-pressed", String(ui.marks));
  $("bb-btn").addEventListener("click", () => { ui.bb = !ui.bb; store.set("wd-bb", ui.bb); $("bb-btn").setAttribute("aria-pressed", String(ui.bb)); loadInstrument(false); });
  $("mk-btn").addEventListener("click", () => { ui.marks = !ui.marks; store.set("wd-marks", ui.marks); $("mk-btn").setAttribute("aria-pressed", String(ui.marks)); loadInstrument(false); });

  // ------------------------------------------------------------ instrument panels
  async function getJSON(url) { const r = await fetch(url, { cache: "no-store" }); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || r.statusText); return d; }

  async function loadInstrument(reset) {
    const sym = ui.sel; if (!sym || ui.loading) return;
    ui.loading = true;
    try {
      const [an, cd] = await Promise.all([getJSON("api/analysis?symbol=" + encodeURIComponent(sym)).catch((e) => ({ error: e.message })),
                                          getJSON(`api/candles?symbol=${encodeURIComponent(sym)}&tf=${ui.tf}`).catch(() => null)]);
      if (sym !== ui.sel) return;
      if (cd) drawChart(cd);
      renderInstrument(sym, an);
    } finally { ui.loading = false; }
  }

  function kv(items) {
    return items.map(([k, v, n]) => `<div><span class="k">${esc(k)}</span><span class="v">${v}</span>${n ? `<span class="n">${esc(n)}</span>` : ""}</div>`).join("");
  }

  function renderInstrument(sym, data) {
    $("i-sym").textContent = sym;
    if (data.error || !data.analysis) {
      $("i-px").textContent = ""; $("i-chg").textContent = ""; $("i-name").textContent = data.error || "Loading…";
      ["sugg", "comps", "pats", "inds", "levels", "pivfib", "stats", "bt", "i-news"].forEach((id) => ($(id).innerHTML = ""));
      return;
    }
    const a = data.analysis, q = data.quote || {};
    $("i-px").textContent = money(q.price ?? a.latest?.price);
    $("i-chg").className = "num " + dir(q.change_pct); $("i-chg").textContent = num(q.change_pct) ? `${smoney(q.change)} (${pct(q.change_pct)})` : "";
    $("i-name").textContent = q.name || "";
    const ext = $("i-ext"); ext.hidden = !num(q.ext_price); if (num(q.ext_price)) ext.textContent = `Extended hours ${money(q.ext_price)} (${pct(q.ext_change_pct)})`;
    $("i-time").textContent = q.time ? "Last trade " + new Date(q.time * 1000).toLocaleTimeString() : "";
    if (!a.ok) { $("v-label").textContent = "Not enough data"; $("sugg").innerHTML = `<div>${esc(a.error)}</div>`; return; }

    $("v-label").textContent = a.label; $("v-label").className = "big " + (labelCls(a.label) === "warn" ? "" : labelCls(a.label));
    $("v-score").textContent = (a.score > 0 ? "+" : "") + a.score.toFixed(0) + " / 100";
    $("v-conf").textContent = `${a.confidence.toFixed(0)}% of evidence agrees`;
    $("v-needle").style.left = (a.score + 100) / 2 + "%";

    const actCls = (x) => /exit|cut|trim|protect|avoid/i.test(x) ? "down" : /take|buy|add|trail/i.test(x) ? "up" : /pattern|evidence/i.test(x) ? "acc" : "";
    $("sugg").innerHTML = (a.suggestions || []).map((s) => `<div><b class="chip ${actCls(s.action)}">${esc(s.action)}</b>${esc(s.text)}</div>`).join("") || "<div>No suggestions.</div>";
    $("comps").innerHTML = a.components.slice().sort((x, y) => Math.abs(y.points) - Math.abs(x.points)).map((c) =>
      `<div class="comp"><span class="pts ${dir(c.points)}">${c.points > 0 ? "+" : ""}${c.points.toFixed(0)}</span><span class="why"><span class="grp">${esc(c.group)}</span>${esc(c.reason)}</span></div>`).join("");

    $("pats").innerHTML = a.patterns.length ? a.patterns.map((p) => {
      const tr = p.track_record;
      const rec = tr && tr.count ? `<span class="n">Track record here: ${tr.hit_rate.toFixed(0)}% right over ${tr.horizon} days · ${tr.count} cases${tr.count < 10 ? " (small sample)" : ""}</span>` : "";
      const when = a.last_index - p.index;
      return `<div class="item ${p.direction === "bullish" ? "pos" : p.direction === "bearish" ? "neg" : ""}" style="padding:8px 0;border:0"><span class="stripe"></span><div>
        <div class="meta"><span class="chip ${p.direction === "bullish" ? "up" : p.direction === "bearish" ? "down" : ""}">${esc(p.direction)}</span><span>${"●".repeat(p.strength)}${"○".repeat(3 - p.strength)}</span><span>${when === 0 ? (ui.snap?.status.session === "open" ? "today (bar still forming)" : "today") : when + " bar" + (when > 1 ? "s" : "") + " ago"}</span></div>
        <h3>${esc(p.name)}</h3><p>${esc(p.meaning)}</p>${rec}</div></div>`;
    }).join("") : '<p class="flat" style="margin:0">No candlestick patterns in the last 3 daily bars.</p>';

    const L = a.latest;
    $("inds").innerHTML = kv([
      ["RSI 14", fx(L.rsi14, 1), L.rsi14 >= 70 ? "Overbought" : L.rsi14 <= 30 ? "Oversold" : ""],
      ["MACD", fx(L.macd, 2), `signal ${fx(L.macd_signal, 2)} · hist ${fx(L.macd_hist, 2)}`],
      ["Stochastic %K/%D", `${fx(L.stoch_k, 0)} / ${fx(L.stoch_d, 0)}`],
      ["ADX", fx(L.adx, 0), `+DI ${fx(L.plus_di, 0)} · −DI ${fx(L.minus_di, 0)}`],
      ["Bollinger %B", fx(L.bb_pctb, 2), `width ${fx(L.bb_width_pct, 1)}%`],
      ["ATR 14", money(L.atr14), `${fx(L.atr_pct, 2)}% of price`],
      ["SMA 20 / 50", `${money(L.sma20, 0)} / ${money(L.sma50, 0)}`],
      ["SMA 200", money(L.sma200)],
      ["Volume vs avg", num(L.volume_avg20) && L.volume_avg20 ? (L.volume / L.volume_avg20).toFixed(2) + "×" : "—"],
      ...(a.intraday ? [["VWAP (today)", money(a.intraday.vwap), a.intraday.above_vwap == null ? "" : a.intraday.above_vwap ? "Price above VWAP" : "Price below VWAP"],
                        ["RSI 14 (5-min)", fx(a.intraday.rsi14_5m, 0)]] : []),
    ]);

    const lv = a.levels;
    $("levels").innerHTML = kv([
      ["Resistance", lv.resistance.map((r) => money(r.level)).join(" · ") || "—", "from swing highs"],
      ["Support", lv.support.map((r) => money(r.level)).join(" · ") || "—", "from swing lows"],
      ["ATR stop (2×)", money(lv.atr_stop)], ["Chandelier stop", money(lv.chandelier_stop), "22-day high − 3×ATR"],
      ["Take-profit", money(lv.take_profit)], ["Reward / risk", num(lv.reward_risk) ? lv.reward_risk.toFixed(2) + " : 1" : "—"],
    ]);
    const piv = lv.pivots, fib = lv.fibonacci;
    $("pivfib").innerHTML = `<table class="mini"><thead><tr><th>Pivot</th><th>Level</th><th>Fib (${esc(fib.direction)} swing)</th><th>Level</th></tr></thead><tbody>${
      [["R2", "23.6%"], ["R1", "38.2%"], ["P", "50.0%"], ["S1", "61.8%"], ["S2", "78.6%"]].map(([p, f]) =>
        `<tr><td>${p}</td><td>${money(piv[p])}</td><td>${f}</td><td>${money(fib.levels[f])}</td></tr>`).join("")}</tbody></table>`;

    const st = a.stats, pr = a.probabilities || {};
    $("stats").innerHTML = kv([
      ["Volatility (annual)", fx(st.volatility_annual_pct, 1) + "%", `${fx(st.sigma_daily_pct, 2)}% a day`],
      ["Today's move", num(st.move_today_sigma) ? (st.move_today_sigma > 0 ? "+" : "") + st.move_today_sigma.toFixed(1) + "σ" : "—", "vs normal daily swing"],
      ["Likely range today", st.range_1d_68 ? `${money(st.range_1d_68[0])} – ${money(st.range_1d_68[1])}` : "—", "68% (1σ)"],
      ["5-day range", st.range_5d_95 ? `${money(st.range_5d_95[0])} – ${money(st.range_5d_95[1])}` : "—", "95% (1.96σ√5)"],
      ["Beta vs S&P 500", fx(st.beta, 2)], ["Sharpe (1y)", fx(st.sharpe_1y, 2)],
      ["Max drawdown (1y)", fx(st.max_drawdown_1y_pct, 1) + "%"],
      ["52-week range", `${money(st.low_52w, 0)} – ${money(st.high_52w, 0)}`, `${pct(st.from_high_pct, 1)} from high`],
      ["20-day trend", num(st.trend_slope_20d_pct) ? pct(st.trend_slope_20d_pct, 2) + "/day" : "—", num(st.trend_r2_20d) ? `R² ${st.trend_r2_20d.toFixed(2)}` : ""],
      ...(num(pr.touch_take_profit_20d) ? [["Hit take-profit in 20d", pr.touch_take_profit_20d.toFixed(0) + "%", "random-walk estimate"]] : []),
      ...(num(pr.touch_atr_stop_20d) ? [["Hit ATR stop in 20d", pr.touch_atr_stop_20d.toFixed(0) + "%", "random-walk estimate"]] : []),
      ...(num(pr.touch_your_target_20d) ? [["Hit your target in 20d", pr.touch_your_target_20d.toFixed(0) + "%"]] : []),
      ...(num(pr.touch_your_stop_20d) ? [["Hit your stop in 20d", pr.touch_your_stop_20d.toFixed(0) + "%"]] : []),
    ]);

    const bt = a.backtest?.horizons || {};
    const row = (h, side) => { const x = bt[h]?.[side]; return x && x.count ? `${x.hit_rate.toFixed(0)}% <small class="flat">(${x.count}, ${pct(x.avg_return, 2)})</small>` : "—"; };
    $("bt").innerHTML = Object.keys(bt).length ? `<table class="mini"><thead><tr><th>After</th><th>Buy signals right</th><th>Sell signals right</th><th>Any day</th></tr></thead><tbody>${
      Object.keys(bt).map((h) => `<tr><td>${h} days</td><td>${row(h, "buy")}</td><td>${row(h, "sell")}</td><td>${row(h, "all")}</td></tr>`).join("")}</tbody></table>
      <p class="flat" style="margin:0;font-size:12px">Same scoring rules replayed over ${a.backtest.bars_tested} past days of this stock. A signal only has an edge if it beats the "any day" column.</p>` : '<p class="flat" style="margin:0">Not enough history to replay.</p>';

    $("i-news").innerHTML = (data.news || []).length ? data.news.slice(0, 5).map((n) => newsItem(n, null)).join("") : '<p class="flat" style="margin:0">No recent headlines for this symbol.</p>';
  }

  // ------------------------------------------------------------ portfolio editor
  const dlg = $("editor");
  function edRow(h = {}) {
    const d = document.createElement("div");
    d.className = "ed-row";
    const v = (x) => (x ?? "") === "" ? "" : esc(x);
    d.innerHTML = `<input aria-label="Symbol" name="symbol" value="${v(h.symbol)}" placeholder="NVDA" maxlength="15">
      <input aria-label="Shares" name="shares" type="number" step="any" min="0" value="${v(h.shares)}">
      <input aria-label="Average cost" name="cost" type="number" step="any" min="0" value="${v(h.cost)}">
      <input aria-label="Target" name="target" type="number" step="any" min="0" value="${v(h.target)}" placeholder="optional">
      <input aria-label="Stop" name="stop" type="number" step="any" min="0" value="${v(h.stop)}" placeholder="optional">
      <button class="btn ghost" type="button" aria-label="Remove">Remove</button>`;
    d.querySelector("button").addEventListener("click", () => d.remove());
    $("ed-rows").appendChild(d);
  }
  $("edit-btn").addEventListener("click", async () => {
    $("ed-msg").textContent = "";
    try {
      const p = await getJSON("api/portfolio");
      $("ed-rows").innerHTML = ""; (p.holdings.length ? p.holdings : [{}]).forEach(edRow);
      $("ed-cash").value = p.cash || ""; $("ed-watch").value = p.watchlist.join(", ");
      dlg.showModal();
    } catch (e) { toast({ title: "Couldn't load your portfolio", body: e.message, severity: "warn" }); }
  });
  $("ed-add").addEventListener("click", () => edRow());
  $("ed-close").addEventListener("click", () => dlg.close());
  $("ed-cancel").addEventListener("click", () => dlg.close());
  $("ed-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const holdings = [...$("ed-rows").children].map((r) => Object.fromEntries([...r.querySelectorAll("input")].map((i) => [i.name, i.value.trim()])))
      .filter((h) => h.symbol || h.shares || h.cost).map((h) => ({ ...h, symbol: h.symbol.toUpperCase() }));
    for (const h of holdings) {
      if (!h.symbol) return ($("ed-msg").textContent = "Every holding needs a symbol.");
      if (!(Number(h.shares) > 0)) return ($("ed-msg").textContent = `${h.symbol}: enter how many shares you own.`);
      if (h.cost === "" || Number(h.cost) < 0) return ($("ed-msg").textContent = `${h.symbol}: enter your average cost per share.`);
    }
    const body = { holdings, cash: Number($("ed-cash").value || 0), watchlist: $("ed-watch").value.split(/[\s,]+/).filter(Boolean) };
    $("ed-save").disabled = true;
    try {
      const r = await fetch("api/portfolio", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { $("ed-msg").textContent = d.error || "Couldn't save."; return; }
      dlg.close(); toast({ title: "Portfolio saved", body: "Fetching prices and re-running the analysis now.", severity: "info" });
    } catch (err) { $("ed-msg").textContent = "Couldn't reach the watcher: " + err.message; }
    finally { $("ed-save").disabled = false; }
  });

  connect();
})();

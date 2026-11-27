'use strict';
(() => {
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
// Everything that comes from data.json is text: escape before it joins markup.
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Only plain https links reach an href; anything else (javascript:, data:, relative tricks) is dropped.
const safeUrl = u => (typeof u === 'string' && /^https:\/\/[A-Za-z0-9.-]+(\/[^\s"'<>]*)?$/.test(u)) ? u : null;
const extLink = (u, label, cls = '') => { const s = safeUrl(u); return s ? `<a class="${cls}" href="${esc(s)}" target="_blank" rel="noopener noreferrer">${label}</a>` : ''; };

const VC = {google:'vg', openai:'vo', anthropic:'va'}, VS = ['google','openai','anthropic'];
const TYPE = {launch:'출시', retire:'지원 중단·퇴역', update:'기타 변경', preview:'프리뷰'};
const KIND = {dated:'changelog', rss:'RSS 피드', links:'뉴스 목록'};
const day = s => new Date(s + 'T00:00:00+09:00');
const today = new Date(new Date().toLocaleDateString('en-CA', {timeZone:'Asia/Seoul'}) + 'T00:00:00+09:00');
const diff = s => Math.round((day(s) - today) / 864e5);
const md = s => s.slice(5).replace('-', '.');
const ago = s => { const d = -diff(s); return d <= 0 ? '오늘' : d + '일 전'; };
const dday = s => { const d = diff(s); return d === 0 ? 'D-day' : 'D-' + d; };
const short = m => m.split(' / ')[0];
const nm = m => short(m).replace(/^(Claude|Gemini) (?=\D)/, '');
const byDate = (a, b) => a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
const ls = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
};

let D, seen = null, firstVisit = false;
const prefs = Object.assign({theme:'light', calm:false, vendors:VS.slice()}, ls.get('fmr-prefs', {}));
if (!Array.isArray(prefs.vendors)) prefs.vendors = VS.slice();
prefs.vendors = prefs.vendors.filter(v => VS.includes(v));
let view = 'dash', co = '', gIdx = 0, bIdx = 0, bAll = false, tAll = false, nAll = false;
const nf = {r:'all', v:'', t:'', q:''};

const isNew = e => !seen.includes(e.id);
const want = e => prefs.vendors.includes(e.vendor);
const src = k => (k && D.sources[k]) ? D.sources[k] : null;
const unread = () => D.events.filter(e => want(e) && isNew(e));
const stTag = e => e.status === 'verified' ? '<span class="tg ok">공식 확인</span>' : e.status === 'auto' ? '<span class="tg auto">자동 수집</span>' : '<span class="tg rec">점검 기록</span>';
const badge = e => `<span class="bd${isNew(e) ? ' new' : ''}" data-b="${esc(e.id)}">${isNew(e) ? '신규' : '확인됨'}</span>`;
const flagOf = e => { const m = short(e.model).toLowerCase(); return D.flagships.find(f => f.vendor === e.vendor && (f.model.toLowerCase() === m || m.startsWith(f.model.toLowerCase())) && Math.abs(diff(f.date) - diff(e.date)) <= 3); };
const grow = sel => requestAnimationFrame(() => requestAnimationFrame(() => $$(sel).forEach(f => { f.style.width = f.dataset.w + '%'; })));

/* ---------- preferences ---------- */
function applyPrefs() {
  const dark = prefs.theme === 'dark' || (prefs.theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.ui = dark ? 'dark' : 'light';
  document.documentElement.toggleAttribute('data-calm', !!prefs.calm);
}
function savePrefs() { ls.set('fmr-prefs', prefs); applyPrefs(); }
applyPrefs();

/* ---------- reading ---------- */
function markRead(id) {
  if (!id || seen.includes(id)) return;
  seen.push(id); ls.set('fmr-seen', seen);
  $$(`[data-b="${CSS.escape(id)}"]`).forEach(b => { b.classList.remove('new'); b.textContent = '확인됨'; });
  $$(`.node[data-n="${CSS.escape(id)}"]`).forEach(n => n.classList.remove('unread'));
  renderBadge();
}
function renderBadge() {
  const n = unread().length, b = $('#badge');
  b.textContent = n; b.dataset.n = n;
  $('#navn').textContent = n || ''; $('#tabn').textContent = n || '';
  $('#bell').setAttribute('aria-label', `읽지 않은 소식 ${n}건`);
  if ($('#nf-un')) $('#nf-un').textContent = n;
  if ($('#readall')) $('#readall').disabled = !n;
  return n;
}

/* ---------- one expandable item, used everywhere ---------- */
function item(e, o = {}) {
  const so = src(e.src);
  const rows = [['가격', e.price], ['컨텍스트', e.context], ['제공', e.availability]].filter(r => r[1]);
  return `<details class="it ${VC[e.vendor]}" data-id="${esc(e.id)}"><summary><span>
    <span class="meta">${o.noVendor ? '' : `<span class="vt">${esc(D.vendors[e.vendor].short)}</span>`}${o.noDate ? '' : `<span class="num">${esc(md(e.date))}</span>`}<span class="tg t-${esc(e.type)}">${esc(TYPE[e.type] || e.type)}</span></span>
    <b class="t">${esc(e.title)}<span class="chev" aria-hidden="true">›</span></b><p class="s">${esc(e.summary)}</p></span>${badge(e)}</summary>
    <div class="ex"><div>${stTag(e)} <span class="num" style="color:var(--mute);font-size:13px">${esc(e.date)} · ${esc(ago(e.date))}</span></div>
    ${rows.length ? `<dl>${rows.map(r => `<dt>${r[0]}</dt><dd>${esc(r[1])}</dd>`).join('')}</dl>` : ''}
    <div class="acts">${so ? extLink(so.url, '공식 출처 ↗', 'lnk') : '<span class="note" style="margin:0">이전 점검 기록 (원문 링크 없음)</span>'}${o.coLink ? `<a class="lnk" href="#${e.vendor}">${esc(D.vendors[e.vendor].short)} 페이지 →</a>` : ''}</div></div></details>`;
}
const upRow = u => `<li class="${VC[u.vendor]}"><div class="dd num">${dday(u.date)}<small>${md(u.date)}</small></div><div><b>${esc(u.title)}</b><span>${esc(D.vendors[u.vendor].short)} · ${esc(u.detail)}</span></div></li>`;

/* ---------- glass lens that glides to the selected item ---------- */
function lens(box, el) {
  const l = box && box.querySelector(':scope>.lens'); if (!l) return;
  if (!el || !el.offsetParent) { l.style.opacity = 0; return; }
  const first = !l.dataset.on; l.dataset.on = 1; l.style.opacity = 1;
  if (first) l.style.transition = 'none';
  l.style.width = el.offsetWidth + 'px'; l.style.height = el.offsetHeight + 'px';
  l.style.transform = `translate(${el.offsetLeft}px,${el.offsetTop}px)`;
  if (first) { void l.offsetWidth; l.style.transition = ''; } else { l.classList.remove('squish'); void l.offsetWidth; l.classList.add('squish'); }
}
function syncNav() {
  const key = co || view;
  $$('[data-nav]').forEach(a => {
    const on = a.dataset.nav === key || (co && a.classList.contains('tb') && a.dataset.nav === 'watch');
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  lens($('#side'), $('#side [aria-current]')); lens($('#tabbar'), $('#tabbar [aria-current]'));
}
function countUp(el, to) {
  if (prefs.calm || typeof to !== 'number') { el.textContent = to; return; }
  const t0 = performance.now(), dur = 500;
  const step = t => { const k = Math.min(1, (t - t0) / dur); el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function checkedAgo() {
  const m = /^(\d{4}-\d\d-\d\d) (\d\d):(\d\d)/.exec(D.checked || '');
  if (!m) return D.updated;
  const t = new Date(`${m[1]}T${m[2]}:${m[3]}:00+09:00`), h = Math.round((Date.now() - t) / 36e5);
  return h < 1 ? '방금 확인' : h < 48 ? `${h}시간 전 확인` : `${Math.round(h / 24)}일 전 확인`;
}

/* ---------- dashboard ---------- */
function renderDash() {
  const evs = D.events.filter(want), un = evs.filter(isNew);
  const l30 = evs.filter(e => e.type === 'launch' && diff(e.date) >= -30);
  const ups = D.upcoming.filter(u => diff(u.date) >= 0 && prefs.vendors.includes(u.vendor)).sort((a, b) => a.date < b.date ? -1 : 1);
  const up30 = ups.filter(u => diff(u.date) <= 30);
  const w = D.watch || [], bad = w.filter(s => !s.ok).length;
  $('#d-lead').textContent = `${checkedAgo()} · ${D.schedule || '자동 점검'} · 관심 회사 ${prefs.vendors.length}곳`;
  const cards = [
    ['읽지 않은 소식', un.length, un.length ? '열어 보지 않은 새 출시·변경' : '모두 확인했습니다', un.length ? 'accent' : '', '#news', 'unread'],
    ['최근 30일 출시', l30.length, l30.length ? `가장 최근: ${short(l30.sort(byDate)[0].model)}` : '새 모델 없음', '', '#news', 'launch'],
    ['30일 안 예정 변경', up30.length, ups[0] ? `${dday(ups[0].date)} · ${ups[0].title}` : '예정된 퇴역·가격 변경 없음', '', '#upbox', ''],
    ['추적 상태', bad ? `오류 ${bad}` : '정상', `공식 출처 ${w.length}곳 · ${checkedAgo()}`, bad ? 'warn' : 'good', '#watch', '']
  ];
  $('#stats').innerHTML = cards.map(c => `<a class="stat glass press ${c[3]}" href="${c[4]}" data-pre="${c[5]}"><span>${c[0]}</span><b class="num">${typeof c[1] === 'number' ? 0 : esc(c[1])}</b><small>${esc(c[2])}</small></a>`).join('');
  $$('#stats b').forEach((b, i) => { if (typeof cards[i][1] === 'number') countUp(b, cards[i][1]); });

  const tops = VS.filter(v => prefs.vendors.includes(v)).map(v => D.events.filter(e => e.vendor === v && e.flagship && e.type === 'launch').sort(byDate)[0]).filter(Boolean).sort(byDate);
  $('#feat').innerHTML = tops.map((e, i) => {
    const f = flagOf(e), pair = f && f.pairs ? f.pairs.slice().sort((a, b) => (b[3] - b[2]) - (a[3] - a[2]))[0] : null, dl = f && f.deltas ? f.deltas[0] : null;
    const hl = pair ? `<div class="hl">${esc(pair[0])} <b class="num">${esc(pair[2])}→${esc(pair[3])}%</b> · vs ${esc(nm(f.prev))}</div>` : dl ? `<div class="hl">${esc(dl[0])} <b class="num">${esc(dl[1])}</b> · ${esc(dl[2])}</div>` : '';
    const px = f && f.in != null ? `<div class="px"><span>입력<b class="num">$${esc(f.in)}</b></span><span>출력<b class="num">$${esc(f.out)}</b></span><span>컨텍스트<b class="num" style="font-size:15px;line-height:1.85">${esc(f.ctx)}</b></span></div>` : '';
    return `<a class="fc glass press ${VC[e.vendor]}" href="#${e.vendor}" style="animation-delay:${i * .06}s"><div class="row"><span class="vt">${esc(D.vendors[e.vendor].short)}</span>${badge(e)}</div><h3>${esc(e.model)}</h3><p><span class="num">${esc(md(e.date))}</span> · ${esc(ago(e.date))} · ${esc(e.summary)}</p>${px}${hl}<span class="go">${esc(D.vendors[e.vendor].short)} 자세히 보기 →</span></a>`;
  }).join('') || '<div class="panel glass empty">설정에서 관심 회사를 켜 주세요.</div>';
  const fids = new Set(tops.map(e => e.id));
  $('#recent').innerHTML = evs.filter(e => !fids.has(e.id)).sort(byDate).slice(0, 6).map(e => item(e, {coLink:true})).join('') || '<div class="empty">최근 소식이 없습니다.</div>';
  $('#upd').innerHTML = ups.slice(0, 6).map(upRow).join('') || '<li class="empty">예정된 변경이 없습니다.</li>';
}

/* ---------- watch ---------- */
function renderWatch() {
  $('#tiles').innerHTML = VS.map(v => {
    const evs = D.events.filter(e => e.vendor === v), fl = evs.filter(e => e.flagship).sort(byDate)[0];
    const nx = D.upcoming.filter(u => u.vendor === v && diff(u.date) >= 0).sort((a, b) => a.date < b.date ? -1 : 1)[0];
    const n30 = evs.filter(e => e.type === 'launch' && diff(e.date) >= -30).length;
    return `<a class="tile glass press ${VC[v]}" href="#${v}"><h3>${esc(D.vendors[v].name)}</h3><p>${esc(D.vendors[v].intro || '')}</p>
      <dl><dt>최신 플래그십</dt><dd>${esc(fl ? short(fl.model) : '—')}<small>${fl ? esc(md(fl.date) + ' 출시 · ' + ago(fl.date)) : ''}</small></dd>
      <dt>최근 30일</dt><dd>출시 ${n30}건</dd>
      <dt>다음 예정 변경</dt><dd>${nx ? `${esc(nx.title)}<small>${esc(md(nx.date))} · ${dday(nx.date)} 남음</small>` : '없음'}</dd></dl>
      <span class="go">타임라인·벤치마크 보기 →</span></a>`;
  }).join('');
  const w = D.watch || [];
  $('#w-ok').textContent = `정상 ${w.filter(s => s.ok).length} / ${w.length}`;
  $('#srcs').innerHTML = w.map(s => `<div class="src ${VC[s.vendor]}"><span><b>${esc(s.name)}</b><span class="k"><span class="vt">${esc(D.vendors[s.vendor].short)}</span> · ${esc(KIND[s.kind] || s.kind)}${s.ok ? ` · 항목 ${esc(s.items)}개 읽음` : ''}${s.error ? ` · ${esc(s.error)}` : ''}</span></span>${s.ok ? '<span class="bd new">정상</span>' : '<span class="bd bad">오류</span>'}${extLink(s.url, '열기 ↗')}</div>`).join('') || '<div class="empty">출처 상태는 추적기가 처음 실행된 뒤 표시됩니다.</div>';
}

/* ---------- news (findings + notifications in one place) ---------- */
function renderNews() {
  $$('#nf-r button').forEach(b => b.setAttribute('aria-pressed', b.dataset.nr === nf.r));
  $$('#nf-v button').forEach(b => b.setAttribute('aria-pressed', b.dataset.nv === nf.v));
  setDrop(nf.t);
  const q = nf.q.trim().toLowerCase();
  const list = D.events.filter(e => want(e) && (nf.r === 'all' || isNew(e)) && (!nf.v || e.vendor === nf.v) && (!nf.t || e.type === nf.t) && (!q || (e.model + ' ' + e.title + ' ' + e.summary).toLowerCase().includes(q))).sort(byDate);
  const shown = nAll ? list : list.slice(0, 15); let h = '', m = '';
  shown.forEach(e => { const k = e.date.slice(0, 7); if (k !== m) { m = k; h += `<div class="mh">${+k.slice(0, 4)}년 ${+k.slice(5)}월</div>`; } h += item(e, {coLink:true}); });
  $('#newslist').innerHTML = list.length ? h + (list.length > 15 ? `<button class="more glass press" data-more="news">${nAll ? '접기' : `${list.length}건 모두 보기`}</button>` : '')
    : `<div class="empty">${nf.r === 'unread' && !q && !nf.t ? '읽지 않은 소식이 없습니다. 다음 점검을 기다리는 중이에요.' : '조건에 맞는 소식이 없습니다. 검색어나 필터를 바꿔 보세요.'}</div>`;
  renderBadge();
  requestAnimationFrame(() => { lens($('#nf-r'), $('#nf-r [aria-pressed=true]')); lens($('#nf-v'), $('#nf-v [aria-pressed=true]')); });
}

/* ---------- settings ---------- */
function renderPrefs() {
  $$('#p-theme button').forEach(b => b.setAttribute('aria-pressed', b.dataset.th === prefs.theme));
  requestAnimationFrame(() => lens($('#p-theme'), $('#p-theme [aria-pressed=true]')));
  $('#p-calm').checked = !!prefs.calm;
  $$('[data-pv]').forEach(c => { c.checked = prefs.vendors.includes(c.dataset.pv); });
  const rows = [['마지막 확인', D.checked || D.updated], ['데이터 갱신', D.updated], ['기록', `${D.events.length}건 · 예정 ${D.upcoming.length}건`], ['공식 출처', `${(D.watch || []).length}곳`]];
  $('#p-data').innerHTML = rows.map(r => `<dt>${r[0]}</dt><dd class="num">${esc(r[1])}</dd>`).join('');
}

/* ---------- company page ---------- */
function renderTimeline() {
  const v = co, evs = D.events.filter(e => e.vendor === v).sort(byDate);
  const fut = D.upcoming.filter(u => u.vendor === v && diff(u.date) >= 0).sort((a, b) => a.date < b.date ? 1 : -1);
  const shown = tAll ? evs : evs.slice(0, 10);
  let h = fut.length ? '<li class="mon">예정</li>' : '';
  h += fut.map(u => `<li class="fu"><div class="when num">${esc(md(u.date))}<small>${dday(u.date)}</small></div><span class="node fut"></span><div class="body fut"><b>${esc(u.title)}</b><span>${esc(u.detail)}</span></div></li>`).join('');
  h += `<li class="today"><span class="num">오늘 ${esc(md(today.toLocaleDateString('en-CA', {timeZone:'Asia/Seoul'})))}</span></li>`;
  let m = '';
  shown.forEach(e => {
    const k = e.date.slice(0, 7);
    if (k !== m) { m = k; h += `<li class="mon">${+k.slice(5)}월</li>`; }
    const cls = e.type === 'retire' ? 'ret' : e.flagship ? 'flag' : '';
    h += `<li><div class="when num">${esc(md(e.date))}<small>${esc(ago(e.date))}</small></div><span class="node ${cls}${isNew(e) ? ' unread' : ''}" data-n="${esc(e.id)}"></span>${item(e, {noVendor:true, noDate:true})}</li>`;
  });
  if (evs.length > 10) h += `<li class="mon"><button class="more glass press" data-more="tl">${tAll ? '접기' : `${evs.length}건 모두 보기`}</button></li>`;
  $('#vtl').innerHTML = h;
}
function renderCo(v) {
  const evs = D.events.filter(e => e.vendor === v), fl = evs.filter(e => e.flagship).sort(byDate)[0];
  const ups = D.upcoming.filter(u => u.vendor === v && diff(u.date) >= 0).sort((a, b) => a.date < b.date ? -1 : 1);
  $('#v-co').className = 'view ' + VC[v];
  $('#ch').innerHTML = `<div><h1>${esc(D.vendors[v].name)}</h1><p>${esc(D.vendors[v].intro || '')}. 최신 플래그십은 <b>${esc(fl ? short(fl.model) : '—')}</b>${fl ? ` (${esc(md(fl.date))}, ${esc(ago(fl.date))})` : ''}입니다.</p></div>
    <div class="mini"><div class="glass">30일 출시<b class="num">${evs.filter(e => e.type === 'launch' && diff(e.date) >= -30).length}건</b></div><div class="glass">60일 퇴역 공지<b class="num">${evs.filter(e => e.type === 'retire' && diff(e.date) >= -60).length}건</b></div><div class="glass">다음 예정 변경<b class="num">${ups[0] ? dday(ups[0].date) : '—'}</b></div></div>`;
  tAll = false; renderTimeline();
  const fls = D.flagships.filter(f => f.vendor === v);
  $('#cards').innerHTML = fls.map(f => { const so = src(f.src); return `<article class="card glass"><div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><h3>${esc(f.model)}</h3><span style="font-size:13px;color:var(--mute);white-space:nowrap">${esc(md(f.date))} · ${esc(ago(f.date))}</span></div><div class="px"><span>입력<b class="num">${f.in != null ? '$' + esc(f.in) : '—'}</b></span><span>출력<b class="num">${f.out != null ? '$' + esc(f.out) : '—'}</b></span><span>컨텍스트<b class="num" style="font-size:15px;line-height:1.95">${esc(f.ctx)}</b></span></div><div style="font-size:13px;color:var(--mute)">이전 모델: ${esc(f.prev)}</div><ul>${(f.notes || []).map(t => `<li>${esc(t)}</li>`).join('')}</ul>${so ? extLink(so.url, '공식 발표 ↗') : ''}</article>`; }).join('') || '<div class="card glass empty">등록된 플래그십 정보가 없습니다.</div>';
  const ps = (D.prices || []).filter(p => p[1] === v), mx = Math.max(...ps.map(p => +p[3] || 0), 1);
  $('#price').innerHTML = ps.map(p => `<div class="pr"><span>${esc(nm(p[0]))}</span><div class="t"><span class="o" data-w="${(+p[3] || 0) / mx * 100}"></span><span class="i" data-w="${(+p[2] || 0) / mx * 100}"></span></div><span class="v num">$${esc(p[2])} / $${esc(p[3])}</span></div>`).join('') || '<div class="empty">가격 정보 없음</div>';
  grow('#price [data-w]');
  gIdx = 0; renderGains(fls); bIdx = 0; bAll = false; renderBench();
}
function renderGains(fls) {
  $('#gtabs').innerHTML = fls.length > 1 ? fls.map((f, i) => `<button aria-pressed="${i === gIdx}" data-g="${i}">${esc(nm(f.prev))} → ${esc(nm(f.model))}</button>`).join('') : '';
  const f = fls[gIdx]; if (!f) { $('#gains').innerHTML = '<div class="empty">비교 데이터가 없습니다.</div>'; return; }
  let h = fls.length === 1 ? `<p class="note" style="margin:0 0 8px">${esc(f.prev)} → ${esc(f.model)}</p>` : '';
  if (f.pairs) h += f.pairs.map(p => { const a = +p[2], b = +p[3]; return `<div class="db"><div>${esc(p[0])}<small>${esc(p[1])}</small></div><div class="tr"><span class="bar" style="left:${a}%;width:0"></span><span class="p" style="left:${a}%"></span><span class="n" data-to="${b}" style="left:${a}%"></span></div><div class="d num">${esc(a)} → ${esc(b)}<br><b>${b >= a ? '+' : ''}${(b - a).toFixed(1)}pt</b></div></div>`; }).join('');
  if (f.deltas) h += `<div class="chips">${f.deltas.map(d => `<div class="dchip"><b class="num">${esc(d[1])}</b>${esc(d[0])}<br><span style="color:var(--mute)">${esc(d[2])}</span></div>`).join('')}</div><p class="note">공식 페이지에 절댓값이 텍스트로 없어 발표된 변화량만 표시합니다.</p>`;
  if (!f.pairs && !f.deltas) h = '<div class="empty">발표된 비교 수치가 없습니다.</div>';
  $('#gains').innerHTML = h;
  requestAnimationFrame(() => requestAnimationFrame(() => $$('#gains .db').forEach(r => { const n = r.querySelector('.n'), bar = r.querySelector('.bar'), a = parseFloat(r.querySelector('.p').style.left), to = +n.dataset.to; n.style.left = to + '%'; bar.style.left = Math.min(a, to) + '%'; bar.style.width = Math.abs(to - a) + '%'; })));
}
function renderBench() {
  const tbs = D.benchTables.filter(t => (t.vendor || t.models[0][1]) === co);
  $('#btabs').innerHTML = tbs.length > 1 ? tbs.map((t, i) => `<button aria-pressed="${i === bIdx}" data-bt="${i}">${esc(t.label)}</button>`).join('') : '';
  const t = tbs[bIdx]; if (!t) { $('#bench').innerHTML = '<div class="empty">이 회사가 발표한 벤치마크 표가 아직 없습니다.</div>'; return; }
  const so = src(t.src), rows = bAll ? t.rows : t.rows.slice(0, 6);
  $('#bench').innerHTML = (tbs.length === 1 ? `<p class="note" style="margin:0 0 10px">${esc(t.label)}</p>` : '') + '<div class="bgrid">' + rows.map(r => {
    const vals = r[2].filter(v => v != null).map(Number), mx = Math.max(...vals), mn = Math.min(...vals);
    const pct = v => r[1] === 'Elo' ? 40 + 60 * (v - mn) / ((mx - mn) || 1) : v;
    return `<div class="bt"><h4>${esc(r[0])}<span>${esc(r[1])}</span></h4>${t.models.map((m, i) => { const v = r[2][i]; return `<div class="br ${VC[m[1]] || ''} ${v === mx ? 'lead1' : ''}"><span>${esc(nm(m[0]))}</span>${v == null ? '<span class="na">표에 없음</span>' : `<div class="t"><div class="f num" data-w="${Math.min(100, pct(+v))}">${esc(v)}${r[1] === '%' ? '%' : ''}</div></div>`}</div>`; }).join('')}</div>`;
  }).join('') + '</div>' + (t.rows.length > 6 ? `<button class="more glass press" data-more="bench">${bAll ? '접기' : `벤치마크 ${t.rows.length}개 모두 보기`}</button>` : '') + `<p class="note">${esc(t.note)} ${so ? '출처: ' + extLink(so.url, esc(so.title)) : ''}</p>`;
  grow('#bench .f');
}

/* ---------- router ---------- */
const TITLES = {watch:'감시 항목', news:'소식', prefs:'설정'};
function route() {
  const h = location.hash.slice(1);
  co = VS.includes(h) ? h : '';
  view = co ? 'co' : ['watch', 'news', 'prefs'].includes(h) ? h : 'dash';
  $$('main>.view').forEach(s => { s.hidden = s.id !== 'v-' + view; });
  const t = co ? D.vendors[co].short : TITLES[view];
  document.title = t ? `${t} · 프런티어 모델 레이더` : '프런티어 모델 레이더';
  ({dash:renderDash, watch:renderWatch, news:renderNews, prefs:renderPrefs, co:() => renderCo(co)})[view]();
  syncNav();
}
function toast(msg, delay) {
  setTimeout(() => { const t = document.createElement('div'); t.className = 'toast glass hi'; t.innerHTML = '<i></i><span></span>'; t.lastChild.textContent = msg; $('#toasts').appendChild(t); setTimeout(() => t.remove(), 4200); }, delay);
}

/* ---------- events ---------- */
document.addEventListener('toggle', ev => { const d = ev.target; if (d.matches && d.matches('details.it') && d.open) markRead(d.dataset.id); }, true);
document.addEventListener('click', ev => {
  const t = ev.target.closest('[data-more],[data-nr],[data-nv],[data-th],[data-g],[data-bt],[data-pre]'); if (!t) return;
  if (t.dataset.pre !== undefined) { // dashboard tiles preset the news filter
    if (t.dataset.pre === 'unread') { nf.r = 'unread'; nf.t = ''; } else if (t.dataset.pre === 'launch') { nf.r = 'all'; nf.t = 'launch'; }
    if (t.getAttribute('href') === '#upbox') { ev.preventDefault(); $('#upbox').scrollIntoView({block:'center', behavior:prefs.calm ? 'auto' : 'smooth'}); }
    return;
  }
  if (t.dataset.more === 'bench') { bAll = !bAll; renderBench(); }
  else if (t.dataset.more === 'news') { nAll = !nAll; renderNews(); }
  else if (t.dataset.more === 'tl') { tAll = !tAll; renderTimeline(); }
  else if (t.dataset.nr) { nf.r = t.dataset.nr; nAll = false; renderNews(); }
  else if (t.dataset.nv !== undefined) { nf.v = t.dataset.nv; nAll = false; renderNews(); }
  else if (t.dataset.th) { prefs.theme = t.dataset.th; savePrefs(); renderPrefs(); }
  else if (t.dataset.g !== undefined) { gIdx = +t.dataset.g; renderGains(D.flagships.filter(f => f.vendor === co)); }
  else if (t.dataset.bt !== undefined) { bIdx = +t.dataset.bt; bAll = false; renderBench(); }
});
/* ---------- glass dropdown (listbox) ---------- */
const drop = $('#nf-t'), dbtn = drop.querySelector('.dbtn'), menu = drop.querySelector('.menu'), opts = [...menu.querySelectorAll('[role=option]')];
function setDrop(val) {
  opts.forEach(o => o.setAttribute('aria-selected', o.dataset.val === val));
  const cur = opts.find(o => o.dataset.val === val) || opts[0];
  drop.querySelector('.dlabel').textContent = cur.textContent;
}
function openDrop(focusSel) {
  menu.hidden = false; dbtn.setAttribute('aria-expanded', 'true');
  const cur = menu.querySelector('[aria-selected=true]') || opts[0];
  lens(menu, cur); liquify();
  if (focusSel) cur.focus();
}
function closeDrop(refocus) { if (menu.hidden) return; menu.hidden = true; dbtn.setAttribute('aria-expanded', 'false'); if (refocus) dbtn.focus(); }
function pick(o) { nf.t = o.dataset.val; nAll = false; closeDrop(true); renderNews(); }
dbtn.addEventListener('click', () => menu.hidden ? openDrop(false) : closeDrop(false));
dbtn.addEventListener('keydown', e => { if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openDrop(true); } });
menu.addEventListener('click', e => { const o = e.target.closest('[role=option]'); if (o) pick(o); });
menu.addEventListener('keydown', e => {
  const i = opts.indexOf(document.activeElement);
  if (e.key === 'ArrowDown') { e.preventDefault(); opts[Math.min(opts.length - 1, i + 1)].focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); opts[Math.max(0, i - 1)].focus(); }
  else if (e.key === 'Home') { e.preventDefault(); opts[0].focus(); }
  else if (e.key === 'End') { e.preventDefault(); opts[opts.length - 1].focus(); }
  else if (e.key === 'Escape' || e.key === 'Tab') { closeDrop(e.key === 'Escape'); }
});
menu.addEventListener('focusin', e => { const o = e.target.closest('[role=option]'); if (o) lens(menu, o); });
document.addEventListener('pointerdown', e => { if (!drop.contains(e.target)) closeDrop(false); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrop(true); });

/* ---------- liquid glass: real refraction (Chrome, Edge and other Chromium browsers) ----------
   Chromium can run an SVG filter through backdrop-filter. Each glass gets a displacement map drawn
   for its own size: neutral in the middle, and along the rim it pulls the backdrop from nearer the
   centre, so whatever passes behind the glass bends at the edge like thick glass. The backdrop is
   also lightly blurred and saturated inside the same filter. Other engines keep the CSS frosted glass. */
const LIQUID = !!(navigator.userAgentData && navigator.userAgentData.brands && navigator.userAgentData.brands.some(b => /Chromium/.test(b.brand)))
  && !matchMedia('(prefers-reduced-transparency: reduce)').matches;
const SVGNS = 'http://www.w3.org/2000/svg';
const filters = new Map(), watched = new WeakSet();
let defs = null, lqQueued = 0;
function edgeMap(w, h, r, band) {
  const k = .5, W = Math.max(4, Math.round(w * k)), H = Math.max(4, Math.round(h * k)), R = Math.min(r * k, W / 2, H / 2), B = band * k;
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const ctx = c.getContext('2d'), img = ctx.createImageData(W, H), d = img.data;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const px = x + .5 - W / 2, py = y + .5 - H / 2, qx = Math.abs(px) - (W / 2 - R), qy = Math.abs(py) - (H / 2 - R);
    const ox = Math.max(qx, 0), oy = Math.max(qy, 0), out = Math.hypot(ox, oy);
    const depth = R - out - Math.min(Math.max(qx, qy), 0); // distance in from the rounded rim
    let dx = 0, dy = 0;
    if (depth >= 0 && depth < B) {
      let nx, ny; // outward normal of the rim
      if (qx > 0 && qy > 0) { nx = ox / out * Math.sign(px); ny = oy / out * Math.sign(py); }
      else if (qx > qy) { nx = Math.sign(px); ny = 0; } else { nx = 0; ny = Math.sign(py); }
      const t = 1 - depth / B, m = t * t * (3 - 2 * t); // smooth, strongest right at the rim
      dx = -nx * m; dy = -ny * m;
    }
    const i = (y * W + x) * 4; d[i] = 128 + dx * 127; d[i + 1] = 128 + dy * 127; d[i + 2] = 128; d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL('image/png');
}
function el(name, attrs) { const n = document.createElementNS(SVGNS, name); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; }
function filterFor(w, h, r, soft) {
  const key = `${w}x${h}r${r}b${soft}`;
  if (filters.has(key)) return filters.get(key);
  if (!defs || filters.size > 160) { // start a fresh set if sizes have piled up
    if (defs) defs.parentNode.remove();
    filters.clear();
    const svg = el('svg', {width:0, height:0, 'aria-hidden':'true', focusable:'false'}); svg.style.position = 'absolute';
    defs = el('defs', {}); svg.appendChild(defs); document.body.appendChild(svg);
  }
  const id = 'lg' + Math.random().toString(36).slice(2, 8), band = Math.min(30, Math.min(w, h) * .32), scale = Math.round(Math.min(48, band * 1.6));
  const f = el('filter', {id, x:0, y:0, width:w, height:h, filterUnits:'userSpaceOnUse', primitiveUnits:'userSpaceOnUse', 'color-interpolation-filters':'sRGB'});
  f.append(
    el('feGaussianBlur', {in:'SourceGraphic', stdDeviation:soft, result:'soft'}),
    el('feImage', {href:edgeMap(w, h, r, band), x:0, y:0, width:w, height:h, preserveAspectRatio:'none', result:'map'}),
    el('feDisplacementMap', {in:'soft', in2:'map', scale, xChannelSelector:'R', yChannelSelector:'G', result:'bent'}),
    el('feColorMatrix', {in:'bent', type:'saturate', values:1.5})
  );
  defs.appendChild(f); filters.set(key, id);
  return id;
}
const gro = new ResizeObserver(() => queueLiquid());
function liquify() {
  if (!LIQUID) return;
  for (const g of $$('.glass')) {
    if (!watched.has(g)) { watched.add(g); gro.observe(g); }
    if (!g.getClientRects().length) continue;
    const w = Math.round(g.offsetWidth), h = Math.round(g.offsetHeight);
    if (!w || !h || w * h > 520000) { // very large panels keep the plain frosted glass
      if (g.dataset.lg) { g.style.removeProperty('backdrop-filter'); g.style.removeProperty('-webkit-backdrop-filter'); delete g.dataset.lg; }
      continue;
    }
    const r = Math.round(Math.min(parseFloat(getComputedStyle(g).borderTopLeftRadius) || 0, w / 2, h / 2));
    const soft = g.matches('.menu,.toast') ? 10 : 3; // menus and toasts sit over text: keep them more frosted
    const key = `${w}x${h}r${r}b${soft}`;
    if (g.dataset.lg === key) continue;
    const id = filterFor(w, h, r, soft);
    g.style.setProperty('backdrop-filter', `url(#${id})`); g.style.setProperty('-webkit-backdrop-filter', `url(#${id})`);
    g.dataset.lg = key;
  }
}
function queueLiquid() { if (!lqQueued) lqQueued = requestAnimationFrame(() => { lqQueued = 0; liquify(); }); }
if (LIQUID) {
  document.documentElement.classList.add('liquid');
  new MutationObserver(queueLiquid).observe(document.querySelector('main'), {childList:true, subtree:true});
  new MutationObserver(queueLiquid).observe($('#toasts'), {childList:true});
}
$('#nf-q').addEventListener('input', e => { nf.q = e.target.value.slice(0, 60); nAll = false; renderNews(); });
$('#p-calm').addEventListener('change', e => { prefs.calm = e.target.checked; savePrefs(); });
$$('[data-pv]').forEach(c => c.addEventListener('change', () => { const v = c.dataset.pv; prefs.vendors = c.checked ? [...new Set([...prefs.vendors, v])] : prefs.vendors.filter(x => x !== v); savePrefs(); renderBadge(); }));
$('#p-reset').addEventListener('click', () => { seen = D.events.filter(e => diff(e.date) < -10).map(e => e.id); ls.set('fmr-seen', seen); renderBadge(); toast('읽음 기록을 초기화했습니다', 0); });
$('#readall').addEventListener('click', () => { seen = [...new Set([...seen, ...D.events.filter(want).map(e => e.id)])]; ls.set('fmr-seen', seen); renderNews(); toast('모두 읽음으로 표시했습니다', 0); });
const mq = matchMedia('(prefers-color-scheme: dark)');
if (mq.addEventListener) mq.addEventListener('change', () => { if (prefs.theme === 'auto') applyPrefs(); });
window.addEventListener('hashchange', () => { closeDrop(false); route(); window.scrollTo(0, 0); });
let raf = 0;
document.addEventListener('pointermove', ev => {
  if (raf || prefs.calm) return;
  raf = requestAnimationFrame(() => { raf = 0; const g = ev.target.closest && ev.target.closest('.glass'); if (!g) return; const r = g.getBoundingClientRect(); g.style.setProperty('--mx', (ev.clientX - r.left) + 'px'); g.style.setProperty('--my', (ev.clientY - r.top) + 'px'); });
}, {passive:true});
const ro = new ResizeObserver(() => syncNav());

/* ---------- boot ---------- */
fetch('data.json', {cache:'no-store', credentials:'same-origin'}).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(d => {
  if (!d || !Array.isArray(d.events)) throw new Error('형식 오류');
  D = d;
  seen = ls.get('fmr-seen', null);
  if (!Array.isArray(seen)) { firstVisit = true; seen = D.events.filter(e => diff(e.date) < -10).map(e => e.id); ls.set('fmr-seen', seen); }
  seen = seen.filter(x => typeof x === 'string');
  $('#chk').textContent = checkedAgo();
  $('#sidestat').textContent = `${D.schedule || '자동 점검'} · ${checkedAgo()}`;
  const n = renderBadge();
  route(); ro.observe(document.body); liquify();
  if (n) toast(`${firstVisit ? '최근 10일' : '읽지 않은'} 소식 ${n}건`, 700);
}).catch(err => { $('#d-lead').textContent = '데이터를 불러오지 못했습니다 (' + String(err.message).slice(0, 40) + '). 잠시 후 새로고침해 주세요.'; });
})();

/* مافيا — عميل اللعبة */
const CODE = decodeURIComponent(location.pathname.split('/')[2] || '').toUpperCase();
const KEY = 'mafia:' + CODE;
const $ = s => document.querySelector(s);
const app = $('#app');

let sess = null;
try { sess = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { sess = null; }
$('#code').textContent = CODE || '····';

if (!sess) location.href = '/?code=' + CODE;

let S = null;          // آخر حالة
let sel = null;        // الاختيار المحلي
let selPhase = '';     // الطور الذي تم فيه الاختيار
let revealed = false;  // هل كشف اللاعب بطاقته
let lastSpoken = '';
let draft = '';
let phaseTotal = null;
let soundOn = false;
let VOICE = {};
const voiceReady = fetch('/api/voice').then(r => r.json())
  .then(j => { VOICE = j.clips || {}; }).catch(() => { VOICE = {}; });

const ROLE_EMO = { killer: '🔪', doctor: '🩺', detective: '🕵️', citizen: '🧑' };
const ROLE_DESC = {
  killer: 'تقتلون شخصاً كل ليلة بالاتفاق بينكما. هدفكم: أن تتساووا عدداً مع الباقين.',
  doctor: 'كل ليلة تحمي شخصاً واحداً — بما فيهم نفسك — من محاولة القتل.',
  detective: 'كل ليلة تستفسر عن شخص واحد، فيخبرك النظام: قاتل أو ليس قاتلاً.',
  citizen: 'لا قدرة خاصة لديك. سلاحك هو النقاش والتصويت الصائب في النهار.'
};
const TAG = { killer: 'k', doctor: 'd', detective: 'i', citizen: 'c' };

/* ------------------------------------------------ شبكة */
async function act(body) {
  const r = await fetch('/api/action', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ code: CODE, pid: sess.pid, token: sess.token }, body))
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) showErr(j.error || 'خطأ');
  else hideErr();
  return j;
}
function showErr(m) { $('#err').textContent = m; $('#err').classList.remove('hidden'); }
function hideErr() { $('#err').classList.add('hidden'); }

async function poll() {
  let v = 0;
  for (;;) {
    try {
      const r = await fetch(`/api/state?code=${CODE}&pid=${sess.pid}&token=${sess.token}&v=${v}`);
      if (r.status === 403 || r.status === 404) {
        localStorage.removeItem(KEY);
        location.href = '/?code=' + CODE;
        return;
      }
      const st = await r.json();
      if (st.error) { showErr(st.error); await sleep(1500); continue; }
      v = st.v;
      apply(st);
    } catch (e) {
      await sleep(1200);
    }
  }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ------------------------------------------------ الصوت */
function speak(text) {
  if (!soundOn || !text || !window.speechSynthesis) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    const ar = speechSynthesis.getVoices().find(v => (v.lang || '').toLowerCase().startsWith('ar'));
    if (ar) u.voice = ar;
    u.lang = 'ar-SA'; u.rate = 0.95; u.pitch = 1;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  } catch (e) { /* تجاهل */ }
}
function playClip(file) {
  return new Promise(res => {
    const a = new Audio('/static/voice/' + encodeURIComponent(file));
    a.onended = res; a.onerror = res;
    a.play().catch(res);
  });
}
async function narrate(ids, text) {
  if (!soundOn) return;
  await voiceReady;
  if (ids && ids.length && ids.every(i => VOICE[i])) {
    if (window.speechSynthesis) speechSynthesis.cancel();
    for (const id of ids) await playClip(VOICE[id]);   // تسجيلك أنت
    return;
  }
  speak(text);                                          // البديل: الصوت الآلي
}

$('#sound').onclick = () => {
  soundOn = !soundOn;
  $('#sound').textContent = soundOn ? '🔊 الصوت' : '🔇 الصوت';
  if (soundOn) speak('تم تشغيل صوت الراوي.');
  else if (window.speechSynthesis) speechSynthesis.cancel();
};

/* ------------------------------------------------ الحالة */
let skew = 0;
function apply(st) {
  if (!S || S.phase !== st.phase) {
    sel = null;
    phaseTotal = st.deadline ? Math.max(1, st.deadline - st.now) : null;
  }
  if (st.phase === 'lobby') revealed = false;
  S = st;
  skew = Date.now() / 1000 - st.now;
  if (st.narrationId !== lastSpoken && (st.narration || (st.voice || []).length)) {
    lastSpoken = st.narrationId;
    narrate(st.voice || [], st.narration);
  }
  render();
}

function remain() {
  if (!S || !S.deadline) return null;
  return Math.max(0, S.deadline - (Date.now() / 1000 - skew));
}
function fmt(s) {
  s = Math.ceil(s);
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}
setInterval(() => {
  const bar = document.getElementById('tbar'), num = document.getElementById('tnum');
  if (!bar || !S) return;
  const left = remain();
  if (left === null) return;
  const total = +bar.dataset.total || 1;
  bar.style.width = Math.max(0, Math.min(100, left / total * 100)) + '%';
  if (num) num.textContent = fmt(left);
}, 500);

/* ------------------------------------------------ عناصر */
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function narration() {
  if (!S.narration) return '';
  const left = remain();
  const total = phaseTotal || Math.max(left || 1, 1);
  let t = '';
  if (left !== null) {
    t = `<div class="timer"><i id="tbar" data-total="${total}" style="width:100%"></i></div>
         <div class="tnum" id="tnum">${fmt(left)}</div>`;
  }
  return `<div class="narr"><div class="ico">📢</div><div class="grow"><p>${esc(S.narration)}</p>${t}</div></div>`;
}

function playerList(opts) {
  opts = opts || {};
  const rows = S.players.map(p => {
    const cls = ['pl'];
    if (!p.alive) cls.push('dead');
    const can = opts.pick && p.alive && !(opts.exclude || []).includes(p.id);
    if (can) cls.push('pick');
    if (sel === p.id) cls.push('sel');
    let tag = '';
    if (p.roleAr) tag = `<span class="tag ${TAG[p.role]}">${p.roleAr}</span>`;
    else if (p.ally) tag = '<span class="tag k">شريكك</span>';
    else if (opts.tally && opts.tally[p.id]) tag = `<span class="vcount">${opts.tally[p.id]}</span>`;
    else if (S.phase === 'reveal' && p.ready) tag = '<span class="tag d">جاهز</span>';
    else if (p.isHost && S.phase === 'lobby') tag = '<span class="tag i">المضيف</span>';
    let meta = '';
    if (!p.alive) meta = '<span class="meta">خارج اللعبة</span>';
    else if (opts.voters && opts.voters[p.id]) meta = `<span class="meta">${esc(opts.voters[p.id].join('، '))}</span>`;
    else if (opts.blocked && opts.blocked.includes(p.id)) meta = '<span class="meta">لا يمكن حمايته الآن</span>';
    const dis = opts.blocked && opts.blocked.includes(p.id) ? ' data-blocked="1"' : '';
    return `<button class="${cls.join(' ')}"${can ? ` data-pick="${p.id}"` : ' disabled'}${dis}>
      <span class="av">${p.alive ? (p.isYou ? '⭐' : '🙂') : '💀'}</span>
      <span class="grow">${esc(p.name)}${p.isYou ? ' <small style="color:var(--dim)">(أنت)</small>' : ''}${meta}</span>
      ${tag}</button>`;
  }).join('');
  return `<div class="grid">${rows}</div>`;
}

function nightScreen(emo, title, sub) {
  return `<div class="card night"><div class="emo">${emo}</div>
    <h2 style="margin-top:12px">${esc(title)}</h2>
    <p class="muted">${esc(sub || '')}</p></div>`;
}

function logBox() {
  if (!S.log.length) return '';
  return `<div class="card"><h3>سجل الأحداث</h3><div class="log">` +
    S.log.slice().reverse().map(l => `<div>الليلة ${l.day}: ${esc(l.text)}</div>`).join('') + `</div></div>`;
}

function confirmBar(label, disabled) {
  return `<div class="row" style="margin-top:12px">
    <button class="grow" style="width:100%" data-confirm="1"${(!sel || disabled) ? ' disabled' : ''}>${label}</button></div>`;
}

/* ------------------------------------------------ العرض */
function render() {
  const you = S.you;
  let h = '';

  if (S.phase === 'lobby') {
    const link = location.origin + '/?code=' + S.code;
    const canShare = !!(navigator.share);
    h += `<div class="card">
      <h3>📨 أرسل الدعوة لباقي اللاعبين</h3>
      <div class="share"><input id="lnk" readonly value="${esc(link)}">
      <button class="ghost sm" data-copy="1">نسخ</button></div>
      <div class="row" style="margin-top:10px;flex-wrap:nowrap">
        <button class="wa grow" data-wa="1">واتساب</button>
        <button class="tg grow" data-tg="1">تيليجرام</button>
        ${canShare ? '<button class="ghost grow" data-share="1">مشاركة…</button>' : ''}
      </div>
      <p class="muted" style="margin-top:10px">أو أعطهم رمز الغرفة: <b style="letter-spacing:4px">${S.code}</b></p>
    </div>`;
    h += `<div class="card"><h3>اللاعبون (${S.players.length})</h3>${playerList({})}
      <p class="muted" style="margin-top:12px">
        الأدوار: قاتلان 🔪 · طبيب 🩺 · محقق 🕵️ · والباقي مواطنون 🧑<br>
        حماية الطبيب: ${S.settings.doctorRule === 'once' ? 'مرة واحدة لكل شخص طوال اللعبة' : 'لا يحمي نفس الشخص ليلتين متتاليتين'}
        · مدة التصويت: ${Math.round(S.settings.voteSeconds / 60)} دقيقة
      </p></div>`;
    if (you.isHost) {
      const ok = S.players.length >= S.minPlayers;
      h += `<button style="width:100%" data-act="start"${ok ? '' : ' disabled'}>
        ${ok ? 'ابدأ القرعة وتوزيع الأدوار 🎲' : `بانتظار ${S.minPlayers - S.players.length} لاعبين إضافيين`}</button>`;
    } else {
      h += `<div class="card muted" style="text-align:center">بانتظار أن يبدأ المضيف اللعبة…</div>`;
    }
  }

  else if (S.phase === 'reveal') {
    h += narration();
    if (!revealed) {
      h += `<div class="card night"><div class="emo">🎴</div>
        <h2 style="margin-top:10px">بطاقتك جاهزة</h2>
        <p class="muted">تأكد أن أحداً لا يرى شاشتك، ثم اكشف دورك.</p>
        <div style="height:14px"></div>
        <button style="width:100%" data-reveal="1">اكشف دوري 👀</button></div>`;
    } else {
      const r = you.role;
      h += `<div class="rolecard ${r}">
        <div class="emo">${ROLE_EMO[r]}</div>
        <h2>أنت ${you.roleAr}</h2>
        <p class="muted">${ROLE_DESC[r]}</p>
        ${S.allies && S.allies.length ? `<p style="margin-top:10px;color:#ff8fa3">شريكك في الجريمة: <b>${esc(S.allies.join('، '))}</b></p>` : ''}
      </div>
      <div style="height:12px"></div>
      ${you.ready ? '<div class="card muted" style="text-align:center">بانتظار بقية اللاعبين…</div>'
        : '<button style="width:100%" data-act="ready">أنا جاهز ✅</button>'}`;
      h += `<div class="card" style="margin-top:14px"><h3>اللاعبون</h3>${playerList({})}</div>`;
    }
  }

  else if (S.phase === 'night_intro') {
    h += narration();
    h += nightScreen('🌙', 'أغمض عينيك', 'حلّ الليل على المدينة…');
  }

  else if (S.phase === 'night_killers') {
    h += narration();
    if (you.role === 'killer' && you.alive) {
      const allies = S.players.filter(p => p.ally || (p.isYou)).map(p => p.id);
      h += `<div class="card"><h3>🔪 اختاروا الضحية</h3>
        <p class="muted">يجب أن تتفقا على نفس الشخص. إن اختلفتما حتى انتهاء الوقت، يُختار أحد اختياريكما عشوائياً.</p>
        <div style="height:10px"></div>
        ${playerList({ pick: true, exclude: allies })}
        ${confirmBar('تأكيد الاختيار')}
        ${S.picks && S.picks.length ? `<p class="muted" style="margin-top:10px">الاختيارات الحالية: ${S.picks.map(x => esc(x.name) + ' ← ' + esc(x.target)).join(' · ')}</p>` : ''}
      </div>`;
      h += `<div class="card"><h3>محادثة القتلة (سرية)</h3>
        <div class="chat" id="chat">${(S.chat || []).map(m => `<div class="msg"><b>${esc(m.name)}:</b> ${esc(m.text)}</div>`).join('') || '<div class="muted">لا رسائل بعد…</div>'}</div>
        <div class="row"><input id="cmsg" class="grow" placeholder="اكتب رسالة لشريكك…" maxlength="200">
        <button class="sm" data-send="1">إرسال</button></div></div>`;
    } else {
      h += nightScreen('🌙', 'أغمض عينيك', 'القتلة يتشاورون على ضحيتهم…');
    }
  }

  else if (S.phase === 'night_detective') {
    h += narration();
    if (you.role === 'detective' && you.alive) {
      const last = (S.investigations || []).filter(x => x.day === S.day)[0];
      if (last) {
        h += `<div class="card"><h3>🕵️ نتيجة الاستفسار</h3>
          <div class="res ${last.result ? 'yes' : 'no'}">${esc(last.name)} — ${last.result ? 'قاتل 🔪' : 'ليس قاتلاً ✅'}</div>
          <div style="height:12px"></div>
          <button style="width:100%" data-act="investigate_done">فهمت، أغلق عيني 🙈</button></div>`;
      } else {
        h += `<div class="card"><h3>🕵️ استفسر عن شخص واحد</h3>
          <p class="muted">سيخبرك النظام مباشرة إن كان قاتلاً أم لا.</p><div style="height:10px"></div>
          ${playerList({ pick: true, exclude: [you.id] })}
          ${confirmBar('استفسر عنه')}</div>`;
      }
      if ((S.investigations || []).length) {
        h += `<div class="card"><h3>استفساراتك السابقة</h3><div class="log">` +
          S.investigations.map(x => `<div>الليلة ${x.day}: ${esc(x.name)} — ${x.result ? '<b style="color:#ff8fa3">قاتل</b>' : 'ليس قاتلاً'}</div>`).join('') + `</div></div>`;
      }
    } else {
      h += nightScreen('🌙', 'أغمض عينيك', 'المحقق يستفسر عن أحدهم…');
    }
  }

  else if (S.phase === 'night_doctor') {
    h += narration();
    if (you.role === 'doctor' && you.alive) {
      h += `<div class="card"><h3>🩺 احمِ شخصاً الليلة</h3>
        <p class="muted">يمكنك حماية نفسك. ${S.settings.doctorRule === 'once' ? 'لا يمكنك حماية نفس الشخص أكثر من مرة في اللعبة.' : 'لا يمكنك حماية نفس الشخص ليلتين متتاليتين.'}</p>
        <div style="height:10px"></div>
        ${playerList({ pick: true, exclude: S.blocked || [], blocked: S.blocked || [] })}
        ${confirmBar('احمِ هذا الشخص')}</div>`;
    } else {
      h += nightScreen('🌙', 'أغمض عينيك', 'الطبيب يختار من يحمي…');
    }
  }

  else if (S.phase === 'day_announce') {
    h += narration();
    h += `<div class="card" style="text-align:center">
      <div style="font-size:56px">${S.victim ? '⚰️' : '🛡️'}</div>
      <div class="big" style="color:${S.victim ? 'var(--danger)' : 'var(--acc2)'}">
        ${S.victim ? 'عملية قتل ناجحة' : 'عملية قتل فاشلة'}</div>
      <p class="muted">${S.victim ? 'الضحية: <b style="color:var(--txt);font-size:18px">' + esc(S.victim) + '</b>'
        : (S.saved ? 'تدخّل الطبيب في الوقت المناسب وأنقذ الهدف.' : 'لم يسقط أحد هذه الليلة.')}</p>
    </div>`;
    h += `<div class="card"><h3>اللاعبون</h3>${playerList({})}</div>`;
  }

  else if (S.phase === 'day_vote') {
    h += narration();
    if (you.alive) {
      h += `<div class="card"><h3>🗳️ صوّت على المشتبه به</h3>
        <p class="muted">ناقشوا فيما بينكم، ثم اختر لاعباً أو اختر عدم التصويت. يمكنك تغيير صوتك حتى انتهاء الوقت.</p>
        <div style="height:10px"></div>
        ${playerList({ pick: true, tally: S.tally, voters: S.voters })}
        <div class="row" style="margin-top:12px">
          <button class="grow" data-confirm="1"${sel ? '' : ' disabled'}>تأكيد التصويت</button>
          <button class="ghost" data-act="vote-skip">عدم التصويت ${S.tally && S.tally.skip ? '(' + S.tally.skip + ')' : ''}</button>
        </div>
        ${S.myVote ? `<p class="muted" style="margin-top:10px">صوتك الحالي: <b>${S.myVote === 'skip' ? 'عدم التصويت' : esc((S.players.find(p => p.id === S.myVote) || {}).name || '')}</b></p>` : ''}
      </div>`;
    } else {
      h += `<div class="card"><h3>🗳️ التصويت جارٍ</h3>
        <p class="muted">أنت خارج اللعبة — تتابع كمشاهد.</p><div style="height:10px"></div>
        ${playerList({ tally: S.tally, voters: S.voters })}</div>`;
    }
  }

  else if (S.phase === 'day_result') {
    h += narration();
    h += `<div class="card" style="text-align:center">
      <div style="font-size:56px">${S.eliminated ? '🚪' : '🤝'}</div>
      <div class="big">${S.eliminated ? 'تم استبعاد ' + esc(S.eliminated) : 'لم يُستبعد أحد اليوم'}</div>
      <p class="muted">${S.eliminated ? 'لن يكشف النظام دوره.' : 'تعادل أو تغلّب خيار عدم التصويت.'}</p></div>`;
    h += `<div class="card"><h3>اللاعبون</h3>${playerList({})}</div>`;
  }

  else if (S.phase === 'ended') {
    const win = S.winner === 'killers';
    h += `<div class="card" style="text-align:center">
      <div style="font-size:64px">${win ? '🔪' : '🎉'}</div>
      <div class="big" style="color:${win ? 'var(--danger)' : 'var(--acc2)'}">
        ${win ? 'فاز القتلة!' : 'فاز المواطنون!'}</div>
      <p class="muted">${win ? 'تساوى عدد القتلة مع بقية اللاعبين.' : 'تم إخراج القاتلين من اللعبة.'}</p></div>`;
    h += `<div class="card"><h3>كشف الأدوار</h3>${playerList({})}</div>`;
    if (you.isHost) h += `<button style="width:100%" data-act="restart">جولة جديدة بنفس اللاعبين 🔄</button>`;
    else h += `<div class="card muted" style="text-align:center">بانتظار المضيف لبدء جولة جديدة…</div>`;
  }

  if (!['lobby', 'reveal', 'ended'].includes(S.phase)) h += logBox();

  if (you.isHost && !['lobby', 'ended'].includes(S.phase)) {
    h += `<div class="row" style="margin-top:6px;justify-content:center">
      <button class="ghost sm" data-act="next">⏭️ تخطّي هذه المرحلة (المضيف)</button></div>`;
  }
  if (!you.alive && S.phase !== 'lobby' && S.phase !== 'ended' && S.phase !== 'day_vote') {
    h = `<div class="card" style="text-align:center;border-color:#6b1e35">
      <b>أنت خارج اللعبة</b><p class="muted" style="margin:6px 0 0">تتابع كمشاهد — لا تفصح عن أي معلومة.</p></div>` + h;
  }

  app.innerHTML = h;
  wire();
}

/* ------------------------------------------------ الأحداث */
function wire() {
  app.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => {
    if (b.dataset.blocked) return;
    sel = b.dataset.pick; selPhase = S.phase; render();
  });
  app.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const a = b.dataset.act;
    if (a === 'vote-skip') { sel = 'skip'; await act({ type: 'vote', target: 'skip' }); return; }
    await act({ type: a });
  });
  const conf = app.querySelector('[data-confirm]');
  if (conf) conf.onclick = async () => {
    if (!sel) return;
    const map = { night_killers: 'kill', night_detective: 'investigate', night_doctor: 'protect', day_vote: 'vote' };
    const t = map[S.phase];
    if (t) await act({ type: t, target: sel });
  };
  const rv = app.querySelector('[data-reveal]');
  if (rv) rv.onclick = () => { revealed = true; render(); };
  const cp = app.querySelector('[data-copy]');
  if (cp) cp.onclick = async () => {
    const v = app.querySelector('#lnk').value;
    try { await navigator.clipboard.writeText(v); cp.textContent = 'تم النسخ ✓'; }
    catch (e) { app.querySelector('#lnk').select(); document.execCommand('copy'); cp.textContent = 'تم النسخ ✓'; }
    setTimeout(() => { if (cp) cp.textContent = 'نسخ'; }, 1600);
  };
  const shareText = () => `انضم إلى جولة مافيا 🎭\nرمز الغرفة: ${S.code}\n${location.origin}/?code=${S.code}`;
  const wa = app.querySelector('[data-wa]');
  if (wa) wa.onclick = () => window.open('https://wa.me/?text=' + encodeURIComponent(shareText()), '_blank');
  const tg = app.querySelector('[data-tg]');
  if (tg) tg.onclick = () => window.open('https://t.me/share/url?url=' +
    encodeURIComponent(location.origin + '/?code=' + S.code) +
    '&text=' + encodeURIComponent('انضم إلى جولة مافيا 🎭 — رمز الغرفة: ' + S.code), '_blank');
  const sh = app.querySelector('[data-share]');
  if (sh) sh.onclick = async () => {
    try { await navigator.share({ title: 'مافيا 🎭', text: 'انضم إلى جولة مافيا — رمز الغرفة: ' + S.code,
                                  url: location.origin + '/?code=' + S.code }); }
    catch (e) { /* ألغى المستخدم المشاركة */ }
  };
  const send = app.querySelector('[data-send]');
  if (send) {
    const inp = app.querySelector('#cmsg');
    const go = async () => { const t = inp.value.trim(); if (!t) return; inp.value = ''; draft = ''; await act({ type: 'chat', text: t }); };
    send.onclick = go;
    inp.oninput = () => { draft = inp.value; };
    inp.onkeydown = e => { if (e.key === 'Enter') go(); };
    if (draft) inp.value = draft;
    const c = app.querySelector('#chat'); if (c) c.scrollTop = c.scrollHeight;
  }
}

if (window.speechSynthesis) speechSynthesis.getVoices();
poll();

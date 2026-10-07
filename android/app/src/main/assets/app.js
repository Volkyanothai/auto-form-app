'use strict';
const $ = id => document.getElementById(id);
let workspace = null, values = {}, activeAction = '', fallbackUrl = '', busy = false;
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function setBusy(on, message) {
  busy = on;
  document.body.classList.toggle('busy', on);
  $('progress').hidden = !on;
  if (message) $('progressText').textContent = message;
  document.querySelectorAll('button').forEach(b => { b.disabled = on; });
  $('questions').querySelectorAll('input,textarea').forEach(el => { el.disabled = on; });
  if (!on) updateSummary();
}
function request(action, args) {
  if (busy) return;
  notice('');
  activeAction = action;
  setBusy(true, 'กำลังทำงาน…');
  args = Object.assign({}, args);
  if (action === 'analyze' || action === 'saveKey') args.api_key = $('apiKey').value;
  if (!window.Android) { setBusy(false); notice('กรุณาเปิดผ่านแอป EZEXAM'); return; }
  Android.request(action, JSON.stringify(args));
}
function hasValue(v) { return Array.isArray(v) ? v.length > 0 : !!String(v || '').trim(); }
function changed() {
  $('reviewed').checked = false;
  $('submitResult').textContent = '';
  $('fallback').hidden = true;
  updateSummary();
}
function updateSummary() {
  if (!workspace) return;
  const qs = workspace.questions;
  const count = qs.filter(q => hasValue(values[q.entry_id])).length;
  const risky = qs.filter(q => {
    const answer = workspace.answers[q.entry_id];
    return !hasValue(values[q.entry_id]) || !answer || answer.risk_level !== 'safe';
  }).length;
  $('summary').textContent = qs.length + ' ข้อ · มีคำตอบ ' + count + ' ข้อ · ต้องตรวจทาน ' + risky + ' ข้อ';
  $('reviewSummary').textContent = 'ตรวจคำตอบ ' + count + '/' + qs.length + ' ข้อ และข้อมูลผู้ตอบก่อนส่ง';
  $('submit').disabled = busy || !$('reviewed').checked || workspace.submitted;
  $('analyze').disabled = busy || workspace.submitted;
}
function renderPersonal() {
  const list = $('personalFields'); list.replaceChildren();
  const entries = Object.entries(workspace.personal);
  $('personal').hidden = entries.length === 0;
  for (const [eid, info] of entries) {
    if (!(eid in values)) values[eid] = info.value || '';
    const label = node('label', info.title + (info.required ? ' *' : ''));
    const input = node('input'); input.value = values[eid]; input.autocomplete = 'off';
    input.addEventListener('input', () => { values[eid] = input.value; changed(); });
    label.append(input); list.append(label);
  }
}
function appendImage(parent, image) {
  if (image.data) {
    const img = node('img'); img.src = image.data; img.alt = 'รูปประกอบคำถามหรือตัวเลือก';
    img.className = 'questionImage'; img.loading = 'lazy'; parent.append(img);
  } else parent.append(node('p', 'โหลดรูปประกอบไม่สำเร็จ โปรดตรวจในฟอร์มต้นฉบับ', 'risk'));
}
function renderQuestions() {
  const target = $('questions'); target.replaceChildren();
  const filter = $('filter').value;
  workspace.questions.forEach((q, index) => {
    const ai = workspace.answers[q.entry_id];
    const hasImages = q.images.length || Object.values(q.choice_images).some(a => a.length);
    const risky = !ai || ai.risk_level !== 'safe' || !hasValue(values[q.entry_id]);
    if (filter === 'review' && !risky || filter === 'blank' && hasValue(values[q.entry_id]) ||
        filter === 'image' && !hasImages) return;
    const card = node('section', undefined, 'card');
    card.append(node('span', 'ข้อ ' + (index + 1) + (q.required ? ' · จำเป็น' : ''), 'badge'));
    if (q.section) card.append(node('p', q.section, 'muted'));
    card.append(node('h2', q.title));
    if (q.context_notes.length) card.append(node('p', q.context_notes.join(' · '), 'muted'));
    q.images.forEach(image => appendImage(card, image));
    if (q.choices.length) {
      q.choices.forEach((choice, choiceIndex) => {
        const label = node('label', undefined, 'choice'), input = node('input');
        input.type = q.is_multi ? 'checkbox' : 'radio'; input.name = q.entry_id;
        const current = values[q.entry_id];
        input.checked = q.is_multi ? Array.isArray(current) && current.includes(choice) : current === choice;
        const content = node('div', choice);
        (q.choice_images[String(choiceIndex)] || []).forEach(image => appendImage(content, image));
        input.addEventListener('change', () => {
          if (q.is_multi) values[q.entry_id] = q.choices.filter((_, i) => card.querySelectorAll('.choice input')[i].checked);
          else values[q.entry_id] = choice;
          changed();
        });
        label.append(input, content); card.append(label);
      });
    } else {
      const label = node('label', 'คำตอบ');
      const input = node('textarea'); input.rows = 3; input.value = values[q.entry_id] || '';
      input.addEventListener('input', () => { values[q.entry_id] = input.value; changed(); });
      label.append(input); card.append(label);
    }
    if (ai) {
      const score = ai.reliability_score === undefined ? ai.confidence : ai.reliability_score;
      card.append(node('p', 'ความเชื่อมั่น ' + score + '% · ' + (ai.verification || 'ยังไม่ได้ตรวจทาน'), risky ? 'risk' : 'muted'));
      card.append(node('p', ai.reasoning || '', 'answerInfo'));
      if (ai.risk_reasons && ai.risk_reasons.length) card.append(node('p', ai.risk_reasons.join(' · '), 'risk'));
    }
    const retry = node('button', 'วิเคราะห์ข้อนี้ใหม่', 'quiet');
    retry.disabled = busy || workspace.submitted;
    retry.addEventListener('click', () => {
      if (hasValue(values[q.entry_id]) && !confirm('วิเคราะห์ใหม่และแทนคำตอบข้อนี้เมื่อได้คำตอบใหม่?')) return;
      request('analyze', {entry_id: q.entry_id});
    });
    card.append(retry); target.append(card);
  });
}
function displayWorkspace(data, resetValues) {
  workspace = data;
  if (resetValues) values = {};
  if (activeAction === 'analyze') {
    for (const [eid, answer] of Object.entries(data.answers)) {
      // Preserve edits on other questions during a single-question analysis.
      if (!window.analysisEntry || eid === window.analysisEntry) {
        if (hasValue(answer.answer)) values[eid] = answer.answer;
      }
    }
  }
  $('formTitle').textContent = data.title;
  $('setup').hidden = true; $('workspace').hidden = false;
  renderPersonal(); renderQuestions(); updateSummary();
  if (data.errors.length) notice(data.errors.join('\n'));
  changed();
}
window.nativeEvent = result => {
  const event = result.event, data = result.data;
  if (event === 'progress') { $('progressText').textContent = result.message; return; }
  if (event === 'ready') {
    $('keyStatus').textContent = result.message || 'ยังไม่ได้บันทึก API Key';
    return;
  }
  setBusy(false);
  if (event === 'error') notice(result.message);
  else if (event === 'key') {
    $('keyStatus').textContent = result.message; $('apiKey').value = '';
  } else if (event === 'load') {
    window.analysisEntry = null; displayWorkspace(data, true);
    window.scrollTo(0, 0);
  } else if (event === 'analyze') displayWorkspace(data, false);
  else if (event === 'reset') {
    workspace = null; values = {};
    $('workspace').hidden = true; $('setup').hidden = false;
    $('questions').replaceChildren(); $('personalFields').replaceChildren();
    $('reviewed').checked = false; $('filter').value = 'all';
    window.scrollTo(0,0);
  } else if (event === 'submit') {
    $('submitResult').textContent = data.message;
    if (data.success) {
      workspace.submitted = true; updateSummary(); renderQuestions();
      $('fallback').hidden = true;
    } else {
      fallbackUrl = data.url; $('fallback').hidden = !fallbackUrl;
      if (data.truncated) notice('คำตอบยาวเกินลิงก์ กรุณาคัดลอกคำตอบแล้วกรอกใน Google Forms');
    }
  } else if (event === 'prefill') {
    if (data.truncated) notice('คำตอบยาวเกินลิงก์ เปิดฟอร์มต้นฉบับแล้วกรอกโดยคัดลอกจากคำตอบในแอป');
    if (data.url) Android.open(data.url);
  }
};
const originalRequest = request;
request = function(action, args) {
  if (action === 'analyze') window.analysisEntry = args.entry_id || null;
  originalRequest(action, args);
};
$('settingsToggle').onclick = () => { $('settings').hidden = !$('settings').hidden; };
$('saveKey').onclick = () => request('saveKey', {});
$('forgetKey').onclick = () => { if (window.Android) Android.forgetKey(); };
$('getKey').onclick = () => Android.open('https://aistudio.google.com/apikey');
$('load').onclick = () => {
  if (!$('formUrl').value.trim()) { notice('กรุณาใส่ลิงก์ Google Forms'); return; }
  request('load', {url:$('formUrl').value, name:$('name').value, student_id:$('studentId').value,
    number:$('number').value, classroom:$('classroom').value, context:$('context').value});
};
$('analyze').onclick = () => {
  if (Object.values(values).some(hasValue) && !confirm('วิเคราะห์ทุกข้อและแทนคำตอบที่มีอยู่เมื่อได้คำตอบใหม่?')) return;
  request('analyze', {});
};
$('newForm').onclick = () => { if (confirm('เริ่มฟอร์มใหม่และล้างคำตอบในหน้านี้?')) request('reset', {}); };
$('openOriginal').onclick = () => Android.open(workspace.original_url);
$('filter').onchange = renderQuestions;
$('reviewed').onchange = updateSummary;
$('submit').onclick = () => { if ($('reviewed').checked) request('submit', {answers:values}); };
$('prefill').onclick = () => request('prefill', {answers:values});
$('fallback').onclick = () => Android.open(fallbackUrl);
$('copyAnswers').onclick = () => {
  let text = workspace.title + '\n';
  workspace.questions.forEach((q,i) => {
    let value = values[q.entry_id] || '';
    if (Array.isArray(value)) value = value.join(', ');
    text += '\nข้อ ' + (i+1) + ': ' + q.title + '\n' + value + '\n';
  });
  const area = node('textarea'); area.value = text; document.body.append(area); area.select();
  const ok = document.execCommand('copy'); area.remove();
  notice(ok ? 'คัดลอกคำตอบแล้ว' : 'คัดลอกไม่สำเร็จ กรุณากดค้างที่ข้อความคำตอบ');
};
window.handleBack = () => {
  if (!$('settings').hidden) { $('settings').hidden = true; return true; }
  if (workspace) { $('newForm').click(); return true; }
  return false;
};

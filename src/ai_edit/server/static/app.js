// image-ai-edit web UI
//
// Single-page client. State lives in this module:
//   - sceneFile / referenceFile : the two input files (set via drag-drop or click)
//   - lastComposite             : Blob of the most recent generated image
//   - history                   : array of {blob, label, kind: 'initial'|'refine'}
//
// The server is stateless. Every refine call sends the original
// scene + reference + the previous composite back up so Gemini sees
// the same context — see /api/insert in app.py.

const $ = (sel, root = document) => root.querySelector(sel);

const sceneDrop      = $('.drop[data-target=scene]');
const referenceDrop  = $('.drop[data-target=reference]');
const sceneInput     = $('input', sceneDrop);
const referenceInput = $('input', referenceDrop);
const instructionEl  = $('#instruction');
const segmentEl      = $('#segment');
const relightEl      = $('#relight');
const generateBtn    = $('#generate');
const generateLabel  = $('.label', generateBtn);
const spinner        = $('.spinner', generateBtn);
const statusEl       = $('#status');
const canvasEl       = $('#canvas');
const refineForm     = $('#refine');
const refineInput    = $('#refine-input');
const historyList    = $('#history-list');

let sceneFile = null;
let referenceFile = null;
let lastComposite = null;
const history = [];

// ----- Drag-drop wiring -----
function bindDrop(drop, input, onFile) {
  drop.addEventListener('click', () => input.click());
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    if (e.dataTransfer.files.length) onFile(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', () => {
    if (input.files.length) onFile(input.files[0]);
  });
}

function setPreview(drop, file) {
  const url = URL.createObjectURL(file);
  drop.innerHTML = `<img src="${url}" alt="" />`;
}

bindDrop(sceneDrop, sceneInput, (file) => {
  sceneFile = file;
  setPreview(sceneDrop, file);
});
bindDrop(referenceDrop, referenceInput, (file) => {
  referenceFile = file;
  setPreview(referenceDrop, file);
});

// ----- Generate / refine -----
function setBusy(busy) {
  generateBtn.disabled = busy;
  refineForm.querySelector('button').disabled = busy;
  spinner.hidden = !busy;
  generateLabel.textContent = busy ? 'Generating…' : 'Generate';
  canvasEl.classList.toggle('loading', busy);
}

function setStatus(msg, isError = false) {
  statusEl.textContent = msg || '';
  statusEl.classList.toggle('err', !!isError);
}

function renderResult(blob, label, kind) {
  const url = URL.createObjectURL(blob);
  canvasEl.classList.remove('empty');
  canvasEl.innerHTML = `<img src="${url}" alt="composite" />`;
  refineForm.hidden = false;
  refineInput.focus();
  pushHistory(blob, label, kind);
}

function pushHistory(blob, label, kind) {
  const item = { blob, label, kind, url: URL.createObjectURL(blob) };
  history.unshift(item);
  renderHistory();
}

function renderHistory() {
  if (!history.length) return;
  historyList.innerHTML = '';
  history.forEach((item, i) => {
    const div = document.createElement('div');
    div.className = 'history-item' + (i === 0 ? ' active' : '');
    div.innerHTML = `
      <img src="${item.url}" alt="${item.label}" title="${item.label}" />
      <span class="badge">${item.kind}</span>`;
    div.addEventListener('click', () => {
      lastComposite = item.blob;
      canvasEl.classList.remove('empty');
      canvasEl.innerHTML = `<img src="${item.url}" alt="composite" />`;
      Array.from(historyList.children).forEach((c) => c.classList.remove('active'));
      div.classList.add('active');
      refineForm.hidden = false;
    });
    historyList.appendChild(div);
  });
}

async function callPipeline(formData, kind) {
  setBusy(true);
  setStatus('Running pipeline… (~10–20s)');
  const t0 = performance.now();
  try {
    const res = await fetch('/api/insert', { method: 'POST', body: formData });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    const blob = await res.blob();
    lastComposite = blob;
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    setStatus(`Done in ${elapsed}s.`);
    const label = kind === 'initial'
      ? truncate(instructionEl.value, 60)
      : truncate(refineInput.value, 60);
    renderResult(blob, label, kind);
    if (kind === 'refine') refineInput.value = '';
  } catch (err) {
    setStatus(String(err.message || err), true);
  } finally {
    setBusy(false);
  }
}

function truncate(s, n) {
  s = (s || '').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

generateBtn.addEventListener('click', () => {
  if (!sceneFile || !referenceFile) {
    setStatus('Drop both a scene and a reference image first.', true);
    return;
  }
  if (!instructionEl.value.trim()) {
    setStatus('Add an instruction.', true);
    return;
  }
  history.length = 0;
  lastComposite = null;
  const fd = new FormData();
  fd.append('scene', sceneFile);
  fd.append('reference', referenceFile);
  fd.append('instruction', instructionEl.value);
  if (segmentEl.value.trim()) fd.append('segment', segmentEl.value);
  if (relightEl.value.trim()) fd.append('relight', relightEl.value);
  callPipeline(fd, 'initial');
});

refineForm.addEventListener('submit', (e) => {
  e.preventDefault();
  if (!lastComposite) return;
  if (!refineInput.value.trim()) return;
  if (!sceneFile || !referenceFile) {
    setStatus('Original scene/reference missing — refresh and try again.', true);
    return;
  }
  const fd = new FormData();
  fd.append('scene', sceneFile);
  fd.append('reference', referenceFile);
  fd.append('instruction', refineInput.value);
  fd.append('previous', lastComposite, 'previous.png');
  callPipeline(fd, 'refine');
});

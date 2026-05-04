// image-ai-edit web UI
//
// State (module-local):
//   sceneFile / referenceFile : the two input files
//   polygonPoints             : [[u, v], ...] in [0, 1] — the drawn region
//   defaults                  : { free, mask, refine } system prompts
//   currentMode               : "free" | "mask"
//   promptDirty               : true if the user manually edited the system prompt
//   lastComposite             : Blob of the most recent composite (used by refine)
//   history                   : [{ blob, label, kind: 'initial'|'refine', url }]

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// --- DOM
const sceneDrop      = $('.drop[data-target=scene]');
const referenceDrop  = $('.drop[data-target=reference]');
const sceneInput     = $('input', sceneDrop);
const referenceInput = $('input', referenceDrop);
const sceneActions   = $('.scene-block .actions');
const polyHint       = $('#poly-hint');
const clearPolyBtn   = $('#clear-poly');
const undoPolyBtn    = $('#undo-poly');
const replaceSceneBtn = $('#replace-scene');

const modeRadios     = $$('input[name=mode]');
const promptDetails  = $('#prompt-details');
const promptModeTag  = $('#prompt-mode-tag');
const promptArea     = $('#system-prompt');
const resetPromptBtn = $('#reset-prompt');

const instructionEl  = $('#instruction');
const segmentEl      = $('#segment');
const relightEl      = $('#relight');
const generateBtn    = $('#generate');
const generateLabel  = $('.label', generateBtn);
const spinner        = $('.spinner', generateBtn);
const statusEl       = $('#status');

const canvasEl       = $('#canvas');
const auxRow         = $('#aux-row');
const auxLabel       = $('#aux-label');
const auxImg         = $('#aux-preview');
const refineForm     = $('#refine');
const refineInput    = $('#refine-input');
const historyList    = $('#history-list');

// --- State
let sceneFile = null;
let referenceFile = null;
let polygonPoints = [];
let lastComposite = null;
const history = [];

let defaults = { free: '', mask: '', refine: '' };
let currentMode = 'free';
let promptDirty = false;

// --- Defaults bootstrap
fetch('/api/defaults')
  .then((r) => r.json())
  .then((d) => {
    defaults = d;
    syncSystemPrompt(); // fill the textarea now that defaults arrived
  })
  .catch(() => setStatus('Could not load default prompts.', true));

// --- File drops
bindFileDrop(referenceDrop, referenceInput, (file) => {
  referenceFile = file;
  const url = URL.createObjectURL(file);
  referenceDrop.innerHTML = `<img class="ref-img" src="${url}" alt="" />`;
});

bindFileDrop(sceneDrop, sceneInput, (file) => {
  sceneFile = file;
  loadSceneEditor(file);
});

function bindFileDrop(drop, input, onFile) {
  drop.addEventListener('click', () => {
    if (drop.classList.contains('has-image')) return; // clicks become poly vertices
    input.click();
  });
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

// --- Scene editor (image + polygon overlay)
function loadSceneEditor(file) {
  const url = URL.createObjectURL(file);
  sceneDrop.classList.add('has-image');
  sceneDrop.innerHTML = `
    <img class="scene-img" src="${url}" alt="scene" />
    <svg class="poly-overlay" preserveAspectRatio="none"></svg>`;
  sceneActions.hidden = false;
  polyHint.hidden = false;

  const img = sceneDrop.querySelector('img');
  img.addEventListener('load', () => {
    const svg = sceneDrop.querySelector('svg');
    svg.setAttribute('viewBox', `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    redrawPolygon();
  });

  polygonPoints = [];
  redrawPolygon();
}

sceneDrop.addEventListener('click', (e) => {
  if (!sceneDrop.classList.contains('has-image')) return;
  if (e.target.tagName === 'BUTTON') return;
  const img = sceneDrop.querySelector('img.scene-img');
  if (!img) return;
  const rect = img.getBoundingClientRect();
  const u = (e.clientX - rect.left) / rect.width;
  const v = (e.clientY - rect.top) / rect.height;
  if (u < 0 || u > 1 || v < 0 || v > 1) return;
  polygonPoints.push([u, v]);
  redrawPolygon();
});

clearPolyBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  polygonPoints = [];
  redrawPolygon();
});
undoPolyBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  polygonPoints.pop();
  redrawPolygon();
});
replaceSceneBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  sceneInput.value = '';
  sceneInput.click();
});

function redrawPolygon() {
  const svg = sceneDrop.querySelector('svg.poly-overlay');
  if (!svg) return;
  const img = sceneDrop.querySelector('img.scene-img');
  if (!img || !img.naturalWidth) return;

  const W = img.naturalWidth, H = img.naturalHeight;
  const pts = polygonPoints.map(([u, v]) => `${u * W},${v * H}`).join(' ');

  let body = '';
  if (polygonPoints.length >= 3) body += `<polygon points="${pts}" />`;
  else if (polygonPoints.length >= 2) body += `<polyline points="${pts}" />`;
  for (const [u, v] of polygonPoints) {
    body += `<circle cx="${u * W}" cy="${v * H}" r="${Math.max(W, H) / 200}" />`;
  }
  svg.innerHTML = body;
}

// --- Mode + system prompt
modeRadios.forEach((r) => {
  r.addEventListener('change', () => {
    if (!r.checked) return;
    currentMode = r.value;
    promptModeTag.textContent = `(${currentMode})`;
    syncSystemPrompt();
  });
});

promptArea.addEventListener('input', () => {
  // Mark the prompt as dirty unless the user is actively typing the
  // exact default — then leave it pristine so future mode switches
  // can replace it cleanly.
  promptDirty = promptArea.value.trim() !== (defaults[currentMode] || '').trim();
});

resetPromptBtn?.addEventListener('click', () => {
  promptArea.value = defaults[currentMode] || '';
  promptDirty = false;
  promptArea.focus();
});

function syncSystemPrompt() {
  // Replace textarea contents with the active mode's default unless
  // the user has manually edited — in which case leave their text
  // alone (they can hit "Reset to default" if they want).
  if (promptDirty) return;
  promptArea.value = defaults[currentMode] || '';
}

// --- Generate / refine
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

function renderResult(blob, label, kind, auxUrl, auxKind) {
  const url = URL.createObjectURL(blob);
  canvasEl.classList.remove('empty');
  canvasEl.innerHTML = `<img src="${url}" alt="composite" />`;
  if (auxUrl && auxKind) {
    auxImg.src = auxUrl;
    auxLabel.textContent = 'Mask sent to model:';
    auxRow.hidden = false;
  } else {
    auxRow.hidden = true;
    auxImg.removeAttribute('src');
  }
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
  setStatus('Running pipeline… (~10–30s)');
  const t0 = performance.now();
  try {
    const res = await fetch('/api/insert', { method: 'POST', body: formData });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    const json = await res.json();
    const compositeRes = await fetch(json.composite_url);
    if (!compositeRes.ok) throw new Error('composite fetch failed');
    const blob = await compositeRes.blob();
    lastComposite = blob;

    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    setStatus(`Done in ${elapsed}s.`);
    const label = kind === 'initial'
      ? truncate(instructionEl.value, 60)
      : truncate(refineInput.value, 60);
    renderResult(blob, label, kind, json.aux_url, json.aux_kind);
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
  if (currentMode === 'mask' && polygonPoints.length < 3) {
    setStatus('mask mode needs a polygon — click 3+ points on the scene.', true);
    return;
  }
  history.length = 0;
  lastComposite = null;
  const fd = new FormData();
  fd.append('scene', sceneFile);
  fd.append('reference', referenceFile);
  fd.append('instruction', instructionEl.value);
  fd.append('mode', currentMode);
  if (polygonPoints.length >= 3) {
    fd.append('polygon', JSON.stringify(polygonPoints));
  }
  if (promptDirty && promptArea.value.trim()) {
    fd.append('system_prompt', promptArea.value);
  }
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
  // Refinement explicitly drops mode + polygon + custom prompt —
  // refinement uses the refine system prompt regardless.
  callPipeline(fd, 'refine');
});

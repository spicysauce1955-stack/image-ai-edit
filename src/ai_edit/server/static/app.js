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
const refCropEl      = $('#reference-crop');
const maskEngineEl   = $('#mask-engine');
const generateBtn    = $('#generate');
const generateLabel  = $('.label', generateBtn);
const spinner        = $('.spinner', generateBtn);
const statusEl       = $('#status');

const canvasEl       = $('#canvas');
const auxRow         = $('#aux-row');
const auxLabel       = $('#aux-label');
const auxImg         = $('#aux-preview');
const arRow          = $('#ar-row');
const refineForm     = $('#refine');
const refineInput    = $('#refine-input');
const historyList    = $('#history-list');

// --- State
let sceneFile = null;
let referenceFile = null;
// `poles` is the new placement primitive: each entry is the BASE position
// of a fence post in normalized image coords. Sections auto-generate
// between consecutive poles in click order. Replaces the old polygon
// vertices for fence-style insertions.
let poles = [];
let sectionHeightPct = 18;     // section height as % of image height
let lastComposite = null;
const history = [];

// AR catalog cache, populated from /api/catalog on page load. Empty
// until the fetch resolves, in which case the AR picker stays hidden —
// renderResult is robust to that.
let arCatalog = [];

let defaults = { free: '', mask: '', overlay: '', refine: '' };
let currentMode = 'mask';
let promptDirty = false;
let overlayAlphaPct = 85;
const overlayAlphaSlider = $('#overlay-alpha');
const alphaDisplay = $('#alpha-display');
overlayAlphaSlider?.addEventListener('input', () => {
  overlayAlphaPct = parseInt(overlayAlphaSlider.value, 10);
  if (alphaDisplay) alphaDisplay.textContent = overlayAlphaPct + '%';
});

// --- Defaults bootstrap
fetch('/api/defaults')
  .then((r) => r.json())
  .then((d) => {
    defaults = d;
    syncSystemPrompt(); // fill the textarea now that defaults arrived
  })
  .catch(() => setStatus('Could not load default prompts.', true));

// --- AR catalog bootstrap (fire-and-forget). Silently fail — the AR
// picker is non-critical; the 2D pipeline still works without it.
fetch('/api/catalog')
  .then((r) => (r.ok ? r.json() : []))
  .then((entries) => { arCatalog = Array.isArray(entries) ? entries : []; })
  .catch(() => { arCatalog = []; });

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
    if (drop.classList.contains('has-image')) return; // clicks become poles
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

// --- Scene editor (image + pole overlay)
function loadSceneEditor(file) {
  const url = URL.createObjectURL(file);
  sceneDrop.classList.add('has-image');
  sceneDrop.innerHTML = `
    <img class="scene-img" src="${url}" alt="scene" />
    <svg class="poly-overlay" preserveAspectRatio="none"></svg>`;
  sceneActions.hidden = false;
  polyHint.hidden = false;
  const poleControls = $('#pole-controls');
  if (poleControls) poleControls.hidden = false;

  const img = sceneDrop.querySelector('img');
  img.addEventListener('load', () => {
    const svg = sceneDrop.querySelector('svg');
    svg.setAttribute('viewBox', `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    redrawPoles();
  });

  poles = [];
  redrawPoles();
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
  poles.push([u, v]);
  redrawPoles();
});

clearPolyBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  poles = [];
  redrawPoles();
});
undoPolyBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  poles.pop();
  redrawPoles();
});
replaceSceneBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  sceneInput.value = '';
  sceneInput.click();
});

const sectionHeightSlider = $('#section-height');
const sectionHeightDisplay = $('#section-height-display');
sectionHeightSlider?.addEventListener('input', () => {
  sectionHeightPct = parseInt(sectionHeightSlider.value, 10);
  if (sectionHeightDisplay) sectionHeightDisplay.textContent = sectionHeightPct + '%';
  redrawPoles();
});

function redrawPoles() {
  const svg = sceneDrop.querySelector('svg.poly-overlay');
  if (!svg) return;
  const img = sceneDrop.querySelector('img.scene-img');
  if (!img || !img.naturalWidth) return;

  const W = img.naturalWidth, H = img.naturalHeight;
  const sectionH = (sectionHeightPct / 100) * H;       // section height in image px
  const poleR = Math.max(W, H) / 140;                  // pole base marker radius
  const postW = Math.max(W, H) / 140;                  // post column width (visualization)

  let body = '';

  // Section parallelograms between consecutive poles.
  for (let i = 0; i < poles.length - 1; i++) {
    const [u1, v1] = poles[i], [u2, v2] = poles[i + 1];
    const x1 = u1 * W, y1 = v1 * H, x2 = u2 * W, y2 = v2 * H;
    const top1y = Math.max(0, y1 - sectionH);
    const top2y = Math.max(0, y2 - sectionH);
    body += `<polygon class="section-quad" points="${x1},${y1} ${x2},${y2} ${x2},${top2y} ${x1},${top1y}" />`;
  }

  // Post columns at each pole.
  for (const [u, v] of poles) {
    const x = u * W, y = v * H;
    const topY = Math.max(0, y - sectionH);
    body += `<rect class="post-col" x="${x - postW/2}" y="${topY}" width="${postW}" height="${y - topY}" />`;
  }

  // Pole base markers + numeric labels.
  poles.forEach(([u, v], idx) => {
    const x = u * W, y = v * H;
    body += `<circle class="pole-base" cx="${x}" cy="${y}" r="${poleR}" />`;
    body += `<text class="pole-label" x="${x}" y="${y - poleR * 1.5}" text-anchor="middle" font-size="${poleR * 2.5}">${idx + 1}</text>`;
  });

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
    auxLabel.textContent = auxKind === 'overlay'
      ? 'Overlay sent to model:'
      : 'Mask sent to model:';
    auxRow.hidden = false;
  } else {
    auxRow.hidden = true;
    auxImg.removeAttribute('src');
  }
  renderArRow(instructionEl.value);
  refineForm.hidden = false;
  refineInput.focus();
  pushHistory(blob, label, kind);
}

// Pick the most-likely category by scanning the instruction text for
// any catalog category name. Returns null when nothing matches, in
// which case the picker shows all entries.
function pickArCategoryFromInstruction(text) {
  if (!arCatalog.length) return null;
  const t = (text || '').toLowerCase();
  const categories = Array.from(new Set(arCatalog.map((e) => e.category)));
  for (const cat of categories) {
    if (t.includes(cat.toLowerCase())) return cat;
  }
  return null;
}

function renderArRow(instructionText) {
  if (!arCatalog.length) { arRow.hidden = true; return; }
  const picked = pickArCategoryFromInstruction(instructionText);
  const entries = picked
    ? arCatalog.filter((e) => e.category === picked)
    : arCatalog;
  if (!entries.length) { arRow.hidden = true; return; }

  arRow.innerHTML = '';
  const label = document.createElement('span');
  label.className = 'ar-row-label';
  label.textContent = picked ? `Try in AR (${picked}):` : 'Try in AR:';
  arRow.appendChild(label);

  for (const entry of entries) {
    const tile = document.createElement('a');
    tile.className = 'ar-tile';
    tile.href = entry.ar_url || `/ar/${entry.id}`;
    tile.target = '_blank';
    tile.rel = 'noopener';
    tile.title = `${entry.name} — open AR viewer in new tab`;

    if (entry.thumbnail_url) {
      const img = document.createElement('img');
      img.src = entry.thumbnail_url;
      img.alt = entry.name;
      img.loading = 'lazy';
      tile.appendChild(img);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'ar-tile-placeholder';
      placeholder.textContent = '3D';
      tile.appendChild(placeholder);
    }

    const name = document.createElement('span');
    name.className = 'ar-tile-name';
    name.textContent = entry.name;
    tile.appendChild(name);

    arRow.appendChild(tile);
  }
  arRow.hidden = false;
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
  if ((currentMode === 'mask' || currentMode === 'overlay') && poles.length < 2) {
    setStatus(`${currentMode} mode needs at least 2 poles — click on the scene where each fence post should stand.`, true);
    return;
  }
  history.length = 0;
  lastComposite = null;
  const fd = new FormData();
  fd.append('scene', sceneFile);
  fd.append('reference', referenceFile);
  fd.append('instruction', instructionEl.value);
  fd.append('mode', currentMode);
  if (poles.length >= 2) {
    fd.append('poles', JSON.stringify(poles));
    fd.append('pole_section_height', (sectionHeightPct / 100).toString());
    if (currentMode === 'overlay') {
      fd.append('overlay_alpha', (overlayAlphaPct / 100).toString());
    }
  }
  if (promptDirty && promptArea.value.trim()) {
    fd.append('system_prompt', promptArea.value);
  }
  if (segmentEl.value.trim()) fd.append('segment', segmentEl.value);
  if (relightEl.value.trim()) fd.append('relight', relightEl.value);
  if (refCropEl.value.trim()) fd.append('reference_crop', refCropEl.value);
  if (maskEngineEl?.value) fd.append('mask_engine', maskEngineEl.value);
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

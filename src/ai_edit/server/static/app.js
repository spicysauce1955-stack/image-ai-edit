// image-ai-edit web UI
//
// Single-page client. State lives in this module:
//   - sceneFile / referenceFile : the two input files (set via drag-drop or click)
//   - polygonPoints             : array of [u, v] in [0, 1] — the drawn region
//   - lastComposite             : Blob of the most recent composite (for refine)
//   - history                   : array of {blob, label, kind: 'initial'|'refine'}
//
// The polygon is stored in normalized image coordinates so window
// resizes during drawing don't invalidate the points. The server
// rasterizes them to a binary PNG matching the scene's pixel dims.

const $ = (sel, root = document) => root.querySelector(sel);

const sceneDrop      = $('.drop[data-target=scene]');
const referenceDrop  = $('.drop[data-target=reference]');
const sceneInput     = $('input', sceneDrop);
const referenceInput = $('input', referenceDrop);
const sceneActions   = $('.scene-block .actions');
const polyHint       = $('#poly-hint');
const clearPolyBtn   = $('#clear-poly');
const undoPolyBtn    = $('#undo-poly');
const replaceSceneBtn = $('#replace-scene');

const instructionEl  = $('#instruction');
const segmentEl      = $('#segment');
const relightEl      = $('#relight');
const generateBtn    = $('#generate');
const generateLabel  = $('.label', generateBtn);
const spinner        = $('.spinner', generateBtn);
const statusEl       = $('#status');

const canvasEl       = $('#canvas');
const maskRow        = $('#mask-row');
const maskImg        = $('#mask-preview');
const refineForm     = $('#refine');
const refineInput    = $('#refine-input');
const historyList    = $('#history-list');

let sceneFile = null;
let referenceFile = null;
let polygonPoints = [];   // [[u, v], ...] in [0, 1]
let lastComposite = null;
const history = [];

// ----- Reference drop (simple) -----
bindFileDrop(referenceDrop, referenceInput, (file) => {
  referenceFile = file;
  const url = URL.createObjectURL(file);
  referenceDrop.innerHTML = `<img class="ref-img" src="${url}" alt="" />`;
});

// ----- Scene drop -----
bindFileDrop(sceneDrop, sceneInput, (file) => {
  sceneFile = file;
  loadSceneEditor(file);
});

function bindFileDrop(drop, input, onFile) {
  drop.addEventListener('click', (e) => {
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

// ----- Scene editor (image + polygon overlay) -----
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
    // Use the natural image dims as the SVG viewBox so SVG coords map
    // straight to image pixels — drawing math stays simple.
    svg.setAttribute('viewBox', `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    redrawPolygon();
  });

  // Reset any previous polygon when a new scene is loaded.
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
  if (polygonPoints.length >= 3) {
    body += `<polygon points="${pts}" />`;
  } else if (polygonPoints.length >= 2) {
    body += `<polyline points="${pts}" />`;
  }
  // Draw vertex handles last so they sit on top.
  for (const [u, v] of polygonPoints) {
    body += `<circle cx="${u * W}" cy="${v * H}" r="${Math.max(W, H) / 200}" />`;
  }
  svg.innerHTML = body;
}

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

function renderResult(blob, label, kind, maskUrl) {
  const url = URL.createObjectURL(blob);
  canvasEl.classList.remove('empty');
  canvasEl.innerHTML = `<img src="${url}" alt="composite" />`;
  if (maskUrl) {
    maskImg.src = maskUrl;
    maskRow.hidden = false;
  } else {
    maskRow.hidden = true;
    maskImg.removeAttribute('src');
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
  setStatus('Running pipeline… (~10–20s)');
  const t0 = performance.now();
  try {
    const res = await fetch('/api/insert', { method: 'POST', body: formData });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    const json = await res.json();

    // Fetch the actual image from the one-shot URL the server issued.
    const compositeRes = await fetch(json.composite_url);
    if (!compositeRes.ok) throw new Error('composite fetch failed');
    const blob = await compositeRes.blob();
    lastComposite = blob;

    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    setStatus(`Done in ${elapsed}s.`);
    const label = kind === 'initial'
      ? truncate(instructionEl.value, 60)
      : truncate(refineInput.value, 60);
    renderResult(blob, label, kind, json.mask_url);
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
  if (polygonPoints.length >= 3) {
    fd.append('polygon', JSON.stringify(polygonPoints));
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
  // Refine intentionally drops the polygon — refinement is about
  // iterating on a result, not re-specifying the placement region.
  callPipeline(fd, 'refine');
});

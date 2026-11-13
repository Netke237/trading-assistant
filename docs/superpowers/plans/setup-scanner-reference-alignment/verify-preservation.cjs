// Source accounting only; rendered checks and independent review are separate gates.
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const crypto = require('crypto');
const root = path.resolve(__dirname, '../../../..');
const baseline = JSON.parse(fs.readFileSync(path.join(__dirname, 'baseline-source.json')));
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const normalize = text => text.replace(/\s+/g, ' ').trim();
const files = baseline.files.map(file => {
  const source = fs.readFileSync(path.join(root, file.file), 'utf8');
  return { file: file.file, baselineSha256: file.sha256, currentSha256: hash(source),
    unchanged: file.sha256 === hash(source), source };
});
const allSource = normalize(files.map(file => file.source).join('\n'));
const records = baseline.files.flatMap(file => file.records);
const texts = [...new Set(records.filter(record => record.kind === 'JsxText')
  .map(record => normalize(record.source)).filter(Boolean))];
const handlers = records.filter(record => record.kind === 'JsxAttribute' && /^on[A-Z]/.test(record.source));
const page = files.find(file => file.file.endsWith('/page.tsx'));
const original = cp.execFileSync('git', ['show', `${baseline.baseline}:${page.file}`], { cwd: root, encoding: 'utf8' });
const boundary = '  const chartShell =';
const report = {
  baseline: baseline.baseline,
  scope: 'Source accounting; not independent audit or proof of every rendered state',
  inventoryRecords: records.length,
  modules: files.map(({ source, ...record }) => record),
  controllerAndSelectionBeforeChartUnchanged: original.includes(boundary) && page.source.includes(boundary)
    && original.slice(0, original.indexOf(boundary)) === page.source.slice(0, page.source.indexOf(boundary)),
  uniqueJsxTextUnits: texts.length,
  missingText: texts.filter(text => !allSource.includes(text)),
  eventHandlerAttributes: handlers.length,
  missingHandlerAttributes: handlers.filter(record => !allSource.includes(normalize(record.source))).map(record => record.id),
  fullComponentContentRetained: files.filter(file => file !== page).every(file => file.unchanged),
  styleSha256: hash(fs.readFileSync(path.join(root, page.file.replace('page.tsx', 'page.module.css')))),
  permittedPresentationRenames: ['Generic Confidence headers now identify Setup, Historical signal and Fib proximity confidence'],
};
fs.writeFileSync(path.join(__dirname, 'source-preservation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ inventoryRecords: report.inventoryRecords, unchangedProtectedModules: files.filter(file => file.unchanged).length,
  controllerUnchanged: report.controllerAndSelectionBeforeChartUnchanged, uniqueText: texts.length,
  missingText: report.missingText, handlers: handlers.length, missingHandlers: report.missingHandlerAttributes }));
if (!report.controllerAndSelectionBeforeChartUnchanged || !report.fullComponentContentRetained
  || report.missingText.length || report.missingHandlerAttributes.length) process.exitCode = 1;

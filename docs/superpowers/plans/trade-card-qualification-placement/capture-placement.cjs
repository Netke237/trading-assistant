// Reuse the existing guarded mocked capture; limit this follow-up to qualifications.
const fs = require('fs');
const path = require('path');
const Module = require('module');
const source = path.resolve(__dirname, '../trade-card-reference-alignment/capture-aligned-layout.cjs');
let code = fs.readFileSync(source, 'utf8');
code = code.replace("const STATES = ['initial', 'calculated', 'mc+arithmetic', 'barrier-race', 'selected-target'];", "const STATES = ['initial', 'identity', 'qualifications-expanded'];");
const start = code.indexOf("  await shot('exit-plan'");
const end = code.indexOf('  await context.close();', start);
if (start < 0 || end < 0) throw new Error('Capture insertion points changed');
const checks = "  const identity = page.getByRole('region', { name: 'Selected stock and contract', exact: true });\n  const stock = page.getByRole('button', { name: /Stock Qualification/ });\n  const contract = page.getByRole('button', { name: /Contract Qualification/ });\n  assert(await stock.count() === 1 && await contract.count() === 1, 'exactly one stock and one contract qualification');\n  assert(await identity.getByRole('button', { name: /Contract Qualification/ }).count() === 1, 'contract qualification within identity');\n  assert(await stock.getAttribute('aria-expanded') === 'false', 'stock qualification defaults collapsed');\n  assert(await contract.getAttribute('aria-expanded') === 'false', 'contract qualification defaults collapsed');\n  const adjacent = await identity.evaluate(el => {\n    const stock = [...el.querySelectorAll('button')].find(b => b.textContent.includes('Stock Qualification')).closest('section');\n    const contract = [...el.querySelectorAll('button')].find(b => b.textContent.includes('Contract Qualification')).closest('section');\n    const details = el.querySelector('[aria-label=\"Contract Details\"]');\n    return details.nextElementSibling === stock && stock.nextElementSibling === contract;\n  });\n  assert(adjacent, 'Contract Details -> Stock Qualification -> Contract Qualification, adjacent');\n  await stock.click();\n  await contract.click();\n  assert(await identity.getByText('Stock Scorecard', { exact: true }).isVisible(), 'expanded stock scorecard remains visible');\n  assert(await identity.getByText('Contract \u2014 ' + card.contract, { exact: true }).isVisible(), 'expanded contract scorecard remains visible');\n  assert(await identity.getByRole('progressbar').count() === 10, 'all ten original score bars remain');\n  await shot('qualifications-expanded', identity);\n  await stock.click();\n  await contract.click();\n  await shot('identity-collapsed', identity);\n  assert(await computeReqs() === 0, 'qualification toggles run no Monte Carlo or Arithmetic calculation');\n  assert(log.mockedWrites.length === 0 && log.blockedWrites.length === 0, 'no save or order attempted');\n  assert(log.pageErrors.length === 0, 'no browser page errors');\n";
code = code.slice(0, start) + checks + code.slice(end);
const capture = new Module(source);
capture.filename = source;
capture.paths = Module._nodeModulePaths(path.dirname(source));
capture._compile(code, source);

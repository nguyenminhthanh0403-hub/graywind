#!/usr/bin/env node
// Rerunnable extractor: pulls NODES, LINKS, PLUMBING_LINKS out of a Bullion
// map HTML file (real JS object literals, not JSON) by locating each
// top-level `const NAME = ...` declaration with a string-aware bracket
// counter, then evaluating the literal in a VM sandbox. Writes flattened
// grounding JSON for MAVIS's keyword-retrieval step.
//
// Merge rule for LINKS/PLUMBING_LINKS mirrors the app's own runtime merge
// (bullion_mkultra.html, "MERGE PLUMBING INTO THE GRAPH"): a plumbing edge
// supersedes an existing LINKS edge on the same (s, t) pair, else appends.
const fs = require('fs');
const vm = require('vm');

const [, , htmlPath, outPath] = process.argv;
if (!htmlPath || !outPath) {
  console.error('usage: extract_bullion_grounding.js <path-to-bullion-html> <out.json>');
  process.exit(1);
}

const src = fs.readFileSync(htmlPath, 'utf8');

function extractDecl(varName) {
  const startRe = new RegExp(`const ${varName} = `);
  const startMatch = startRe.exec(src);
  if (!startMatch) throw new Error(`${varName} not found`);
  const i0 = startMatch.index + startMatch[0].length;
  const openChar = src[i0];
  const closeChar = openChar === '[' ? ']' : '}';
  if (openChar !== '[' && openChar !== '{') {
    throw new Error(`${varName} does not start with [ or {`);
  }
  let depth = 0;
  let inStr = null;
  let escaped = false;
  let end = -1;
  for (let j = i0; j < src.length; j++) {
    const c = src[j];
    if (inStr) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === inStr) inStr = null;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { inStr = c; continue; }
    if (c === openChar) depth++;
    else if (c === closeChar) {
      depth--;
      if (depth === 0) { end = j + 1; break; }
    }
  }
  if (end === -1) throw new Error(`unterminated ${varName}`);
  return src.slice(i0, end);
}

const context = {};
vm.createContext(context);

const NODES = vm.runInContext(`(${extractDecl('NODES')})`, context);
const LINKS = vm.runInContext(`(${extractDecl('LINKS')})`, context);
const PLUMBING_LINKS = vm.runInContext(`(${extractDecl('PLUMBING_LINKS')})`, context);

const mergedLinks = [...LINKS];
for (const pl of PLUMBING_LINKS) {
  const i = mergedLinks.findIndex(l => l.s === pl.s && l.t === pl.t);
  if (i >= 0) mergedLinks[i] = pl;
  else mergedLinks.push(pl);
}

const grounding = {
  generated_at: new Date().toISOString(),
  source: htmlPath,
  nodes: NODES.map(n => ({
    id: n.id,
    label: n.label,
    group: n.group,
    beginner: n.beginner || [],
    expert: n.expert || [],
  })),
  links: mergedLinks.map(l => ({
    s: l.s,
    t: l.t,
    sign: l.sign,
    conf: l.conf,
    why: l.why,
    stat: l.stat,
    fieldNote: l.fieldNote || null,
  })),
};

fs.writeFileSync(outPath, JSON.stringify(grounding, null, 2));
console.log(`Wrote ${grounding.nodes.length} nodes, ${grounding.links.length} links -> ${outPath}`);

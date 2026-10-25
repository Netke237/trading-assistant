'use strict';

/**
 * census.cjs — React Fiber live tree census and component attribution verifier.
 *
 * Requirements:
 * - Reach HostRoot from any connected node via fiber.return or fiber.stateNode.current.
 * - Always traverse HostRoot.stateNode.current, NOT the stale alternate.
 * - Walk child/sibling links including renderless components (e.g. KeyboardShortcuts).
 * - Unwrap memo and forwardRef to extract component names; record unresolved/missing/lazy names explicitly.
 * - Record connected host DOM nodes with stable per-observation opaque node IDs.
 * - Unsupported React internals fail the census explicitly.
 * - Disconnected nodes and stale alternates cannot credit a native.
 * - Support both browser execution (in page context via page.evaluate) and exportable pure fiber traversal.
 */

function compactText(s) {
  if (!s || typeof s !== 'string') return '';
  return s.replace(/\s+/g, ' ').trim().slice(0, 280);
}

function unwrapComponentType(type) {
  if (!type) {
    return { name: null, status: 'unresolved', reason: 'missing-type' };
  }
  if (typeof type === 'string') {
    return { name: type, status: 'host-tag' };
  }

  let current = type;
  let displayName = null;

  while (current && typeof current === 'object') {
    if (current.displayName) displayName = current.displayName;
    if (current.$$typeof === Symbol.for('react.memo') || current.type) {
      current = current.type;
      continue;
    }
    if (current.$$typeof === Symbol.for('react.forward_ref') || current.render) {
      current = current.render;
      continue;
    }
    if (current.$$typeof === Symbol.for('react.lazy')) {
      return { name: displayName, status: 'unresolved', reason: 'lazy-component' };
    }
    break;
  }

  if (typeof current === 'function') {
    const name = displayName || current.displayName || current.name || null;
    if (name) {
      return { name, status: 'resolved' };
    }
    return { name: null, status: 'unresolved', reason: 'anonymous-component' };
  }

  if (displayName) {
    return { name: displayName, status: 'resolved' };
  }

  return { name: null, status: 'unresolved', reason: 'unrecognized-component-type' };
}

function findConnectedFiberRoot(domNode) {
  if (!domNode || typeof domNode !== 'object') {
    throw new Error('unsupported-react-internals: target is not a DOM object');
  }
  if (domNode.isConnected === false) {
    throw new Error('disconnected-node: starting node is disconnected from DOM');
  }

  // Look for React internal properties on this element or its descendants
  function getFiber(el) {
    for (const key of Object.keys(el)) {
      if (key.startsWith('__reactFiber$')) return el[key];
      if (key.startsWith('__reactContainer$')) {
        const container = el[key];
        if (container && container.current) return container.current;
      }
    }
    return null;
  }

  let fiber = getFiber(domNode);
  if (!fiber && domNode.querySelectorAll) {
    const children = domNode.querySelectorAll('*');
    for (const child of children) {
      if (child.isConnected === false) continue;
      fiber = getFiber(child);
      if (fiber) break;
    }
  }

  if (!fiber) {
    throw new Error('unsupported-react-internals: no React fiber found on connected DOM tree');
  }

  return getAuthoritativeHostRoot(fiber);
}

function getAuthoritativeHostRoot(fiber) {
  if (!fiber || typeof fiber !== 'object') {
    throw new Error('unsupported-react-internals: fiber is null or invalid');
  }

  // If passed a FiberRootNode (which has .current)
  if (fiber.current && (fiber.current.tag === 3 || fiber.current._isHostRoot)) {
    return fiber.current;
  }

  // Navigate up to HostRoot via .return
  let curr = fiber;
  const visited = new Set();
  while (curr.return) {
    if (visited.has(curr)) {
      throw new Error('unsupported-react-internals: cyclic return reference in fiber tree');
    }
    visited.add(curr);
    curr = curr.return;
  }

  // If curr has stateNode.current (standard React HostRoot)
  if (curr.stateNode && curr.stateNode.current) {
    return curr.stateNode.current;
  }

  // If curr itself is marked as HostRoot
  if (curr.tag === 3 || curr._isHostRoot) {
    return curr;
  }

  throw new Error('unsupported-react-internals: root fiber missing stateNode.current or tag 3');
}

function isCustomComponentFiber(fiber) {
  if (!fiber || !fiber.type) return false;
  if (typeof fiber.type === 'string') return false; // HostComponent (tag name)
  if (fiber.tag === 5 || fiber.tag === 6 || fiber.tag === 7) return false; // Host, Text, Fragment
  // React WorkTags: 0: Function, 1: Class, 2: Indeterminate, 11: ForwardRef, 14: Memo, 15: SimpleMemo
  if (typeof fiber.type === 'function') return true;
  if (typeof fiber.type === 'object') {
    const typeofSym = fiber.type.$$typeof;
    if (
      typeofSym === Symbol.for('react.memo') ||
      typeofSym === Symbol.for('react.forward_ref') ||
      typeofSym === Symbol.for('react.lazy')
    ) {
      return true;
    }
  }
  return false;
}

function extractCensusFromFiber(rootOrFiber, options = {}) {
  const hostRoot = getAuthoritativeHostRoot(rootOrFiber);
  if (!hostRoot) {
    throw new Error('unsupported-react-internals: could not reach authoritative HostRoot');
  }

  const components = [];
  const hostNodes = [];
  const mountedNamesSet = new Set();
  const componentCounts = {};
  let fiberCounter = 0;
  let hostNodeCounter = 0;

  // DFS traversal using child and sibling links
  function traverse(fiber, ancestorComponents) {
    if (!fiber) return;

    let nextAncestors = ancestorComponents;
    let currentComponentRecord = null;

    if (isCustomComponentFiber(fiber)) {
      const unwrapped = unwrapComponentType(fiber.type);
      const fiberId = `fiber:${++fiberCounter}`;
      const name = unwrapped.name || (unwrapped.status === 'unresolved' ? `[Unresolved: ${unwrapped.reason}]` : null);

      currentComponentRecord = {
        fiber_id: fiberId,
        name: unwrapped.name,
        status: unwrapped.status,
        reason: unwrapped.reason || null,
        parent_component: ancestorComponents.length ? ancestorComponents[0].name : null,
        custom_ancestors: ancestorComponents.map(c => c.name).filter(Boolean),
        host_node_ids: [],
      };

      components.push(currentComponentRecord);
      if (unwrapped.name) {
        mountedNamesSet.add(unwrapped.name);
        componentCounts[unwrapped.name] = (componentCounts[unwrapped.name] || 0) + 1;
      }
      nextAncestors = [currentComponentRecord, ...ancestorComponents];
    } else if (typeof fiber.type === 'string' || fiber.tag === 5) {
      // HostComponent (DOM element)
      const dom = fiber.stateNode;
      const isConnected = dom ? (dom.isConnected !== false) : false;

      // "Record only connected host nodes, with stable per-observation opaque node IDs."
      // "Disconnected nodes and stale alternates cannot credit a native."
      if (isConnected) {
        const nodeId = `node:${++hostNodeCounter}`;
        const tagName = (dom.tagName || fiber.type || '').toLowerCase();

        // Extract attributes
        const attributes = {};
        if (dom.attributes) {
          if (Array.isArray(dom.attributes)) {
            for (const attr of dom.attributes) {
              if (attr && attr.name) attributes[attr.name] = String(attr.value || '');
            }
          } else if (typeof dom.attributes === 'object') {
            for (const [k, v] of Object.entries(dom.attributes)) {
              if (v && typeof v === 'object' && v.name && v.value !== undefined) {
                attributes[v.name] = String(v.value);
              } else if (typeof v === 'string' || typeof v === 'number') {
                attributes[k] = String(v);
              }
            }
          }
        }
        if (dom.id && !attributes.id) attributes.id = dom.id;
        if (dom.className && !attributes.class) attributes.class = dom.className;

        const text = compactText(dom.textContent || dom.innerText || '');

        const hostNodeRecord = {
          id: nodeId,
          tag: tagName,
          attributes,
          text,
          component_name: ancestorComponents.length ? ancestorComponents[0].name : null,
          custom_ancestors: ancestorComponents.map(c => c.name).filter(Boolean),
          is_connected: true,
        };

        hostNodes.push(hostNodeRecord);

        // Credit to the immediate custom component ancestor
        if (ancestorComponents.length) {
          ancestorComponents[0].host_node_ids.push(nodeId);
        }
      }
    }

    // Traverse children
    let child = fiber.child;
    const childVisited = new Set();
    while (child) {
      if (childVisited.has(child)) {
        throw new Error('unsupported-react-internals: cyclic child reference in fiber tree');
      }
      childVisited.add(child);
      traverse(child, nextAncestors);
      child = child.sibling;
    }
  }

  // Start traversal from HostRoot
  traverse(hostRoot, []);

  const mounted_names = Array.from(mountedNamesSet).sort();
  const duplicate_names = Object.keys(componentCounts).filter(k => componentCounts[k] > 1).sort();

  return {
    status: 'ok',
    components,
    host_nodes: hostNodes,
    mounted_names,
    component_counts: componentCounts,
    duplicate_names,
  };
}

function collectCensus(domNodeOrFiber, options = {}) {
  if (!domNodeOrFiber) {
    throw new Error('unsupported-react-internals: input cannot be null or undefined');
  }

  // If DOM node (has nodeType or tagName)
  if (typeof domNodeOrFiber.nodeType === 'number' || typeof domNodeOrFiber.tagName === 'string') {
    const root = findConnectedFiberRoot(domNodeOrFiber);
    return extractCensusFromFiber(root, options);
  }

  // Otherwise assume fiber
  return extractCensusFromFiber(domNodeOrFiber, options);
}

/**
 * Self-contained client-side census extraction function to be executed inside Playwright page.evaluate()
 */
function browserCensusEvaluation() {
  function compactText(s) {
    if (!s || typeof s !== 'string') return '';
    return s.replace(/\s+/g, ' ').trim().slice(0, 280);
  }

  function unwrapComponentType(type) {
    if (!type) return { name: null, status: 'unresolved', reason: 'missing-type' };
    if (typeof type === 'string') return { name: type, status: 'host-tag' };
    let current = type;
    let displayName = null;
    while (current && typeof current === 'object') {
      if (current.displayName) displayName = current.displayName;
      if (current.$$typeof === Symbol.for('react.memo') || current.type) {
        current = current.type;
        continue;
      }
      if (current.$$typeof === Symbol.for('react.forward_ref') || current.render) {
        current = current.render;
        continue;
      }
      if (current.$$typeof === Symbol.for('react.lazy')) {
        return { name: displayName, status: 'unresolved', reason: 'lazy-component' };
      }
      break;
    }
    if (typeof current === 'function') {
      const name = displayName || current.displayName || current.name || null;
      if (name) return { name, status: 'resolved' };
      return { name: null, status: 'unresolved', reason: 'anonymous-component' };
    }
    if (displayName) return { name: displayName, status: 'resolved' };
    return { name: null, status: 'unresolved', reason: 'unrecognized-component-type' };
  }

  function getFiber(el) {
    for (const key of Object.keys(el)) {
      if (key.startsWith('__reactFiber$')) return el[key];
      if (key.startsWith('__reactContainer$')) {
        const c = el[key];
        if (c && c.current) return c.current;
      }
    }
    return null;
  }

  let fiber = getFiber(document.body);
  if (!fiber) {
    const all = document.querySelectorAll('*');
    for (let i = 0; i < all.length; i++) {
      if (!all[i].isConnected) continue;
      fiber = getFiber(all[i]);
      if (fiber) break;
    }
  }

  if (!fiber) {
    return { status: 'error', reason: 'unsupported-react-internals: no React fiber found' };
  }

  let curr = fiber;
  while (curr.return) curr = curr.return;
  const hostRoot = (curr.stateNode && curr.stateNode.current) ? curr.stateNode.current : curr;
  if (!hostRoot) {
    return { status: 'error', reason: 'unsupported-react-internals: could not reach HostRoot' };
  }

  const components = [];
  const hostNodes = [];
  const mountedNamesSet = new Set();
  const componentCounts = {};
  let fiberCounter = 0;
  let hostNodeCounter = 0;

  function isCustomComp(f) {
    if (!f || !f.type) return false;
    if (typeof f.type === 'string') return false;
    if (f.tag === 5 || f.tag === 6 || f.tag === 7) return false;
    if (typeof f.type === 'function') return true;
    if (typeof f.type === 'object') {
      const sym = f.type.$$typeof;
      if (sym === Symbol.for('react.memo') || sym === Symbol.for('react.forward_ref') || sym === Symbol.for('react.lazy')) {
        return true;
      }
    }
    return false;
  }

  function traverse(f, ancestors) {
    if (!f) return;
    let nextAncestors = ancestors;

    if (isCustomComp(f)) {
      const unwrapped = unwrapComponentType(f.type);
      const fiberId = 'fiber:' + (++fiberCounter);
      const record = {
        fiber_id: fiberId,
        name: unwrapped.name,
        status: unwrapped.status,
        reason: unwrapped.reason || null,
        parent_component: ancestors.length ? ancestors[0].name : null,
        custom_ancestors: ancestors.map(c => c.name).filter(Boolean),
        host_node_ids: [],
      };
      components.push(record);
      if (unwrapped.name) {
        mountedNamesSet.add(unwrapped.name);
        componentCounts[unwrapped.name] = (componentCounts[unwrapped.name] || 0) + 1;
      }
      nextAncestors = [record, ...ancestors];
    } else if (typeof f.type === 'string' || f.tag === 5) {
      const dom = f.stateNode;
      if (dom && dom.isConnected) {
        const nodeId = 'node:' + (++hostNodeCounter);
        const tagName = (dom.tagName || f.type || '').toLowerCase();
        const attributes = {};
        if (dom.attributes) {
          for (let i = 0; i < dom.attributes.length; i++) {
            const a = dom.attributes[i];
            attributes[a.name] = a.value;
          }
        }
        const text = compactText(dom.textContent || '');
        const hostRecord = {
          id: nodeId,
          tag: tagName,
          attributes,
          text,
          component_name: ancestors.length ? ancestors[0].name : null,
          custom_ancestors: ancestors.map(c => c.name).filter(Boolean),
          is_connected: true,
        };
        hostNodes.push(hostRecord);
        if (ancestors.length) {
          ancestors[0].host_node_ids.push(nodeId);
        }
      }
    }

    let ch = f.child;
    while (ch) {
      traverse(ch, nextAncestors);
      ch = ch.sibling;
    }
  }

  traverse(hostRoot, []);

  return {
    status: 'ok',
    components,
    host_nodes: hostNodes,
    mounted_names: Array.from(mountedNamesSet).sort(),
    component_counts: componentCounts,
    duplicate_names: Object.keys(componentCounts).filter(k => componentCounts[k] > 1).sort(),
  };
}

async function runCensusInPage(page) {
  const result = await page.evaluate(browserCensusEvaluation);
  if (result.status === 'error') {
    throw new Error(result.reason);
  }
  return result;
}

module.exports = {
  unwrapComponentType,
  findConnectedFiberRoot,
  getAuthoritativeHostRoot,
  extractCensusFromFiber,
  collectCensus,
  browserCensusEvaluation,
  runCensusInPage,
};

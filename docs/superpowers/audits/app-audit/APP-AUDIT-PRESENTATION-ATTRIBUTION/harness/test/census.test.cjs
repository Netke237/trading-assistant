'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  extractCensusFromFiber,
  unwrapComponentType,
  findConnectedFiberRoot,
  collectCensus,
} = require('../census.cjs');

test('census: current/alternate selection traverses stateNode.current, not stale alternate', () => {
  // Construct a synthetic FiberRoot with current and alternate trees.
  const staleComponentFiber = {
    tag: 0,
    type: function StaleComponent() {},
    child: {
      tag: 5,
      type: 'div',
      stateNode: { isConnected: true, tagName: 'DIV', attributes: {}, textContent: 'stale' },
      child: null,
      sibling: null,
    },
    sibling: null,
  };
  staleComponentFiber.child.return = staleComponentFiber;

  const alternateHostRoot = {
    tag: 3,
    _isHostRoot: true,
    child: staleComponentFiber,
    sibling: null,
    return: null,
    stateNode: null,
  };
  staleComponentFiber.return = alternateHostRoot;

  const activeComponentFiber = {
    tag: 0,
    type: function ActiveComponent() {},
    child: {
      tag: 5,
      type: 'main',
      stateNode: { isConnected: true, tagName: 'MAIN', attributes: { id: 'active-main' }, textContent: 'active' },
      child: null,
      sibling: null,
    },
    sibling: null,
  };
  activeComponentFiber.child.return = activeComponentFiber;

  const currentHostRoot = {
    tag: 3,
    _isHostRoot: true,
    child: activeComponentFiber,
    sibling: null,
    return: null,
    stateNode: null,
  };
  activeComponentFiber.return = currentHostRoot;

  const fiberRoot = {
    current: currentHostRoot,
  };
  currentHostRoot.stateNode = fiberRoot;
  alternateHostRoot.stateNode = fiberRoot;
  currentHostRoot.alternate = alternateHostRoot;
  alternateHostRoot.alternate = currentHostRoot;

  // Passing the alternateHostRoot or a child from the alternate tree must resolve
  // to currentHostRoot via stateNode.current.
  const census = extractCensusFromFiber(staleComponentFiber);
  assert.equal(census.status, 'ok');
  assert.ok(census.mounted_names.includes('ActiveComponent'));
  assert.equal(census.mounted_names.includes('StaleComponent'), false);
  assert.ok(census.host_nodes.some(n => n.tag === 'main' && n.text === 'active'));
  assert.equal(census.host_nodes.some(n => n.text === 'stale'), false);
});

test('census: unwraps memo and forwardRef to extract component names', () => {
  function RawComp() {}
  const MemoComp = {
    $$typeof: Symbol.for('react.memo'),
    type: RawComp,
    displayName: 'CustomMemoComp',
  };
  const RefComp = {
    $$typeof: Symbol.for('react.forward_ref'),
    render: function InnerRef(props, ref) {},
  };
  RefComp.render.displayName = 'CustomRefComp';

  const NestedComp = {
    $$typeof: Symbol.for('react.memo'),
    type: {
      $$typeof: Symbol.for('react.forward_ref'),
      render: function DeepInner() {},
    },
  };

  assert.equal(unwrapComponentType(MemoComp).name, 'CustomMemoComp');
  assert.equal(unwrapComponentType(RefComp).name, 'CustomRefComp');
  assert.equal(unwrapComponentType(NestedComp).name, 'DeepInner');
});

test('census: records missing, anonymous and lazy component names explicitly as unresolved', () => {
  const anonymousFn = () => {};
  Object.defineProperty(anonymousFn, 'name', { value: '' });

  const lazyComp = {
    $$typeof: Symbol.for('react.lazy'),
    _payload: {},
  };

  const anonRes = unwrapComponentType(anonymousFn);
  assert.equal(anonRes.status, 'unresolved');
  assert.equal(anonRes.reason, 'anonymous-component');

  const lazyRes = unwrapComponentType(lazyComp);
  assert.equal(lazyRes.status, 'unresolved');
  assert.equal(lazyRes.reason, 'lazy-component');

  const nullRes = unwrapComponentType(null);
  assert.equal(nullRes.status, 'unresolved');
});

test('census: walks child/sibling links including renderless components (e.g. KeyboardShortcuts)', () => {
  function KeyboardShortcuts() {}
  function Sidebar() {}

  const root = {
    tag: 3,
    _isHostRoot: true,
    child: {
      tag: 0,
      type: KeyboardShortcuts,
      child: null, // renderless!
      sibling: {
        tag: 0,
        type: Sidebar,
        child: {
          tag: 5,
          type: 'aside',
          stateNode: { isConnected: true, tagName: 'ASIDE', attributes: {}, textContent: 'sidebar' },
          child: null,
          sibling: null,
        },
        sibling: null,
      },
    },
    return: null,
  };
  root.child.return = root;
  root.child.sibling.return = root;
  root.child.sibling.child.return = root.child.sibling;
  root.stateNode = { current: root };

  const census = extractCensusFromFiber(root);
  assert.ok(census.mounted_names.includes('KeyboardShortcuts'));
  assert.ok(census.mounted_names.includes('Sidebar'));
  const ks = census.components.find(c => c.name === 'KeyboardShortcuts');
  assert.ok(ks);
  assert.deepEqual(ks.host_node_ids, []);
});

test('census: duplicate component names are tracked with distinct entries and collisions flagged', () => {
  function Card() {}

  const root = {
    tag: 3,
    _isHostRoot: true,
    child: {
      tag: 0,
      type: Card,
      child: null,
      sibling: {
        tag: 0,
        type: Card,
        child: null,
        sibling: null,
      },
    },
    return: null,
  };
  root.child.return = root;
  root.child.sibling.return = root;
  root.stateNode = { current: root };

  const census = extractCensusFromFiber(root);
  const cards = census.components.filter(c => c.name === 'Card');
  assert.equal(cards.length, 2);
  assert.notEqual(cards[0].fiber_id, cards[1].fiber_id);
  assert.equal(census.component_counts['Card'], 2);
  assert.ok(census.duplicate_names.includes('Card'));
});

test('census: disconnected node and stale alternate cannot credit a native', () => {
  const disconnectedDom = {
    isConnected: false,
    tagName: 'DIV',
    __reactFiber$test: {
      tag: 5,
      return: null,
    },
  };

  assert.throws(
    () => findConnectedFiberRoot(disconnectedDom),
    /disconnected-node/
  );

  // If a HostComponent in tree has a disconnected DOM node, it must not be in host_nodes
  function Comp() {}
  const root = {
    tag: 3,
    _isHostRoot: true,
    child: {
      tag: 0,
      type: Comp,
      child: {
        tag: 5,
        type: 'button',
        stateNode: { isConnected: false, tagName: 'BUTTON', attributes: {}, textContent: 'ghost' },
        child: null,
        sibling: null,
      },
      sibling: null,
    },
    return: null,
  };
  root.child.return = root;
  root.child.child.return = root.child;
  root.stateNode = { current: root };

  const census = extractCensusFromFiber(root);
  assert.equal(census.host_nodes.length, 0);
  const comp = census.components.find(c => c.name === 'Comp');
  assert.deepEqual(comp.host_node_ids, []);
});

test('census: unsupported React internals fail the census explicitly', () => {
  assert.throws(
    () => extractCensusFromFiber({ invalid: true }),
    /unsupported-react-internals/
  );
  assert.throws(
    () => extractCensusFromFiber(null),
    /unsupported-react-internals/
  );
});

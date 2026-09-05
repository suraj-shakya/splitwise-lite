/* Splitwise Lite shell harness: runs the shipped app/ files and asserts what a
   person would see.

   Why this exists. Task 9a's test for a refused sign-in sliced the body of
   submitted() out of app/app.js and asserted substrings against that slice. The
   defect it was written to pin is an ordering defect spread across three functions in
   two files, announce() in api.js and showGate() and submitted() in app.js, so a test
   that reads the text of one of them cannot see it by construction. Two mutants prove
   it: both reintroduce the defect and leave the sliced function byte-identical, and
   the structural test passed both.

   The two mutants this harness is measured against, applied to the real source at run
   time as anchored substitutions and never committed as copies:

     A. app/app.js, inside show():  gate.hidden = which !== 'gate';
        gains                       gateError.hidden = true;
     B. app/api.js, inside announce(): handlers.unauthenticated(error);
        becomes  setTimeout(function () { handlers.unauthenticated(error); }, 0);

   Mutant B is only visible once the timer queue has drained, not just the microtask
   queue, which is why settle() drains both.

   What stays browser-only. The harness must not pretend to cover any of this, and no
   scenario is named as if it did. These stay on the hand checklist in
   plans/tasks/09a-application-server-and-http-api.md:

     * Service worker registration, activation, scope, skipWaiting, clients.claim and
       the /api bypass. The stub navigator deliberately has no serviceWorker.
     * Cache Storage: what is in it, that there is one cache, and that bumping VERSION
       clears the old ones.
     * Installability: manifest parsing, the install affordance, launching standalone,
       and whether an installed window shares the browser's cookie jar.
     * Offline reload of the document itself. This stubs fetch, not a lost network.
     * Real cookie enforcement. HttpOnly, SameSite and Secure are a browser's job, not
       a fake document.cookie's.
     * Console cleanliness in a real browser, including the service worker warning path
       this never enters.
     * Focus actually announcing a screen. focus() being called is recorded here;
       whether a screen reader says anything is a different question.
     * Layout: viewport, safe area insets, hit areas, font sizes, iOS auto-zoom.
     * A disabled button really refusing a second click. Handlers are dispatched
       directly here, so that cannot be proven and is not claimed.

   Usage. pytest drives this through tests/test_shell_behaviour.py, passing a JSON
   configuration on stdin and reading one JSON report from stdout. To run it by hand
   against the unmodified files:

       node tests/shell_harness.mjs < /dev/null

   Exit status is 0 when every requested scenario passed, 1 when one or more failed,
   and 2 for a harness error: unparseable stdin, an anchor that did not match exactly
   once, a missing file, a script that threw while loading, or a run that would not
   quiesce. The 1 and 2 distinction is not decoration: the mutant tests assert exit 1
   so that a substitution which broke a file into a syntax error cannot be mistaken
   for a killed mutant. */

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

/* Files are found from this file's own location, never from the working directory,
   matching every other test file in this repo. */
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..');
const APP = join(REPO, 'app');

/* The error codes the response fixtures name. They are the real ones, and
   tests/test_shell_behaviour.py asserts each appears in src/splitwise_lite/web.py, so
   a fixture cannot drift away from the contract it is imitating. */
const CODES = {
  authenticationFailed: 'authentication_failed',
  memberNotLinked: 'member_not_linked',
  internalError: 'internal_error'
};

/* A harness error, as opposed to a scenario failure: the run itself is broken, so it
   exits 2 and reports nothing. */
class HarnessError extends Error {}

/* --- The document ---------------------------------------------------------- */

/* index.html is parsed rather than declared, so a renamed id is a loud harness
   failure instead of a hand-written stub that quietly drifts from the document the
   browser loads. */
const VOID_TAGS = new Set([
  'area',
  'base',
  'br',
  'col',
  'embed',
  'hr',
  'img',
  'input',
  'link',
  'meta',
  'param',
  'source',
  'track',
  'wbr'
]);

const ATTRIBUTE = /([a-zA-Z][a-zA-Z0-9:_.-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;

function element(tag, attributes, sink) {
  const own = {
    tagName: tag.toUpperCase(),
    attributes: attributes,
    childNodes: [],
    /* Every element carries these because a browser's does; they stay null unless a
       shipped file assigns a loader callback to a <script> it created. */
    onload: null,
    onerror: null,
    src: attributes.src === undefined ? '' : attributes.src,
    /* The value property is not reflected back to the attribute, which is what a
       browser does once a field has been typed into. */
    value: attributes.value === undefined ? '' : attributes.value,
    disabled: attributes.disabled !== undefined,

    get hidden() {
      return own.attributes.hidden !== undefined;
    },
    set hidden(on) {
      if (on) {
        own.attributes.hidden = '';
      } else {
        delete own.attributes.hidden;
      }
    },

    get textContent() {
      return own.childNodes
        .map((node) => (node.tagName === undefined ? node.text : node.textContent))
        .join('');
    },
    set textContent(text) {
      own.childNodes = [{ text: String(text) }];
    },

    getAttribute(name) {
      return own.attributes[name] === undefined ? null : own.attributes[name];
    },
    setAttribute(name, value) {
      own.attributes[name] = String(value);
    },
    removeAttribute(name) {
      delete own.attributes[name];
    },
    appendChild(child) {
      own.childNodes.push(child);
      return child;
    },
    removeChild(child) {
      const at = own.childNodes.indexOf(child);
      if (at === -1) {
        throw new Error('removeChild was given a node that is not a child');
      }
      own.childNodes.splice(at, 1);
      return child;
    },
    replaceChildren(...nodes) {
      own.childNodes = nodes.slice();
    },
    get firstChild() {
      return own.childNodes.length === 0 ? null : own.childNodes[0];
    },
    addEventListener(type, handler) {
      const listeners = own.listeners[type] || [];
      listeners.push(handler);
      own.listeners[type] = listeners;
    },
    focus() {
      /* Recorded rather than acted on, so a scenario can assert which element the
         app moved focus to. Whether a screen reader announces it is browser-only. */
      sink.focused = own.self;
    },
    querySelector(selector) {
      return select(own, selector)[0] || null;
    },
    querySelectorAll(selector) {
      return select(own, selector);
    },
    listeners: {},
    classList: (attributes.class || '').split(/\s+/).filter(Boolean)
  };
  /* Everything else holds the guarded view, so the element hands that back rather
     than its raw target and an identity comparison in a scenario means what it says. */
  own.self = guarded(own, 'element <' + tag + '>');
  return own.self;
}

/* Anything a shipped file reaches for that the stub does not provide throws with a
   message naming it, rather than returning undefined and producing a confusing
   failure three steps later. */
function guarded(target, what) {
  return new Proxy(target, {
    get(object, property) {
      if (typeof property === 'symbol' || property in object) {
        return object[property];
      }
      throw new Error(
        'the stub ' + what + ' has no ' + String(property) + '; the harness fakes ' +
          'only what a shipped file uses, so widen it deliberately'
      );
    }
  });
}

function parseDocument(html, sink) {
  const root = element('#document', {}, sink);
  const stack = [root];
  const byId = new Map();
  let index = 0;

  const top = () => stack[stack.length - 1];
  const addText = (text) => {
    if (text !== '') {
      top().childNodes.push({ text: text });
    }
  };

  while (index < html.length) {
    const open = html.indexOf('<', index);
    if (open === -1) {
      addText(html.slice(index));
      break;
    }
    addText(html.slice(index, open));
    if (html.startsWith('<!--', open)) {
      const close = html.indexOf('-->', open);
      if (close === -1) {
        throw new HarnessError('app/index.html has an unterminated comment');
      }
      index = close + 3;
      continue;
    }
    if (html.startsWith('<!', open)) {
      index = html.indexOf('>', open) + 1;
      continue;
    }
    const close = html.indexOf('>', open);
    if (close === -1) {
      throw new HarnessError('app/index.html has an unterminated tag');
    }
    let raw = html.slice(open + 1, close);
    index = close + 1;
    if (raw.startsWith('/')) {
      const name = raw.slice(1).trim().toLowerCase();
      if (top().tagName !== name.toUpperCase()) {
        throw new HarnessError(
          'app/index.html closes </' + name + '> inside <' + top().tagName + '>'
        );
      }
      stack.pop();
      continue;
    }
    const selfClosing = raw.endsWith('/');
    if (selfClosing) {
      raw = raw.slice(0, -1);
    }
    const space = raw.search(/\s/);
    const tag = (space === -1 ? raw : raw.slice(0, space)).toLowerCase();
    const attributes = {};
    if (space !== -1) {
      ATTRIBUTE.lastIndex = 0;
      let found = ATTRIBUTE.exec(raw.slice(space));
      while (found !== null) {
        const value = found[2] !== undefined ? found[2] : found[3] !== undefined ? found[3] : found[4];
        attributes[found[1]] = value === undefined ? '' : value;
        found = ATTRIBUTE.exec(raw.slice(space));
      }
    }
    const node = element(tag, attributes, sink);
    top().childNodes.push(node);
    if (attributes.id !== undefined) {
      if (byId.has(attributes.id)) {
        throw new HarnessError('app/index.html has two elements with id ' + attributes.id);
      }
      byId.set(attributes.id, node);
    }
    if (!selfClosing && !VOID_TAGS.has(tag)) {
      stack.push(node);
    }
  }
  return { root: root, byId: byId };
}

/* Exactly the four selector shapes app.js uses: #id, .class, ".class tag" and a bare
   tag scoped to an element. Anything else throws rather than returning null, so a
   screen task that introduces an attribute selector breaks the harness visibly and
   someone widens it deliberately. */
function simple(part, selector) {
  if (/^#[A-Za-z][\w-]*$/.test(part)) {
    return { kind: 'id', value: part.slice(1) };
  }
  if (/^\.[A-Za-z][\w-]*$/.test(part)) {
    return { kind: 'class', value: part.slice(1) };
  }
  if (/^[a-z][a-z0-9]*$/.test(part)) {
    return { kind: 'tag', value: part };
  }
  throw new Error(unsupported(selector));
}

function unsupported(selector) {
  return (
    'the stub supports #id, .class, ".class tag" and a bare tag; it cannot handle ' +
    JSON.stringify(selector)
  );
}

function matches(node, part) {
  if (part.kind === 'id') {
    return node.attributes.id === part.value;
  }
  if (part.kind === 'class') {
    return node.classList.indexOf(part.value) !== -1;
  }
  return node.tagName === part.value.toUpperCase();
}

function descendants(node, found) {
  node.childNodes.forEach((child) => {
    if (child.tagName !== undefined) {
      found.push(child);
      descendants(child, found);
    }
  });
  return found;
}

function select(root, selector) {
  const parts = String(selector).trim().split(/\s+/);
  if (parts.length > 2) {
    throw new Error(unsupported(selector));
  }
  const steps = parts.map((part) => simple(part, selector));
  if (steps.length === 2 && (steps[0].kind !== 'class' || steps[1].kind !== 'tag')) {
    throw new Error(unsupported(selector));
  }
  const all = descendants(root, []);
  const first = all.filter((node) => matches(node, steps[0]));
  if (steps.length === 1) {
    return first;
  }
  const found = [];
  first.forEach((node) => {
    descendants(node, []).forEach((child) => {
      if (matches(child, steps[1]) && found.indexOf(child) === -1) {
        found.push(child);
      }
    });
  });
  return found;
}

/* --- Response fixtures ------------------------------------------------------ */

/* The shapes web.py actually returns. A response is answered to api.js, which reads
   status, ok and json() and nothing else. */
function ok(payload) {
  return { status: 200, ok: true, json: () => Promise.resolve(payload) };
}

function failure(status, code, message) {
  return {
    status: status,
    ok: false,
    json: () => Promise.resolve({ error: { code: code, message: message } })
  };
}

function unreadable(status) {
  /* A body that is not JSON: api.js swallows this into a null payload and an
     ApiError with an empty message. */
  return {
    status: status,
    ok: false,
    json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON'))
  };
}

function noContent() {
  /* A 204 has no body, so api.js must return null without ever calling json(). The
     count is on the response itself, so the scenario that registers it can assert it
     stayed at zero. */
  const response = {
    status: 204,
    ok: true,
    jsonCalls: 0,
    json: () => {
      response.jsonCalls += 1;
      throw new Error('json() was called on a 204 response');
    }
  };
  return response;
}

function networkFailure() {
  /* fetch itself rejects, which is what a real fetch does when the request never
     gets an answer. */
  return { rejectWith: () => new TypeError('Failed to fetch') };
}

/* --- One scenario ----------------------------------------------------------- */

const SETTLE_STEPS = 1000;

function page(scripts, name, provokeRunawayTimer) {
  const sink = { focused: null };
  const parsed = parseDocument(readFileSync(join(APP, 'index.html'), 'utf8'), sink);
  const failures = [];
  const calls = [];
  const answers = new Map();
  const consoleLines = [];
  const missing = new Set();
  const replaceStates = [];
  const pushStates = [];
  const windowEvents = [];
  const timers = [];
  let cookie = '';
  let sequence = 0;
  let declaredConsole = [];
  let declaredRequests = null;

  const byId = (id) => {
    const found = parsed.byId.get(id);
    if (found === undefined) {
      /* Never a silent null: a mistyped or renamed id is the one thing that turns
         the boot wiring into a blank page. */
      throw new HarnessError('app/index.html has no element with id ' + id);
    }
    return found;
  };

  const schedule = (handler, delay) => {
    sequence += 1;
    const timer = { id: sequence, at: Number(delay) || 0, order: sequence, handler: handler };
    timers.push(timer);
    return timer.id;
  };

  const setTimeoutStub = (handler, delay) => schedule(handler, delay);
  const clearTimeoutStub = (id) => {
    const at = timers.findIndex((timer) => timer.id === id);
    if (at !== -1) {
      timers.splice(at, 1);
    }
  };

  const runNextTimer = () => {
    /* The declared delay is ordering information only, never elapsed time: nothing
       here sleeps and no assertion reads the wall clock. Equal delays run in
       scheduling order. */
    let pick = 0;
    for (let index = 1; index < timers.length; index += 1) {
      const candidate = timers[index];
      const best = timers[pick];
      if (candidate.at < best.at || (candidate.at === best.at && candidate.order < best.order)) {
        pick = index;
      }
    }
    const timer = timers.splice(pick, 1)[0];
    timer.handler();
  };

  const loadScript = (node) => {
    const source = String(node.src);
    const path = join(APP, source);
    if (!path.startsWith(APP)) {
      throw new HarnessError('a script src escaped app/: ' + source);
    }
    /* A browser fetches the src and runs it as a macrotask, so api.js runs, then
       onload fires, then wire() runs. Doing it synchronously here would hide that
       ordering, which is exactly the kind of thing this harness exists to see. */
    schedule(() => {
      if (missing.has(source) || !existsSync(path)) {
        if (node.onerror) {
          node.onerror();
        }
        return;
      }
      const script = scripts.get(path);
      if (script === undefined) {
        throw new HarnessError('the harness has no compiled script for ' + source);
      }
      script.runInContext(sandbox);
      if (node.onload) {
        node.onload();
      }
    }, 0);
  };

  const head = select(parsed.root, 'head')[0];
  head.appendChild = (node) => {
    head.childNodes.push(node);
    if (node.tagName === 'SCRIPT' && node.src !== '') {
      loadScript(node);
    }
  };

  const titleElement = select(parsed.root, 'title')[0];
  const documentStub = guarded(
    {
      getElementById: byId,
      querySelector: (selector) => select(parsed.root, selector)[0] || null,
      querySelectorAll: (selector) => select(parsed.root, selector),
      createElement: (tag) => element(String(tag).toLowerCase(), {}, sink),
      head: head,
      get title() {
        return titleElement.textContent;
      },
      set title(text) {
        titleElement.textContent = text;
      },
      get cookie() {
        /* Read-only: no shipped file writes a cookie, and the session cookie is
           HttpOnly anyway. The scenario owns the jar. */
        return cookie;
      }
    },
    'document'
  );

  const fetchStub = (url, options) => {
    const method = String(options.method);
    const headers = {};
    Object.keys(options.headers || {}).forEach((key) => {
      headers[key] = options.headers[key];
    });
    calls.push({
      method: method,
      url: String(url),
      headers: headers,
      body: options.body === undefined ? null : String(options.body),
      credentials: options.credentials === undefined ? null : options.credentials
    });
    const key = method + ' ' + url;
    const queue = answers.get(key);
    if (queue === undefined || queue.length === 0) {
      /* Never served the next thing in a queue: a call nobody registered an answer
         for is a failure naming the method and the path, so a screen task that adds
         a call at boot fails loudly and has to register its answer.

         Recorded as a failure here rather than left to the throw below. api.js
         swallows a rejection in more than one place, and a guarantee that depends on
         an exception escaping a promise chain is not a guarantee: the throw alone
         would let a call made inside a .then() slip past silently. */
      const unregistered = 'no answer was registered for ' + key;
      failures.push(unregistered);
      throw new Error(unregistered);
    }
    /* One registered answer stands for every matching request; a list registered
       with respondInOrder is consumed in order and its last entry stands for
       anything after it. Every scenario asserts its exact request list, so a call
       nobody expected is caught there rather than being quietly served. */
    const answer = queue.length === 1 ? queue[0] : queue.shift();
    if (answer.rejectWith) {
      return Promise.reject(answer.rejectWith());
    }
    return Promise.resolve(answer);
  };

  const record = (method) => (...args) => {
    consoleLines.push(method + ': ' + args.map((arg) => String(arg)).join(' '));
  };

  const sandbox = {};
  vm.createContext(sandbox);
  /* window is the context's own global, as in a browser, so window.SplitwiseApi set
     by api.js is reachable as a bare SplitwiseApi from app.js. Assigning it from out
     here would make window a different object from globalThis. */
  vm.runInContext('globalThis.window = globalThis;', sandbox);
  sandbox.document = documentStub;
  sandbox.location = { hash: '' };
  sandbox.history = guarded(
    {
      replaceState: (state, title, url) => {
        replaceStates.push(String(url));
        sandbox.location.hash = String(url);
      },
      /* Present only so a scenario can assert it was never called: "replace, never
         push" is a decision task 8 made. */
      pushState: (state, title, url) => {
        pushStates.push(String(url));
      }
    },
    'history'
  );
  /* No serviceWorker property, so 'serviceWorker' in navigator is false and the
     registration branch is never entered. The harness does not pretend to cover
     service workers, and this is how it stays honest about that. */
  sandbox.navigator = {};
  sandbox.console = {
    log: record('log'),
    info: record('info'),
    warn: record('warn'),
    error: record('error'),
    debug: record('debug')
  };
  sandbox.setTimeout = setTimeoutStub;
  sandbox.clearTimeout = clearTimeoutStub;
  sandbox.fetch = fetchStub;
  const windowListeners = {};
  sandbox.addEventListener = (type, handler) => {
    windowEvents.push(String(type));
    const listeners = windowListeners[type] || [];
    listeners.push(handler);
    windowListeners[type] = listeners;
  };

  const drainMicrotasks = async () => {
    /* Returning to the event loop drains the microtask queue to empty, so two hops
       finish a chain that queued more work while the first drain was running.
       setImmediate is a Node global rather than an import, and nothing here sleeps. */
    await new Promise((done) => setImmediate(done));
    await new Promise((done) => setImmediate(done));
  };

  const settle = async () => {
    /* Bounded on purpose: a run that will not quiesce fails with the scenario's name
       rather than hanging the suite. */
    for (let step = 0; step < SETTLE_STEPS; step += 1) {
      await drainMicrotasks();
      if (timers.length === 0) {
        return;
      }
      runNextTimer();
    }
    throw new HarnessError(
      'settle() did not quiesce within ' + SETTLE_STEPS + ' steps in scenario ' + name
    );
  };

  const api = {
    /* --- setting a scenario up, before boot --- */
    respond(method, path, response) {
      answers.set(method + ' /api' + path, [response]);
    },
    respondInOrder(method, path, responses) {
      answers.set(method + ' /api' + path, responses.slice());
    },
    setCookie(text) {
      cookie = String(text);
    },
    startAt(hash) {
      sandbox.location.hash = String(hash);
    },
    absent(source) {
      /* The file is on disk; the scenario declares it absent so app.js's onerror
         path, which is real shipped code, gets a run. */
      missing.add(source);
    },
    expectConsole(lines) {
      declaredConsole = lines.slice();
    },
    expectRequests(list) {
      /* Every scenario declares the whole ordered list, and finish() fails one that
         does not. A recorded call the scenario never expected is then a failure even
         when the app swallowed the rejection it caused, and a call that stopped
         happening is a failure too. */
      declaredRequests = list.slice();
    },

    /* --- driving --- */
    async boot() {
      if (provokeRunawayTimer) {
        /* Harness-owned, and only when the configuration asks for it: a timer that
           reschedules itself, to prove settle() is bounded. */
        const again = () => schedule(again, 0);
        schedule(again, 0);
      }
      scripts.get(join(APP, 'app.js')).runInContext(sandbox);
      await settle();
    },
    async dispatch(node, type) {
      const event = {
        type: type,
        defaultPrevented: false,
        preventDefault() {
          event.defaultPrevented = true;
        }
      };
      (node.listeners[type] || []).forEach((handler) => handler(event));
      await settle();
      return event;
    },
    async dispatchWindow(type) {
      (windowListeners[type] || []).forEach((handler) => handler({ type: type }));
      await settle();
    },
    async goTo(hash) {
      /* What following a tab link does: the anchor changes the hash and the browser
         fires hashchange. No click handler is registered on a nav link. */
      sandbox.location.hash = String(hash);
      await api.dispatchWindow('hashchange');
    },

    /* --- looking --- */
    el: byId,
    query: (selector) => select(parsed.root, selector),
    get calls() {
      return calls;
    },
    get requests() {
      return calls.map((call) => call.method + ' ' + call.url);
    },
    get focused() {
      return sink.focused;
    },
    get hash() {
      return sandbox.location.hash;
    },
    get title() {
      return documentStub.title;
    },
    get replaceStates() {
      return replaceStates;
    },
    get pushStates() {
      return pushStates;
    },
    global(expression) {
      return vm.runInContext(expression, sandbox);
    },

    /* --- asserting --- */
    is(actual, expected, what) {
      if (actual !== expected) {
        failures.push(what + ': expected ' + show(expected) + ', got ' + show(actual));
      }
    },
    same(actual, expected, what) {
      const left = JSON.stringify(actual);
      const right = JSON.stringify(expected);
      if (left !== right) {
        failures.push(what + ': expected ' + right + ', got ' + left);
      }
    },
    ok(condition, what) {
      if (!condition) {
        failures.push(what);
      }
    },
    fail(message) {
      failures.push(message);
    },

    /* --- the record the runner reads --- */
    failures: failures,
    windowEvents: windowEvents,
    finish() {
      if (declaredRequests === null) {
        failures.push(
          'this scenario declared no expected requests; every scenario must call ' +
            'expectRequests, so a call nobody registered an answer for cannot slip ' +
            'through a promise chain that swallowed the rejection'
        );
      } else if (JSON.stringify(api.requests) !== JSON.stringify(declaredRequests)) {
        failures.push(
          'requests: expected ' + JSON.stringify(declaredRequests) + ', got ' +
            JSON.stringify(api.requests)
        );
      }
      /* Any console output a scenario did not declare is a failure: a warning nobody
         asked for is a change in behaviour. */
      if (JSON.stringify(consoleLines) !== JSON.stringify(declaredConsole)) {
        failures.push(
          'console output: expected ' + JSON.stringify(declaredConsole) + ', got ' +
            JSON.stringify(consoleLines)
        );
      }
    }
  };
  return api;
}

function show(value) {
  if (typeof value === 'string') {
    return JSON.stringify(value);
  }
  /* `in` rather than a property read, so a guarded stub that is not an element says
     so instead of throwing while a failure message is being written. */
  if (value && typeof value === 'object' && 'tagName' in value) {
    const id = value.attributes.id;
    return '<' + value.tagName.toLowerCase() + (id === undefined ? '' : ' id=' + id) + '>';
  }
  return String(value);
}

/* --- The scenarios ---------------------------------------------------------- */

const A_MEMBER = {
  account: { id: 'acc-1', email: 'sam@example.com', display_name: 'Sam' },
  group: { id: 'grp-1', name: 'Flat', currency: 'AUD' },
  member: { id: 'mem-1', display_name: 'Sam' }
};
const NO_MEMBER = {
  account: { id: 'acc-1', email: 'sam@example.com', display_name: 'Sam' },
  group: { id: 'grp-1', name: 'Flat', currency: 'AUD' },
  member: null
};
const REFUSED = 'Those details did not match an account.';
const SIGN_IN_FIRST = 'Sign in to continue.';

/* Tasks 11 and 12 landed after this harness was written, and both read as soon as the
   app frame appears: the feed loads the expenses and the roster, the balances screen
   loads the roster and the figures. Every scenario that reaches the app screen has to
   answer them, which is this harness working as intended rather than a burden, since a
   call nobody registered an answer for is a failure. These are the empty, valid shapes:
   those two tasks own the scenarios that assert what their screens draw, and this task
   still asserts only the gate, the notices, routing and the client. */
const EMPTY_FEED = { currency: 'AUD', expenses: [] };
const EMPTY_ROSTER = { members: [] };
const EMPTY_BALANCES = { net: [], transfers: [] };

function screensLoad(page) {
  page.respond('GET', '/expenses', ok(EMPTY_FEED));
  page.respond('GET', '/members', ok(EMPTY_ROSTER));
  page.respond('GET', '/balances', ok(EMPTY_BALANCES));
}

const refusal = (message) => failure(401, CODES.authenticationFailed, message);
const notLinked = () =>
  failure(403, CODES.memberNotLinked, 'Nobody has linked you to a member yet.');
const serverError = () => failure(500, CODES.internalError, 'Something went wrong.');

/* The name the document title carries, spelled out here rather than read back from
   app.js: an assertion that borrows the subject's own constant asserts nothing. */
const APP_NAME = 'Splitwise Lite';

async function signIn(page, email, password) {
  page.el('gate-email').value = email;
  page.el('gate-password').value = password;
  return page.dispatch(page.el('gate-form'), 'submit');
}

const SCREENS = ['screen-feed', 'screen-add', 'screen-balances'];

/* The methods that change nothing, so they carry no body, no content type and no CSRF
   token. Spelled out here rather than read from api.js's UNSAFE set: a request whose
   method the back end gates is exactly the one an assertion must not take on trust. */
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

function visibleScreens(page) {
  return SCREENS.filter((id) => !page.el(id).hidden);
}

function currentTabs(page) {
  return page
    .query('.tabbar a')
    .filter((tab) => tab.getAttribute('aria-current') !== null)
    .map((tab) => tab.getAttribute('href'));
}

/* Prose in index.html wraps, so a text node carries whatever newline and indentation
   the document happens to use. Collapsing runs of whitespace keeps a comparison exact
   without pinning where a line breaks, the way test_web_shell.py reads a paragraph. */
function flatText(node) {
  return node.textContent.replace(/\s+/g, ' ').trim();
}

/* The gate's standing copy. Nothing in app.js writes it, so a message that lands here
   instead of in #gate-error would otherwise pass unseen. */
const GATE_LEDE = 'Use the address whoever set the flat up linked to your name.';

/* setMode()'s four effects are one behaviour: what the gate says it is for. Asserting
   one of them leaves a create-account form headed "Sign in" with a "Sign in" button. */
const GATE_MODES = {
  'signing in': {
    title: 'Sign in',
    submit: 'Sign in',
    other: 'Create an account',
    autocomplete: 'current-password'
  },
  creating: {
    title: 'Create an account',
    submit: 'Create account',
    other: 'I already have an account',
    autocomplete: 'new-password'
  }
};

function gateReads(page, mode, what) {
  const expected = GATE_MODES[mode];
  page.is(flatText(page.el('gate-title')), expected.title, what + ': #gate-title text');
  page.is(
    flatText(page.el('gate-submit')),
    expected.submit,
    what + ': #gate-submit text'
  );
  page.is(flatText(page.el('gate-mode')), expected.other, what + ': #gate-mode text');
  page.is(
    page.el('gate-password').getAttribute('autocomplete'),
    expected.autocomplete,
    what + ': #gate-password autocomplete'
  );
}

/* The three curtains and the sign out control, always asserted together and never one
   at a time. A screen assertion that names only the curtain it expects leaves the other
   two free to be wrong, which is how a live tab bar ends up sitting over an empty
   frame on the offline screen. */
function curtains(page, which, what, signOutVisible) {
  page.is(page.el('gate').hidden, which !== 'gate', what + ': #gate hidden');
  page.is(page.el('notice').hidden, which !== 'notice', what + ': #notice hidden');
  page.is(
    page.query('.content')[0].hidden,
    which !== 'app',
    what + ': the app frame hidden'
  );
  page.is(
    page.query('.tabbar')[0].hidden,
    which !== 'app',
    what + ': the tab bar hidden'
  );
  page.is(page.el('sign-out').hidden, !signOutVisible, what + ': #sign-out hidden');
}

function gateIsUp(page, what) {
  /* showGate() hides the sign out control, and every route to the gate goes through
     it, so it is hidden whenever the gate is up. */
  curtains(page, 'gate', what, false);
  page.is(page.el('notice-unlinked').hidden, true, what + ': #notice-unlinked hidden');
  page.is(page.el('notice-offline').hidden, true, what + ': #notice-offline hidden');
  page.is(flatText(page.el('gate-lede')), GATE_LEDE, what + ': #gate-lede text');
}

function noticeIsUp(page, which, what, signOutVisible) {
  curtains(page, 'notice', what, signOutVisible);
  page.is(
    page.el('notice-unlinked').hidden,
    which !== 'unlinked',
    what + ': #notice-unlinked hidden'
  );
  page.is(
    page.el('notice-offline').hidden,
    which !== 'offline',
    what + ': #notice-offline hidden'
  );
  page.is(page.focused, page.el('notice-title'), what + ': focus');
}

function appIsUp(page, what) {
  curtains(page, 'app', what, true);
}

const SCENARIOS = [
  {
    name: 'boot_with_no_session_shows_the_gate',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      await page.boot();
      gateIsUp(page, 'no session');
      gateReads(page, 'signing in', 'no session');
      page.is(page.el('gate-error').hidden, true, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, '', '#gate-error text');
      page.is(page.focused, page.el('gate-title'), 'focus');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    name: 'boot_with_a_linked_session_shows_the_app',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      await page.boot();
      appIsUp(page, 'a linked session');
      /* No focus move on first load: the person has not navigated anywhere yet. */
      page.is(page.focused, null, 'focus');
      /* window is the context's own global, as in a browser, so what api.js hung off
         window is reachable as a bare global from app.js. */
      page.is(page.global('window === globalThis'), true, 'window === globalThis');
      page.is(
        page.global('SplitwiseApi === window.SplitwiseApi'),
        true,
        'SplitwiseApi as a bare global'
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    /* Runs straight after the scenario above, which caches a session view inside
       api.js. A 403 leaves cached alone, so a view showing up here would be the
       previous scenario's, and the fresh context and fresh document would be a
       fiction. */
    name: 'nothing_from_the_previous_scenario_survives_into_this_one',
    async run(page) {
      page.respond('GET', '/session', notLinked());
      await page.boot();
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    name: 'boot_with_an_unlinked_session_shows_the_not_linked_message',
    async run(page) {
      page.respond('GET', '/session', ok(NO_MEMBER));
      await page.boot();
      noticeIsUp(page, 'unlinked', 'an unlinked session', true);
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* The other route to the same screen: through announce(), not through refresh(). */
    name: 'a_403_member_not_linked_shows_the_not_linked_message',
    async run(page) {
      page.respond('GET', '/session', notLinked());
      await page.boot();
      noticeIsUp(page, 'unlinked', 'a 403 member_not_linked', true);
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    name: 'a_network_failure_shows_the_offline_message_and_never_the_gate',
    async run(page) {
      page.respond('GET', '/session', networkFailure());
      await page.boot();
      noticeIsUp(page, 'offline', 'a network failure', false);
      /* Explicitly, because the offline notice being up is not enough on its own:
         prompting for a password on a page that cannot send it is how a person types
         their password into nothing, repeatedly. */
      page.is(page.el('gate').hidden, true, '#gate hidden');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    name: 'a_server_error_is_the_same_screen_as_being_offline',
    async run(page) {
      page.respond('GET', '/session', serverError());
      await page.boot();
      noticeIsUp(page, 'offline', 'a 500', false);
      page.is(page.el('gate').hidden, true, '#gate hidden');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    name: 'the_api_client_failing_to_load_shows_the_offline_message',
    async run(page) {
      page.absent('api.js');
      await page.boot();
      noticeIsUp(page, 'offline', 'the client failing to load', false);
      /* Nothing is ever wired, so nothing is ever asked of the back end. */
      page.expectRequests([]);
      page.is(page.global('typeof window.SplitwiseApi'), 'undefined', 'SplitwiseApi');
    }
  },

  {
    /* The replacement for the deleted structural test, and the scenario both mutants
       are measured against. */
    name: 'a_refused_sign_in_tells_the_person_why',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'a refused sign-in');
      gateReads(page, 'signing in', 'a refused sign-in');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, REFUSED, '#gate-error text');
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests(['GET /api/session', 'POST /api/session']);
    }
  },

  {
    name: 'a_refused_sign_in_with_an_unreadable_body_still_says_something',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', unreadable(401));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'an unreadable refusal');
      gateReads(page, 'signing in', 'an unreadable refusal');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(
        page.el('gate-error').textContent,
        'That did not work.',
        '#gate-error text'
      );
      page.expectRequests(['GET /api/session', 'POST /api/session']);
    }
  },

  {
    /* The quiet branch: submitted() returns early, because the offline notice is
       already up and the gate deliberately is not. */
    name: 'a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', networkFailure());
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      noticeIsUp(page, 'offline', 'a sign-in that got no answer', false);
      page.is(page.el('gate-error').textContent, '', '#gate-error text');
      page.is(page.el('gate-error').hidden, true, '#gate-error hidden');
      /* Enabled again anyway, so the person can try once the network is back. */
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests(['GET /api/session', 'POST /api/session']);
    }
  },

  {
    name: 'a_successful_sign_in_keeps_the_screen_the_person_was_on',
    async run(page) {
      screensLoad(page);
      page.startAt('#/balances');
      page.respondInOrder('GET', '/session', [refusal(SIGN_IN_FIRST), ok(A_MEMBER)]);
      page.respond('POST', '/session', ok(A_MEMBER));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      appIsUp(page, 'a successful sign-in');
      page.is(page.hash, '#/balances', 'location.hash');
      page.same(visibleScreens(page), ['screen-balances'], 'the screens on show');
      page.is(page.title, 'Balances - ' + APP_NAME, 'document.title');
      page.is(page.el('gate-password').value, '', '#gate-password cleared');
      page.expectRequests([
        'GET /api/session',
        'POST /api/session',
        'GET /api/session',
        'GET /api/members',
        'GET /api/balances'
      ]);
    }
  },

  {
    /* KNOWN DEFECT, PINNED ON PURPOSE. The sign-in succeeds, the session read behind
       it 401s, and the person is dropped back on a gate with no message at all: the
       401 handler calls showGate(''), and submitted()'s success path never writes
       anything. This scenario asserts that blankness so the behaviour cannot change
       unnoticed, not because it is right. If it starts failing because someone fixed
       the screen, update this scenario to the new behaviour: do not revert the fix.
       Reported for its own task rather than fixed here, because changing app/ is out
       of scope for a test harness. */
    name: 'a_session_that_dies_between_sign_in_and_session_read_returns_to_a_blank_gate',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', ok(A_MEMBER));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'a session that died');
      gateReads(page, 'signing in', 'a session that died');
      /* The defect, written down: no message, on a gate the person just signed in at
         successfully. */
      page.is(page.el('gate-error').hidden, true, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, '', '#gate-error text');
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      /* The sign-in cached a session view; the 401 behind it has to drop that copy.
         A copy of server state left in the browser is how a signed-out page keeps
         showing a ledger. */
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests([
        'GET /api/session',
        'POST /api/session',
        'GET /api/session'
      ]);
    }
  },

  {
    /* Signup issues no session, so the client signs in straight after it. */
    name: 'creating_an_account_signs_in_straight_after',
    async run(page) {
      screensLoad(page);
      page.respondInOrder('GET', '/session', [refusal(SIGN_IN_FIRST), ok(A_MEMBER)]);
      page.respond('POST', '/signup', ok({ account: A_MEMBER.account }));
      page.respond('POST', '/session', ok(A_MEMBER));
      await page.boot();
      await page.dispatch(page.el('gate-mode'), 'click');
      page.is(page.focused, page.el('gate-email'), 'focus after switching mode');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.expectRequests([
        'GET /api/session',
        'POST /api/signup',
        'POST /api/session',
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
      appIsUp(page, 'creating an account');
      /* Back to signing in, because the account now exists. */
      gateReads(page, 'signing in', 'after creating an account');
    }
  },

  {
    name: 'the_gate_says_whether_it_is_signing_in_or_creating_an_account',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      await page.boot();
      gateReads(page, 'signing in', 'at first');
      await page.dispatch(page.el('gate-mode'), 'click');
      gateReads(page, 'creating', 'after switching');
      await page.dispatch(page.el('gate-mode'), 'click');
      gateReads(page, 'signing in', 'after switching back');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* So a password manager offers to save a new secret rather than fill an old one. */
    name: 'the_gate_switches_the_password_autocomplete_with_the_mode',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      await page.boot();
      const password = page.el('gate-password');
      page.is(password.getAttribute('autocomplete'), 'current-password', 'signing in');
      await page.dispatch(page.el('gate-mode'), 'click');
      page.is(password.getAttribute('autocomplete'), 'new-password', 'creating');
      await page.dispatch(page.el('gate-mode'), 'click');
      page.is(password.getAttribute('autocomplete'), 'current-password', 'back again');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* Without preventDefault the browser navigates and the whole app blanks. */
    name: 'the_form_never_lets_the_browser_navigate',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      const event = await signIn(page, 'sam@example.com', 'hunter2');
      page.is(event.defaultPrevented, true, 'preventDefault on the submit event');
      page.expectRequests(['GET /api/session', 'POST /api/session']);
    }
  },

  {
    name: 'the_email_is_trimmed_and_the_password_is_not',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, '  sam@example.com  ', ' hunter2');
      const sent = page.calls[1];
      page.is(sent.method, 'POST', 'the method');
      page.is(sent.url, '/api/session', 'the path');
      page.is(
        sent.body,
        '{"email":"sam@example.com","password":" hunter2"}',
        'the request body'
      );
      page.expectRequests(['GET /api/session', 'POST /api/session']);
    }
  },

  {
    name: 'signing_out_returns_to_the_gate',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('DELETE', '/session', noContent());
      await page.boot();
      await page.dispatch(page.el('sign-out'), 'click');
      gateIsUp(page, 'after signing out');
      gateReads(page, 'signing in', 'after signing out');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'DELETE /api/session'
      ]);
    }
  },

  {
    name: 'routing_shows_one_screen_and_moves_focus',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      await page.boot();
      await page.goTo('#/balances');
      page.same(visibleScreens(page), ['screen-balances'], 'the screens on show');
      page.same(currentTabs(page), ['#/balances'], 'aria-current');
      page.is(page.title, 'Balances - ' + APP_NAME, 'document.title');
      page.is(page.focused, page.el('title-balances'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'GET /api/members',
        'GET /api/balances'
      ]);
    }
  },

  {
    name: 'an_unknown_hash_is_replaced_not_pushed',
    async run(page) {
      screensLoad(page);
      page.startAt('#/nope');
      page.respond('GET', '/session', ok(A_MEMBER));
      await page.boot();
      page.same(page.replaceStates, ['#/feed'], 'history.replaceState');
      page.same(page.pushStates, [], 'history.pushState');
      page.is(page.hash, '#/feed', 'location.hash');
      page.same(visibleScreens(page), ['screen-feed'], 'the screens on show');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    name: 'every_request_goes_to_the_api_with_credentials',
    async run(page) {
      screensLoad(page);
      page.setCookie('sl_csrf=a-token');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('DELETE', '/session', noContent());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await page.dispatch(page.el('sign-out'), 'click');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'DELETE /api/session',
        'POST /api/session'
      ]);
      /* Every recorded call, never a spot check of the first two: the request whose
         method decides whether a CSRF token is sent is exactly the one a spot check
         leaves out, and the back end refuses a DELETE without that header. */
      page.calls.forEach((call, index) => {
        const at = 'call ' + index + ' (' + call.method + ' ' + call.url + ')';
        page.ok(call.url.indexOf('/api/') === 0, at + ' does not go to /api/');
        page.is(call.credentials, 'same-origin', at + ' credentials');
        if (SAFE_METHODS.indexOf(call.method) === -1) {
          page.same(
            Object.keys(call.headers),
            ['Accept', 'Content-Type', 'X-CSRF-Token'],
            at + ' headers'
          );
          page.ok(call.body !== null, at + ' sends a body');
        } else {
          /* A safe method changes nothing, so it carries neither a body, a content
             type, nor a token. */
          page.same(Object.keys(call.headers), ['Accept'], at + ' headers');
          page.is(call.body, null, at + ' body');
        }
      });
    }
  },

  {
    /* The token the server rotated on the last response is the one the next request
       has to carry, so it is read from the cookie at request time and never cached. */
    name: 'the_csrf_token_is_read_at_request_time_not_cached',
    async run(page) {
      page.setCookie('sl_csrf=first-token');
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      page.setCookie('sl_csrf=second-token');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.expectRequests([
        'GET /api/session',
        'POST /api/session',
        'POST /api/session'
      ]);
      page.is(page.calls[1].headers['X-CSRF-Token'], 'first-token', 'the first POST');
      page.is(page.calls[2].headers['X-CSRF-Token'], 'second-token', 'the second POST');
    }
  },

  {
    name: 'a_204_is_not_parsed_as_json',
    async run(page) {
      screensLoad(page);
      const answer = noContent();
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('DELETE', '/session', answer);
      await page.boot();
      await page.dispatch(page.el('sign-out'), 'click');
      page.is(answer.jsonCalls, 0, 'json() calls on the 204');
      page.is(page.el('gate').hidden, false, '#gate visible');
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'DELETE /api/session'
      ]);
    }
  },

  {
    /* The stub's own honesty check: a selector shape it does not support has to be a
       loud failure, so a screen task that introduces one widens the stub deliberately
       instead of quietly getting null back. */
    name: 'an_unsupported_selector_is_a_loud_failure_not_a_null',
    async run(page) {
      page.respond('GET', '/session', refusal(SIGN_IN_FIRST));
      await page.boot();
      let message = null;
      try {
        page.query('a[href]');
      } catch (error) {
        message = String(error.message);
      }
      page.ok(message !== null, 'an unsupported selector throws rather than returning');
      page.ok(
        message !== null && message.indexOf('a[href]') !== -1,
        'the message names the selector, and was: ' + message
      );
      page.expectRequests(['GET /api/session']);
    }
  }
];

/* --- Running ---------------------------------------------------------------- */

/* The scenario being driven, so an error that escapes into a promise nobody handled
   can be recorded against it. Without these handlers such an error kills the process
   and takes the whole report with it, which turns one broken scenario into a run that
   says nothing about the other twenty-four. */
let running = null;

function escaped(kind, reason) {
  const detail = kind + ': ' + (reason && reason.stack ? reason.stack : String(reason));
  if (running === null) {
    process.stderr.write('harness error: ' + detail + '\n');
    process.exit(2);
  }
  running.fail(detail);
}

process.on('unhandledRejection', (reason) => escaped('unhandled rejection', reason));
process.on('uncaughtException', (error) => escaped('uncaught exception', error));

function readSource(relative, substitutions) {
  const path = join(REPO, relative);
  if (!path.startsWith(REPO)) {
    throw new HarnessError('a substitution named a path outside the repository: ' + relative);
  }
  if (!existsSync(path)) {
    throw new HarnessError('no such file: ' + relative);
  }
  let source = readFileSync(path, 'utf8');
  substitutions
    .filter((substitution) => substitution.file === relative)
    .forEach((substitution) => {
      const find = String(substitution.find);
      const hits = source.split(find).length - 1;
      if (hits !== 1) {
        /* An anchor that rots into zero or many matches refuses the whole run rather
           than quietly mutating something else, so a later task that edits the anchor
           has to re-express the mutant. */
        throw new HarnessError(
          'the anchor ' + JSON.stringify(find) + ' matched ' + hits + ' times in ' +
            relative + ', not exactly once'
        );
      }
      source = source.replace(find, String(substitution.replace));
    });
  return source;
}

function compile(substitutions) {
  const scripts = new Map();
  ['app.js', 'api.js'].forEach((file) => {
    const source = readSource('app/' + file, substitutions);
    /* The real file path is the script filename, so an exception inside app.js
       reports that path and a line number. */
    scripts.set(join(APP, file), new vm.Script(source, { filename: join(APP, file) }));
  });
  return scripts;
}

async function main() {
  const config = await readConfig();
  const substitutions = config.substitutions || [];
  substitutions.forEach((substitution) => {
    if (substitution.file !== 'app/app.js' && substitution.file !== 'app/api.js') {
      throw new HarnessError(
        'a substitution named ' + JSON.stringify(String(substitution.file)) +
          '; only app/app.js and app/api.js are loaded'
      );
    }
  });
  const scripts = compile(substitutions);

  const wanted = config.scenarios;
  if (wanted !== undefined) {
    wanted.forEach((name) => {
      if (!SCENARIOS.some((scenario) => scenario.name === name)) {
        throw new HarnessError('there is no scenario named ' + name);
      }
    });
  }
  const chosen = SCENARIOS.filter(
    (scenario) => wanted === undefined || wanted.indexOf(scenario.name) !== -1
  );

  const report = { scenarios: [], errorCodes: Object.keys(CODES).sort().map((key) => CODES[key]) };
  for (const scenario of chosen) {
    /* A fresh context and a freshly parsed document per scenario: api.js holds cached
       and handlers, app.js holds current and creating, and no scenario may inherit
       another's state. */
    const driver = page(scripts, scenario.name, Boolean(config.provokeRunawayTimer));
    running = driver;
    try {
      await scenario.run(driver);
      driver.finish();
    } catch (error) {
      if (error instanceof HarnessError) {
        throw error;
      }
      driver.fail('threw: ' + (error && error.stack ? error.stack : String(error)));
    }
    running = null;
    const passed = driver.failures.length === 0;
    report.scenarios.push({
      name: scenario.name,
      passed: passed,
      failures: driver.failures,
      requests: driver.requests,
      windowEvents: driver.windowEvents
    });
    process.stderr.write((passed ? 'ok   ' : 'FAIL ') + scenario.name + '\n');
    driver.failures.forEach((failure) => process.stderr.write('       ' + failure + '\n'));
  }
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  return report.scenarios.every((entry) => entry.passed) ? 0 : 1;
}

async function readConfig() {
  /* No stdin at all means every scenario against the unmodified files, so a person
     debugging one can run the harness directly. */
  if (process.stdin.isTTY) {
    return {};
  }
  let raw = '';
  for await (const chunk of process.stdin) {
    raw += chunk;
  }
  if (raw.trim() === '') {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new HarnessError('the configuration on stdin is not JSON: ' + String(error));
  }
}

try {
  process.exitCode = await main();
} catch (error) {
  process.stderr.write(
    (error instanceof HarnessError ? 'harness error: ' : 'harness crashed: ') +
      (error && error.stack ? error.stack : String(error)) + '\n'
  );
  process.exitCode = 2;
}

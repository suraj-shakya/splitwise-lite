/* Splitwise Lite shell harness: runs the shipped app/ files and asserts what a
   person would see.

   Why this exists. Task 9a's test for a refused sign-in sliced the body of
   submitted() out of app/app.js and asserted substrings against that slice. The
   defect it was written to pin is an ordering defect spread across three functions in
   two files, announce() in api.js and showGate() and submitted() in app.js, so a test
   that reads the text of one of them cannot see it by construction. Two mutants prove
   it: both reintroduce the defect and leave the sliced function byte-identical, and
   the structural test passed both.

   The three mutants this harness is measured against, applied to the real source at
   run time as anchored substitutions and never committed as copies:

     A. app/app.js, inside show():  gate.hidden = which !== 'gate';
        gains                       gateError.hidden = true;
     B. app/api.js, inside announce(): handlers.unauthenticated(error);
        becomes  setTimeout(function () { error.say = '';
                 handlers.unauthenticated(error); }, 0);
     C. app/api.js, the default arm of classify(): return 'refused';
        becomes  return '';

   Mutant B is only visible once the timer queue has drained, not just the microtask
   queue, which is why settle() drains both. Mutant C puts back the fall through task
   32 removed: a kind no handler speaks for, so an answer the server gave reaches
   nobody and the screen does not change. The text of all three lives in
   tests/test_shell_behaviour.py, where a reviewer reads it.

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
  notAuthenticated: 'not_authenticated',
  sessionInvalid: 'session_invalid',
  authenticationFailed: 'authentication_failed',
  memberNotLinked: 'member_not_linked',
  csrfFailed: 'csrf_failed',
  recordNotFound: 'record_not_found',
  emailAlreadyRegistered: 'email_already_registered',
  tooManyAttempts: 'too_many_attempts',
  internalError: 'internal_error',
  noGroupConfigured: 'no_group_configured',
  ambiguousGroup: 'ambiguous_group'
};

/* The wire contract every request is held to, spelled out here rather than read back
   from api.js: an assertion that borrows the subject's own constants asserts nothing.
   web.py gates a state-changing request on the CSRF header and on the content type, so
   a request that carries the wrong value for either is refused by the real server while
   a check of header names alone stays green. */
const CSRF_COOKIE = 'sl_csrf';
const CSRF_HEADER = 'X-CSRF-Token';
const ACCEPTS = 'application/json';
const SENDS = 'application/json';
/* The methods that change nothing, so they carry no body, no content type and no
   token. */
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

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

    /* Derived from the attribute on every read, never snapshotted at parse time. A
       snapshot accepts setAttribute('class', ...) and className silently and never
       reflects it, so a .class selector finds nothing and the scenario that relies on
       it passes while asserting nothing. Tasks 11 and 12 set className on every node
       they build. */
    get classList() {
      return String(own.attributes.class || '').split(/\s+/).filter(Boolean);
    },
    get className() {
      return own.attributes.class === undefined ? '' : own.attributes.class;
    },
    set className(value) {
      own.attributes.class = String(value);
    }
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
    },
    set(object, property, value) {
      /* A property nobody defined is refused rather than quietly created. Accepting
         it would leave a shipped file writing into a stub that reflects nothing,
         which reads as a passing test. */
      if (typeof property !== 'symbol' && !(property in object)) {
        throw new Error(
          'the stub ' + what + ' has no ' + String(property) + ' to set; the harness ' +
            'fakes only what a shipped file uses, so widen it deliberately'
        );
      }
      object[property] = value;
      return true;
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

/* The harness's own reading of the cookie jar, used to check what the CSRF header
   should have carried. Be clear about how much that is worth: this is a second copy of
   api.js's readCookie, not an independent one, so a mutation this copy would mirror is
   not caught here. What catches those is the two cookie-bearing scenarios asserting the
   literal decoded token, 'a token' and 'first token', which no copy of the subject can
   agree with by accident. */
function jarValue(jar, name) {
  const parts = String(jar || '').split(';');
  for (let index = 0; index < parts.length; index += 1) {
    const pair = parts[index];
    const split = pair.indexOf('=');
    if (split !== -1 && pair.slice(0, split).trim() === name) {
      return decodeURIComponent(pair.slice(split + 1));
    }
  }
  return null;
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

function noStatus() {
  /* A response this client cannot get a status out of. web.py never sends one, but a
     service worker or a polyfill standing between the two can hand one back, and the
     classifier has a row for it: never a refusal, and never the gate. */
  return { status: undefined, ok: false, json: () => Promise.resolve(null) };
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
  const watchers = [];
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
      credentials: options.credentials === undefined ? null : options.credentials,
      /* The whole options object's shape, so an added mode, cache or redirect is a
         failure rather than an invisible change of what the browser is asked to do. */
      optionKeys: Object.keys(options),
      /* The token the jar held when this request went out, read by the harness rather
         than by api.js, so the header can be checked against what it should have
         carried. */
      csrf: jarValue(cookie, CSRF_COOKIE)
    });
    const key = method + ' ' + url;
    /* Watchers see the page as it was when the request went out. Nothing is asserted
       here: a scenario records what it saw and asserts after settle, because some
       states, a control disabled in flight among them, exist at no other moment. */
    watchers.forEach((watcher) => {
      if (watcher.key === key) {
        watcher.watch();
      }
    });
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
         happening is a failure too.

         An entry is either 'METHOD /api/path' for a safe method, or, for a method
         that changes something, { method, path, body } carrying the exact body. The
         body is not optional there: a request whose payload nobody asserts is a
         request whose payload can be rewritten silently, which is how signUp could
         send the password as the display name and stay green. */
      declaredRequests = list.slice();
    },
    onRequest(method, path, watch) {
      watchers.push({ key: method + ' /api' + path, watch: watch });
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
    async settle() {
      /* Drives nothing. It lets work that is already in flight finish, for the two
         scenarios that start a request through the shipped client itself rather than
         through the page, and it drains the same queues every other driver call
         does. */
      await settle();
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
      /* The #notice invariant, checked on every scenario rather than only on the ones
         that thought to look: while the curtain is up, exactly one of its four
         paragraphs is showing. While it is down, nothing inside it is visible and the
         flags underneath are not a state anybody can see. That distinction is
         load-bearing, and it rests on showNotice() being the only thing that ever
         raises #notice again, which is why it sets all four flags on every call. */
      if (!byId('notice').hidden) {
        const showing = NOTICES.filter((name) => !byId('notice-' + name).hidden);
        if (showing.length !== 1) {
          failures.push(
            '#notice is up with ' + showing.length + ' of its paragraphs showing, ' +
              'not exactly one: ' + JSON.stringify(showing)
          );
        }
      }
      calls.forEach((call, index) => wellFormed(call, index, failures));
      if (declaredRequests === null) {
        failures.push(
          'this scenario declared no expected requests; every scenario must call ' +
            'expectRequests, so a call nobody registered an answer for cannot slip ' +
            'through a promise chain that swallowed the rejection'
        );
      } else {
        const lines = declaredRequests.map((entry) =>
          typeof entry === 'string' ? entry : entry.method + ' /api' + entry.path
        );
        if (JSON.stringify(api.requests) !== JSON.stringify(lines)) {
          failures.push(
            'requests: expected ' + JSON.stringify(lines) + ', got ' +
              JSON.stringify(api.requests)
          );
        } else {
          calls.forEach((call, index) => {
            const entry = declaredRequests[index];
            const declared = typeof entry === 'string' ? undefined : entry.body;
            const at = 'call ' + index + ' (' + call.method + ' ' + call.url + ')';
            if (SAFE_METHODS.indexOf(call.method) !== -1) {
              api.is(call.body, null, at + ' body');
              if (declared !== undefined) {
                failures.push(at + ' is a safe method and sends no body to declare');
              }
            } else if (declared === undefined) {
              failures.push(
                at + ' changes something, so declare the exact body it sends: ' +
                  JSON.stringify(call.body)
              );
            } else {
              api.is(call.body, declared, at + ' body');
            }
          });
        }
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

/* Every recorded call, held to the whole wire contract and not to its method and path.
   Applied in finish() to every call of every scenario, so no scenario can inspect the
   easy half: a Content-Type of text/plain, an Accept header that takes anything, an
   added mode: 'no-cors' and a CSRF header carrying the raw cookie value are all either
   refused by web.py or a change to what the browser is asked to do, and all four are
   invisible to a check of header names. */
function wellFormed(call, index, failures) {
  const at = 'call ' + index + ' (' + call.method + ' ' + call.url + ')';
  const safe = SAFE_METHODS.indexOf(call.method) !== -1;
  const note = (what, expected, actual) => {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      failures.push(
        at + ' ' + what + ': expected ' + JSON.stringify(expected) + ', got ' +
          JSON.stringify(actual)
      );
    }
  };

  if (call.url.indexOf('/api/') !== 0) {
    failures.push(at + ' does not go to /api/');
  }
  note('credentials', 'same-origin', call.credentials);
  note(
    'the options it was given',
    safe
      ? ['method', 'credentials', 'headers']
      : ['method', 'credentials', 'headers', 'body'],
    call.optionKeys
  );

  const headers = { Accept: ACCEPTS };
  if (!safe) {
    headers['Content-Type'] = SENDS;
    if (call.csrf !== null) {
      /* The decoded, trimmed value the jar held, so a token sent raw or read with the
         wrong name fails here rather than at the server. */
      headers[CSRF_HEADER] = call.csrf;
    }
  }
  note('headers', headers, call.headers);
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
/* The exact payloads, spelled out rather than rebuilt from the values the scenario
   typed in, so a client that sends the password where the display name belongs fails
   here instead of shipping. */
const SIGN_IN_BODY = '{"email":"sam@example.com","password":"hunter2"}';
const SIGN_UP_BODY =
  '{"email":"sam@example.com","display_name":"sam@example.com","password":"hunter2"}';
const NO_BODY = '{}';

const REFUSED = 'Those details did not match an account.';
const SIGN_IN_FIRST = 'Sign in to continue.';
const EXPIRED = 'That session is no longer valid; sign in again.';
const STALE_FORM = 'That form went stale.';
const NO_SUCH_RECORD = 'no expense with that id';
const TOO_MANY_ATTEMPTS = 'too many failed attempts; wait a few minutes and try again';
const GENERIC_500 =
  'the server could not complete that request; the failure has been logged';
/* The two sentences web.py keeps its own words for, in the shape groups.py composes
   them: one names the command that fixes it, the other names every group id. Spelled
   out here rather than imported, and asserted character for character on screen, so a
   client that summarises either of them fails. */
const NO_GROUP =
  'this store holds no group yet; create one with: uv run python ' +
  'scripts/setup_group.py apply --store PATH --definition group.toml';
const AMBIGUOUS_GROUP =
  "this store holds 2 groups, so which one is meant is ambiguous: 'grp-1', 'grp-2'; " +
  'pass the group id explicitly';

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

/* The three 401s web.py can send, kept apart because announce() treats them apart.
   not_authenticated is every first visit, so its sentence is written for a client and
   is suppressed; session_invalid is a session that died; authentication_failed only
   ever answers POST /api/session. */
const noSession = () => failure(401, CODES.notAuthenticated, SIGN_IN_FIRST);
const sessionDied = (message) => failure(401, CODES.sessionInvalid, message);
const refusal = (message) => failure(401, CODES.authenticationFailed, message);
const notLinked = () =>
  failure(403, CODES.memberNotLinked, 'Nobody has linked you to a member yet.');
/* A 403 that is not member_not_linked, and a 4xx that is neither a sign-in problem nor
   a server one. Both exist to pin which branch of announce() they land in. */
const csrfRefused = () => failure(403, CODES.csrfFailed, STALE_FORM);
const missingRecord = () => failure(404, CODES.recordNotFound, NO_SUCH_RECORD);
const alreadyRegistered = () =>
  failure(409, CODES.emailAlreadyRegistered, 'That address already has an account.');
const rateLimited = () => failure(429, CODES.tooManyAttempts, TOO_MANY_ATTEMPTS);
const serverError = () => failure(500, CODES.internalError, GENERIC_500);
/* The two 503s web.py composes on purpose. Both were thrown away by the old
   status >= 500 arm, which is what told an operator who has not run setup_group.py
   that their network was broken. */
const noGroupConfigured = () => failure(503, CODES.noGroupConfigured, NO_GROUP);
const ambiguousGroup = () => failure(503, CODES.ambiguousGroup, AMBIGUOUS_GROUP);

/* The name the document title carries, spelled out here rather than read back from
   app.js: an assertion that borrows the subject's own constant asserts nothing. */
const APP_NAME = 'Splitwise Lite';

async function signIn(page, email, password) {
  page.el('gate-email').value = email;
  page.el('gate-password').value = password;
  return page.dispatch(page.el('gate-form'), 'submit');
}

const SCREENS = ['screen-feed', 'screen-add', 'screen-balances'];


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

/* The four paragraphs #notice holds, of which exactly one is ever visible. All four
   are asserted together and never one at a time: a screen assertion that names only
   the paragraph it expects leaves the other three free to be wrong, which is how a
   sentence from an earlier failure ends up sitting behind a later one. */
const NOTICES = ['unlinked', 'offline', 'not-kept', 'problem'];

function everyNoticeHidden(page, which, what) {
  NOTICES.forEach((name) => {
    page.is(
      page.el('notice-' + name).hidden,
      which !== name,
      what + ': #notice-' + name + ' hidden'
    );
  });
}

function gateIsUp(page, what) {
  /* showGate() hides the sign out control, and every route to the gate goes through
     it, so it is hidden whenever the gate is up.

     The four paragraph flags are deliberately not asserted here. Nothing resets them
     when the gate replaces a notice, so after a curtain the paragraph that was up
     stays flagged visible underneath a #notice that is itself hidden, where nobody
     can see it. curtains() pins that #notice is hidden, which is the property that
     matters and the one the two canaries rely on; the flags underneath only mean
     something while the curtain is up, and finish() checks them there on every
     scenario. Asserting them here as well would be asserting that the app does
     housekeeping it does not do, and the first scenario to go notice-then-gate would
     fail for a reason that is not a defect. */
  curtains(page, 'gate', what, false);
  page.is(flatText(page.el('gate-lede')), GATE_LEDE, what + ': #gate-lede text');
}

function noticeIsUp(page, which, what, signOutVisible) {
  curtains(page, 'notice', what, signOutVisible);
  everyNoticeHidden(page, which, what);
  page.is(page.focused, page.el('notice-title'), what + ': focus');
}

function appIsUp(page, what) {
  curtains(page, 'app', what, true);
}

const SCENARIOS = [
  {
    name: 'boot_with_no_session_shows_the_gate',
    async run(page) {
      page.respond('GET', '/session', noSession());
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
    /* announce() reads the code as well as the status, and only member_not_linked is
       the not-linked screen. Any other 403 is a refusal, and this one answered the
       session read, whose rejection refresh() discards on the grounds that a handler
       has already spoken: without the escalation nobody speaks at all and the person
       is left looking at an empty app frame. The server's own sentence goes up
       instead. */
    name: 'a_403_that_is_not_member_not_linked_prints_what_the_server_said',
    async run(page) {
      page.respond('GET', '/session', csrfRefused());
      await page.boot();
      noticeIsUp(page, 'problem', 'a 403 that is not member_not_linked', false);
      page.is(page.el('notice-problem').textContent, STALE_FORM, '#notice-problem text');
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
    /* A 500 and a request that got no answer are two different things: one is an
       answer this app produced and logged, and it has a sentence, the other is no
       answer at all. So a 500 stops claiming the network is down and prints what the
       server said. Never the gate either way. */
    name: 'a_server_error_prints_what_the_server_said_and_never_the_gate',
    async run(page) {
      page.respond('GET', '/session', serverError());
      await page.boot();
      noticeIsUp(page, 'problem', 'a 500', false);
      page.is(page.el('notice-problem').textContent, GENERIC_500, '#notice-problem text');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* Defect 1, closed. web.py composes this sentence on purpose and it names the
       command that fixes it; the old status >= 500 arm threw it away and told an
       operator who had not run setup_group.py that their network was broken. */
    name: 'a_503_naming_the_setup_command_prints_that_sentence',
    async run(page) {
      page.respond('GET', '/session', noGroupConfigured());
      await page.boot();
      noticeIsUp(page, 'problem', 'a 503 with no group configured', false);
      /* Character for character what the fixture sent: not summarised, not prefixed
         and not replaced by a sentence this client wrote. */
      page.is(page.el('notice-problem').textContent, NO_GROUP, '#notice-problem text');
      page.ok(
        page.el('notice-problem').textContent.indexOf('setup_group.py') !== -1,
        'the printed sentence names the setup command'
      );
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* The other 503, whose sentence names every group id rather than picking one.
       Both ids have to survive the trip to the screen. */
    name: 'a_503_naming_both_group_ids_prints_both_of_them',
    async run(page) {
      page.respond('GET', '/session', ambiguousGroup());
      await page.boot();
      noticeIsUp(page, 'problem', 'a 503 with an ambiguous group', false);
      page.is(
        page.el('notice-problem').textContent,
        AMBIGUOUS_GROUP,
        '#notice-problem text'
      );
      ['grp-1', 'grp-2'].forEach((id) => {
        page.ok(
          page.el('notice-problem').textContent.indexOf(id) !== -1,
          'the printed sentence names ' + id
        );
      });
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* A gateway nobody in this repo writes, answering with its own HTML error page.
       There is no sentence to print, so the standing offline paragraph stands in
       rather than a blank curtain. What this pins is that it is classified at all:
       treated as a refusal it would raise nothing and leave an empty app frame. */
    name: 'a_status_above_five_hundred_nobody_anticipated_is_still_classified',
    async run(page) {
      page.respond('GET', '/session', unreadable(502));
      await page.boot();
      noticeIsUp(page, 'offline', 'a 502 from somewhere in the middle', false);
      page.is(page.el('notice-problem').textContent, '', '#notice-problem text');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* And below 500, where the old code did nothing at all. This one answered the
       session read, so it is escalated; with no sentence in the body the standing
       offline paragraph stands in. The gate is never offered: if the client cannot
       read what was refused, a password box is how the password-into-nothing loop
       starts. */
    name: 'a_status_below_five_hundred_nobody_anticipated_is_not_silently_dropped',
    async run(page) {
      page.respond('GET', '/session', unreadable(418));
      await page.boot();
      noticeIsUp(page, 'offline', 'a 418 nobody anticipated', false);
      page.is(page.el('notice-problem').textContent, '', '#notice-problem text');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* The other way a request comes back with a status of 0: not fetch rejecting, but
       the browser handing back a response this client may not read. Both mean no
       answer came back, so both are the same kind and the same paragraph.

       Asked for by a screen rather than by the session read, because that is where
       the classification shows: a refusal would be left to the feed to report and the
       app frame would stay up. A curtain is right here, because nothing came back. */
    name: 'a_response_the_client_may_not_read_is_the_same_as_no_answer',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', unreadable(0));
      await page.boot();
      noticeIsUp(page, 'offline', 'a response that could not be read', true);
      page.is(page.el('gate').hidden, true, '#gate hidden');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    /* A status that is not a readable number. It must never be a refusal, which would
       leave the app frame up and the feed reporting something the client never
       established, and it must never raise the gate: if the client cannot tell that
       the request was refused, offering a password box is exactly how the
       password-into-nothing loop starts. */
    name: 'a_status_that_is_not_a_number_is_never_taken_for_a_refusal',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', noStatus());
      await page.boot();
      noticeIsUp(page, 'offline', 'a status that could not be read', true);
      page.is(page.el('gate').hidden, true, '#gate hidden');
      page.is(page.el('notice-problem').textContent, '', '#notice-problem text');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    /* #notice-problem is the one paragraph a screen writes, so it is the one that can
       be left behind. A second failure that shows a different paragraph has to clear
       it: a sentence about a group that was not configured, sitting under a heading
       about being offline, would be read as if it were still true. */
    name: 'a_later_failure_does_not_leave_the_earlier_sentence_behind',
    async run(page) {
      page.respondInOrder('GET', '/session', [noGroupConfigured(), networkFailure()]);
      await page.boot();
      noticeIsUp(page, 'problem', 'the first failure', false);
      page.is(page.el('notice-problem').textContent, NO_GROUP, '#notice-problem text');
      /* One more read, driven through the shipped client because nothing on a curtain
         asks for one. app/app.js's own handlers are left in place, so this asserts
         what a person would see. */
      page.global('window.SplitwiseApi.session().then(null, function () {});');
      await page.settle();
      noticeIsUp(page, 'offline', 'the second failure', false);
      page.is(page.el('notice-problem').textContent, '', '#notice-problem text');
      page.expectRequests(['GET /api/session', 'GET /api/session']);
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
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'a refused sign-in');
      gateReads(page, 'signing in', 'a refused sign-in');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, REFUSED, '#gate-error text');
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    name: 'a_refused_sign_in_with_an_unreadable_body_still_says_something',
    async run(page) {
      page.respond('GET', '/session', noSession());
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
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    /* The quiet branch: submitted() returns early, because the offline notice is
       already up and the gate deliberately is not. */
    name: 'a_sign_in_that_cannot_reach_the_server_leaves_the_gate_alone',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', networkFailure());
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      noticeIsUp(page, 'offline', 'a sign-in that got no answer', false);
      page.is(page.el('gate-error').textContent, '', '#gate-error text');
      page.is(page.el('gate-error').hidden, true, '#gate-error hidden');
      /* Enabled again anyway, so the person can try once the network is back. */
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    name: 'a_successful_sign_in_keeps_the_screen_the_person_was_on',
    async run(page) {
      screensLoad(page);
      page.startAt('#/balances');
      page.respondInOrder('GET', '/session', [noSession(), ok(A_MEMBER)]);
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
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members',
        'GET /api/balances'
      ]);
    }
  },

  {
    /* What ships, after task 32. The server accepted the sign-in and then answered the
       very next request with a 401, so it believes the sign-in succeeded and its own
       sentence describes a different situation. Signing in again cannot fix that, and
       the gate this scenario used to assert was an invitation to type the same
       password again, and again: the loop was the harm. The check armed by the 200 on
       POST /api/session is what tells this apart from an ordinary expiry.
       plans/tasks/32-client-error-classification.md carries the reasoning. */
    name: 'a_session_that_dies_between_sign_in_and_session_read_says_so_instead_of_the_gate',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', ok(A_MEMBER));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      noticeIsUp(page, 'not-kept', 'a session that did not survive the sign-in', false);
      /* No gate, and nothing written on the one behind the curtain either: a message
         left there would be read the moment anything raised it again. */
      page.is(page.el('gate-error').hidden, true, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, '', '#gate-error text');
      /* Enabled again anyway, as on every other path out of submitted(). */
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      /* The sign-in cached a session view; the 401 behind it has to drop that copy.
         A copy of server state left in the browser is how a signed-out page keeps
         showing a ledger. */
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session'
      ]);
    }
  },

  {
    /* An ordinary 401 with the check never armed at all, which is what a session that
       expires under a client that booted straight into a live session looks like. The
       gate comes back carrying the sentence the server sent rather than blank.

       This scenario does NOT exercise the disarm: it boots into ok(A_MEMBER), so
       armed is still false from initialisation and the 401 is ordinary for that
       reason rather than because anything disarmed it. The scenario below is the one
       that arms the check first and then relies on the disarm. */
    name: 'a_session_that_expires_mid_session_puts_the_server_sentence_on_the_gate',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respondInOrder('GET', '/members', [ok(EMPTY_ROSTER), sessionDied(EXPIRED)]);
      await page.boot();
      appIsUp(page, 'before the session expired');
      await page.goTo('#/balances');
      gateIsUp(page, 'a session that expired');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, EXPIRED, '#gate-error text');
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
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
    /* The other way the check is disarmed: not by a response, but by there being no
       response at all. A rejected fetch is not a 401, and the safe reading of "not a
       401" is the one that lets the gate come back: a person whose network dropped
       after signing in, who then navigates and is told their session is gone, needs a
       password box. Left armed, they would get the cookie notice instead, with no
       gate behind it, which is the no-way-back curtain again.

       The one further request is driven through the shipped client rather than by
       navigating, and that is not a convenience. Navigating makes the balances screen
       read the roster and the figures together, and whichever of those two answers is
       processed first calls noted(): a 200 among them disarms the check on its own,
       before the 401 beside it is ever classified. A scenario written that way passes
       whether or not the rejected fetch disarmed anything, which is the whole failure
       this round of review was about. One request in flight, and only the rule under
       test can decide the outcome. app/app.js's own handlers are left in place, so
       what is asserted is still what a person would see. */
    name: 'a_sign_in_the_network_interrupted_still_lets_the_gate_come_back',
    async run(page) {
      page.respondInOrder('GET', '/session', [noSession(), networkFailure()]);
      page.respond('POST', '/session', ok(A_MEMBER));
      page.respond('GET', '/members', sessionDied(EXPIRED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      /* The sign-in worked and the read behind it got no answer: the offline curtain,
         and the check disarmed by the absence of an answer rather than by one. */
      noticeIsUp(page, 'offline', 'a session read that got no answer', false);
      page.global('window.SplitwiseApi.members().then(null, function () {});');
      await page.settle();
      gateIsUp(page, 'a 401 after the network came back');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, EXPIRED, '#gate-error text');
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* The disarm, which is what makes the check one-shot, and the scenario above only
       claims to cover. A real sign-in arms it, the session read behind that sign-in
       succeeds and disarms it, and the 401 that arrives later is therefore ordinary:
       the gate, with the server's sentence on it.

       Without the disarm, armed stays true for the rest of the session and every
       later 401 is read as a sign-in that did not stick. The person gets a curtain
       telling them their browser is not keeping cookies, with no gate behind it and
       no way to sign back in, which is a worse outcome than the blank gate #36 was
       filed about: that at least had a password box on it. */
    name: 'a_session_that_expires_after_a_real_sign_in_still_returns_to_the_gate',
    async run(page) {
      screensLoad(page);
      page.respondInOrder('GET', '/session', [noSession(), ok(A_MEMBER)]);
      page.respond('POST', '/session', ok(A_MEMBER));
      page.respondInOrder('GET', '/members', [ok(EMPTY_ROSTER), sessionDied(EXPIRED)]);
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      appIsUp(page, 'signed in');
      await page.goTo('#/balances');
      gateIsUp(page, 'an expiry after a real sign-in');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, EXPIRED, '#gate-error text');
      page.is(page.global('window.SplitwiseApi.cachedSession()'), null, 'cachedSession');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'GET /api/members',
        'GET /api/balances'
      ]);
    }
  },

  {
    /* A 401 answering POST /api/session is always the gate, even with the check armed
       by a sign-in that worked: a wrong password is a wrong password, and the person
       can fix it by typing the right one. The shipped app reads the session straight
       after signing in, which disarms the check, so the only way to reach a second
       sign-in while it is still armed is to drive the client directly. */
    name: 'a_401_answering_the_sign_in_itself_is_always_the_gate',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respondInOrder('POST', '/session', [ok(A_MEMBER), refusal(REFUSED)]);
      await page.boot();
      page.global(
        'window.SplitwiseApi.signIn("sam@example.com", "hunter2").then(function () {});'
      );
      await page.settle();
      page.global(
        'window.refused = null;' +
          'window.SplitwiseApi.signIn("sam@example.com", "hunter2").then(null,' +
          '  function (error) { window.refused = error; });'
      );
      await page.settle();
      page.is(page.global('window.refused.kind'), 'signed-out', 'kind');
      page.is(page.global('window.refused.say'), REFUSED, 'say');
      /* And on screen: the gate, carrying the server's sentence. Not the notice that
         a sign-in did not stick, which would tell the person their browser was at
         fault when they simply mistyped. */
      gateIsUp(page, 'a refused second sign-in');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, REFUSED, '#gate-error text');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    /* Signup issues no session, so the client signs in straight after it. */
    name: 'creating_an_account_signs_in_straight_after',
    async run(page) {
      screensLoad(page);
      page.respondInOrder('GET', '/session', [noSession(), ok(A_MEMBER)]);
      page.respond('POST', '/signup', ok({ account: A_MEMBER.account }));
      page.respond('POST', '/session', ok(A_MEMBER));
      await page.boot();
      await page.dispatch(page.el('gate-mode'), 'click');
      page.is(page.focused, page.el('gate-email'), 'focus after switching mode');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/signup', body: SIGN_UP_BODY },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
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
    /* A 409 is neither a sign-in problem nor a server one, so announce() leaves it
       alone and the gate says what happened. The offline notice would be a lie: the
       server answered, and it answered clearly. */
    name: 'creating_an_account_that_already_exists_says_so_on_the_gate',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/signup', alreadyRegistered());
      await page.boot();
      await page.dispatch(page.el('gate-mode'), 'click');
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'an address that already has an account');
      /* Still creating: only a successful sign-in switches the gate back. */
      gateReads(page, 'creating', 'an address that already has an account');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(
        page.el('gate-error').textContent,
        'That address already has an account.',
        '#gate-error text'
      );
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/signup', body: SIGN_UP_BODY }
      ]);
    }
  },

  {
    /* A refusal the gate itself asked for, so the gate reports it and no curtain comes
       down over it. A full frame curtain here would take the gate's own message away,
       which is this task causing the defect it exists to remove. */
    name: 'a_rate_limited_sign_in_reads_on_the_gate_with_no_curtain_over_it',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', rateLimited());
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      gateIsUp(page, 'a rate limited sign-in');
      gateReads(page, 'signing in', 'a rate limited sign-in');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, TOO_MANY_ATTEMPTS, '#gate-error text');
      page.is(page.el('gate-submit').disabled, false, '#gate-submit disabled');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    /* The control is disabled for exactly as long as the request is in flight, which
       is the only thing stopping a second submit. It is observed when the request goes
       out, because that is the only moment it exists, and asserted after settle. */
    name: 'the_submit_control_is_disabled_while_the_sign_in_is_in_flight',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      let inFlight = null;
      page.onRequest('POST', '/session', () => {
        inFlight = page.el('gate-submit').disabled;
      });
      page.is(page.el('gate-submit').disabled, false, '#gate-submit before');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.is(inFlight, true, '#gate-submit while the request was in flight');
      page.is(page.el('gate-submit').disabled, false, '#gate-submit afterwards');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    name: 'the_gate_says_whether_it_is_signing_in_or_creating_an_account',
    async run(page) {
      page.respond('GET', '/session', noSession());
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
      page.respond('GET', '/session', noSession());
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
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      const event = await signIn(page, 'sam@example.com', 'hunter2');
      page.is(event.defaultPrevented, true, 'preventDefault on the submit event');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    name: 'the_email_is_trimmed_and_the_password_is_not',
    async run(page) {
      page.respond('GET', '/session', noSession());
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
      page.expectRequests([
        'GET /api/session',
        {
          method: 'POST',
          path: '/session',
          body: '{"email":"sam@example.com","password":" hunter2"}'
        }
      ]);
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
        { method: 'DELETE', path: '/session', body: NO_BODY }
      ]);
    }
  },

  {
    /* signOut()'s rejection is discarded by the sign out button, so a refusal here
       reaches nobody and the button is simply dead. It is one of the two requests
       whose refusals are escalated for exactly that reason. */
    name: 'a_sign_out_the_server_refuses_says_why_rather_than_doing_nothing',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('DELETE', '/session', csrfRefused());
      await page.boot();
      await page.dispatch(page.el('sign-out'), 'click');
      noticeIsUp(page, 'problem', 'a refused sign out', true);
      page.is(page.el('notice-problem').textContent, STALE_FORM, '#notice-problem text');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        { method: 'DELETE', path: '/session', body: NO_BODY }
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
    /* Leaving a screen and coming back reads it again: nothing is kept between visits,
       so a screen never shows figures from a previous one. This is also the only
       scenario that returns to a route it has already been on, which is what makes a
       screen's own hashchange listener visible at all. */
    name: 'going_back_to_a_screen_reads_it_again',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      await page.boot();
      page.same(visibleScreens(page), ['screen-feed'], 'at first');
      page.is(page.title, 'Feed - ' + APP_NAME, 'document.title at first');
      await page.goTo('#/balances');
      page.same(visibleScreens(page), ['screen-balances'], 'after leaving');
      page.is(page.title, 'Balances - ' + APP_NAME, 'document.title after leaving');
      await page.goTo('#/feed');
      page.same(visibleScreens(page), ['screen-feed'], 'after coming back');
      page.is(page.title, 'Feed - ' + APP_NAME, 'document.title after coming back');
      page.is(page.focused, page.el('title-feed'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'GET /api/members',
        'GET /api/balances',
        'GET /api/expenses',
        'GET /api/members'
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
      /* Two cookies, so the second needs its name trimmed, and a value that needs
         decoding: exactly what readCookie does, and what a request would carry raw if
         it stopped doing it. */
      page.setCookie('sl_session=opaque; sl_csrf=a%20token');
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
        { method: 'DELETE', path: '/session', body: NO_BODY },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
      /* Header values and not header names, on every recorded call. A name-only check
         passes a Content-Type of text/plain and an Accept that takes anything, and
         web.py refuses a state-changing request that carries either. The token is the
         decoded, trimmed value the jar held, so a raw or untrimmed one fails here. */
      page.calls.forEach((call, index) => {
        const at = 'call ' + index + ' (' + call.method + ' ' + call.url + ')';
        page.is(call.credentials, 'same-origin', at + ' credentials');
        page.same(
          call.headers,
          SAFE_METHODS.indexOf(call.method) === -1
            ? {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                'X-CSRF-Token': 'a token'
              }
            : /* A safe method changes nothing, so it carries neither a content type
                 nor a token. */
              { Accept: 'application/json' },
          at + ' headers'
        );
      });
    }
  },

  {
    /* The token the server rotated on the last response is the one the next request
       has to carry, so it is read from the cookie at request time and never cached. */
    name: 'the_csrf_token_is_read_at_request_time_not_cached',
    async run(page) {
      page.setCookie('sl_session=opaque; sl_csrf=first%20token');
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      page.setCookie('sl_session=opaque; sl_csrf=second%20token');
      await signIn(page, 'sam@example.com', 'hunter2');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
      page.is(page.calls[1].headers['X-CSRF-Token'], 'first token', 'the first POST');
      page.is(page.calls[2].headers['X-CSRF-Token'], 'second token', 'the second POST');
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
        { method: 'DELETE', path: '/session', body: NO_BODY }
      ]);
    }
  },

  {
    /* A refusal a screen asked for names something about that one request, so the
       screen that asked reports it in its own failure state and no curtain comes down
       over the whole frame. */
    name: 'a_refusal_a_screen_asked_for_leaves_the_app_frame_up',
    async run(page) {
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', missingRecord());
      await page.boot();
      appIsUp(page, 'a refusal the feed asked for');
      page.is(page.el('feed-error').hidden, false, '#feed-error hidden');
      /* Nothing was written on a paragraph nobody is looking at, either. */
      page.is(page.el('notice-problem').hidden, true, '#notice-problem hidden');
      page.is(page.el('notice-problem').textContent, '', '#notice-problem text');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    /* The handoff itself. This registers its own handler through the shipped
       window.SplitwiseApi after boot, which replaces app/app.js's onOffline for the
       rest of this scenario, so no screen state is asserted here: what it pins is
       that the whole error reaches whoever registered for it, unchanged, and that the
       caller is rejected with that same object. */
    name: 'the_whole_error_reaches_the_handler_that_registered_for_it',
    async run(page) {
      page.respondInOrder('GET', '/session', [noSession(), noGroupConfigured()]);
      await page.boot();
      page.global(
        'window.seen = null;' +
          'window.SplitwiseApi.onOffline(function (error) { window.seen = error; });' +
          'window.rejected = null;' +
          'window.SplitwiseApi.session().then(null, function (error) {' +
          '  window.rejected = error;' +
          '});'
      );
      await page.settle();
      page.is(page.global('window.seen.status'), 503, 'status');
      page.is(page.global('window.seen.code'), 'no_group_configured', 'code');
      page.is(page.global('window.seen.message'), NO_GROUP, 'message');
      page.is(page.global('window.seen.kind'), 'unavailable', 'kind');
      page.is(page.global('window.seen.say'), NO_GROUP, 'say');
      /* say is the message itself, not a copy of it that could drift. */
      page.is(page.global('window.seen.say === window.seen.message'), true, 'say');
      page.is(
        page.global('window.rejected === window.seen'),
        true,
        'the caller is rejected with the same object the handler saw'
      );
      page.is(
        page.global('window.rejected instanceof window.SplitwiseApi.ApiError'),
        true,
        'the rejection is an ApiError'
      );
      page.expectRequests(['GET /api/session', 'GET /api/session']);
    }
  },

  {
    /* What a rejected fetch puts in message, which nothing constrained until this
       scenario. It used to carry String(networkFailure), "TypeError: Failed to
       fetch", composed by this client rather than sent by the server, and a reviewer
       replaced it with a full user-facing sentence with the whole suite still green.
       say kept it off the screen either way, but say is assigned from message, so the
       invariant rested entirely on speaks() returning false for offline. It now rests
       on message being what the header says it is. Registers its own handler, so no
       screen state is asserted here. */
    name: 'a_rejected_fetch_carries_no_message_of_its_own',
    async run(page) {
      page.respondInOrder('GET', '/session', [noSession(), networkFailure()]);
      await page.boot();
      page.global(
        'window.seen = null;' +
          'window.SplitwiseApi.onOffline(function (error) { window.seen = error; });' +
          'window.SplitwiseApi.session().then(null, function () {});'
      );
      await page.settle();
      page.is(page.global('window.seen.kind'), 'offline', 'kind');
      /* A machine-readable sentinel, not prose, and the classifier reads the status
         rather than this. */
      page.is(page.global('window.seen.code'), 'offline', 'code');
      page.is(page.global('window.seen.message'), '', 'message');
      page.is(page.global('window.seen.say'), '', 'say');
      page.expectRequests(['GET /api/session', 'GET /api/session']);
    }
  },

  {
    /* A handler is a screen's code and a screen can have a bug in it. That must not
       change what the caller is rejected with, and must not swallow the rejection: a
       caller left waiting forever on a promise nobody settles is worse than the
       screen glitch that caused it. Registers its own handler, so no screen state is
       asserted here either. */
    name: 'a_handler_that_throws_does_not_stop_the_rejection_reaching_the_caller',
    async run(page) {
      page.respondInOrder('GET', '/session', [noSession(), serverError()]);
      await page.boot();
      page.global(
        'window.SplitwiseApi.onOffline(function () {' +
          '  throw new Error("this screen has a bug in it");' +
          '});' +
          'window.settled = "never";' +
          'window.SplitwiseApi.session().then(function () {' +
          '  window.settled = "resolved";' +
          '}, function (error) { window.settled = error; });'
      );
      await page.settle();
      page.is(page.global('typeof window.settled'), 'object', 'the promise rejected');
      page.is(page.global('window.settled.status'), 500, 'status');
      page.is(page.global('window.settled.kind'), 'unavailable', 'kind');
      page.is(page.global('window.settled.message'), GENERIC_500, 'message');
      page.is(
        page.global('window.settled instanceof window.SplitwiseApi.ApiError'),
        true,
        'the rejection is still the ApiError, not what the handler threw'
      );
      page.expectRequests(['GET /api/session', 'GET /api/session']);
    }
  },

  {
    /* The stub's own honesty check: a selector shape it does not support has to be a
       loud failure, so a screen task that introduces one widens the stub deliberately
       instead of quietly getting null back. */
    name: 'an_unsupported_selector_is_a_loud_failure_not_a_null',
    async run(page) {
      page.respond('GET', '/session', noSession());
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

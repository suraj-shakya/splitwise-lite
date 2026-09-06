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
  /* split_exact's refusal, which the add screen shows verbatim. */
  invalidSplit: 'invalid_split',
  emailAlreadyRegistered: 'email_already_registered',
  tooManyAttempts: 'too_many_attempts',
  /* The refusal the debts route composes for an id that is not in the roster,
     and for a self-pair. */
  malformedRequest: 'malformed_request',
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

    /* checked and type are reflected off their attributes the way hidden is, and both
       are here deliberately rather than incidentally: the guarded proxy refuses a set
       of any property the stub does not define, and the add screen creates checkboxes
       and text inputs at run time and sets all three mode radios explicitly when it
       clears the form. Reflecting checked also means a radio that ships with the
       attribute reads as checked before a line of app.js has run, which is what makes
       "equal across everyone is the default in the markup" checkable. */
    get checked() {
      return own.attributes.checked !== undefined;
    },
    set checked(on) {
      if (on) {
        own.attributes.checked = '';
      } else {
        delete own.attributes.checked;
      }
    },
    get type() {
      return own.attributes.type === undefined ? '' : own.attributes.type;
    },
    set type(value) {
      own.attributes.type = String(value);
    },

    /* Reflected off the attribute the way hidden and type are. app.js assigns an
       id to a region it built so the button controlling it can name that id in
       aria-controls: feedDetail's `detail.id = ...`, and task 13's detail regions. */
    get id() {
      return own.attributes.id === undefined ? '' : own.attributes.id;
    },
    set id(value) {
      own.attributes.id = String(value);
    },

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

function created(payload) {
  /* 201, which is what a recorded expense comes back as. api.js reads status, ok and
     json() and nothing else, so this is the whole of it. */
  return { status: 201, ok: true, json: () => Promise.resolve(payload) };
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
      /* The { text } shape the textContent getter above already understands. app.js
         composes a row out of text nodes so that a display name holding a `<` reaches
         the DOM as text: balancesNetRow, balancesTransferRow and task 13's rows. */
      createTextNode: (text) => ({ text: String(text) }),
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

/* --- Task 10: the add screen -------------------------------------------- */

/* Three members, in the order the roster endpoint returned them, so a screen that
   sorted, reversed or deduplicated the list fails on the option order alone.

   The acting member of A_MEMBER is mem-1, which is also the first member here, so
   against this fixture alone "the payer defaults to the acting member" and "the payer
   defaults to the top of the list" produce a byte-identical request body and neither
   can be told from the other. ADD_ACTING_SECOND is what separates them, and
   `choosing_a_different_payer_sends_that_member_as_the_payer` is what pins that the
   picker's own value is what goes out. On a shared ledger that field decides who is
   owed money, so it gets both. */
const ADD_ROSTER = {
  members: [
    { id: 'mem-1', display_name: 'Sam' },
    { id: 'mem-2', display_name: 'Ali' },
    { id: 'mem-3', display_name: 'Jo' }
  ]
};

/* The same three people with the acting member second. Roster order is preserved in
   the split either way, so this fixture asserts two different things at once: the
   default lands on whoever is entering rather than on whoever the roster happens to
   list first, and the member list still goes out in the order it arrived. */
const ADD_ACTING_SECOND = {
  members: [
    { id: 'mem-2', display_name: 'Ali' },
    { id: 'mem-1', display_name: 'Sam' },
    { id: 'mem-3', display_name: 'Jo' }
  ]
};

const ADD_ONE_MEMBER = { members: [{ id: 'mem-1', display_name: 'Sam' }] };

/* A roster that does not carry the acting member at all, which is what an operator
   who linked an account and then reshaped the group leaves behind. The default falls
   back to the first member in roster order, and nobody is marked as you. */
const ADD_WITHOUT_ACTING = {
  members: [
    { id: 'mem-2', display_name: 'Ali' },
    { id: 'mem-3', display_name: 'Jo' }
  ]
};

/* A 200 carrying the documented shape after it drifted: a member with no display
   name. That is a failure and never an empty group, and never a picker holding the
   word undefined. */
const ADD_BROKEN_ROSTER = { members: [{ id: 'mem-1' }] };

/* One 201 body in _expense_view shape, and deliberately not what any scenario types:
   the confirmation echoes the server or it says nothing, so a screen that rendered
   the typed text instead fails here. */
const ADD_CREATED = {
  expense: {
    id: 'exp-1',
    description: 'Milk',
    amount: '12.50',
    payer_id: 'mem-1',
    created_by: 'mem-1',
    created_at: '2026-09-03T08:00:00.000000',
    allocations: [
      { member_id: 'mem-1', amount: '4.17' },
      { member_id: 'mem-2', amount: '4.17' },
      { member_id: 'mem-3', amount: '4.16' }
    ]
  }
};

/* split_exact's own refusal, pinned by
   tests/test_web_api.py::test_exact_amounts_that_do_not_add_up_report_both_figures.
   Its figures are raw cents against dollars the person typed, and it is still shown
   word for word: the alternatives are inventing replacement copy for one code, which
   drifts from web.py the day either changes, or dividing by a hundred in JavaScript,
   which is the one thing this codebase exists to prevent. Raised as its own issue
   against src/splitwise_lite/split.py. */
const ADD_SUM_REFUSED = 'exact amounts sum to 950, not the total 1000';

/* Every body spelled out rather than rebuilt from the values a scenario typed in: a
   request whose payload is asserted against a copy of the code that built it asserts
   nothing. Four keys, in this order, and never currency, id, created_at, created_by
   or now, each of which web.py refuses by name. */
const ADD_EQUALLY = '{"description":"","amount":"12.50","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-1","mem-2","mem-3"]}}';
const ADD_WITHOUT_ALI = '{"description":"","amount":"12.50","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-1","mem-3"]}}';
const ADD_UNEVEN = '{"description":"","amount":"10.00","payer_id":"mem-1",' +
  '"split":{"mode":"exact","amounts":{"mem-1":"8.00","mem-3":"2.00"}}}';
const ADD_UNEVEN_SHORT = '{"description":"","amount":"10.00","payer_id":"mem-1",' +
  '"split":{"mode":"exact","amounts":{"mem-1":"8.00","mem-3":"1.50"}}}';
const ADD_DESCRIBED = '{"description":"what was typed","amount":"9.99",' +
  '"payer_id":"mem-1","split":{"mode":"equal",' +
  '"member_ids":["mem-1","mem-2","mem-3"]}}';
const ADD_ALONE = '{"description":"","amount":"12.50","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-1"]}}';
const ADD_MILK = '{"description":"Milk","amount":"12.50","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-1","mem-2","mem-3"]}}';
/* The acting member is second in the roster this one goes with, so the payer and the
   head of the member list are different ids and the body says which one the screen
   chose. */
const ADD_ACTING_PAYER = '{"description":"","amount":"12.50","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-2","mem-1","mem-3"]}}';
/* A payer the person picked by hand, and neither the acting member nor the first. */
const ADD_CHOSEN_PAYER = '{"description":"","amount":"12.50","payer_id":"mem-3",' +
  '"split":{"mode":"equal","member_ids":["mem-1","mem-2","mem-3"]}}';
const ADD_SECOND_SAVE = '{"description":"","amount":"3.00","payer_id":"mem-1",' +
  '"split":{"mode":"equal","member_ids":["mem-1","mem-2","mem-3"]}}';
/* The fallback payer: the first member, and not the last one and not the acting
   member the roster has no row for. */
const ADD_FALLBACK_PAYER = '{"description":"","amount":"12.50","payer_id":"mem-2",' +
  '"split":{"mode":"equal","member_ids":["mem-2","mem-3"]}}';

/* A second 201, so a save that follows a save is answered with a different echo and
   the confirmation cannot be a leftover of the first. Its description is empty, which
   is also what pins that no description is invented for an expense that has none. */
const ADD_CREATED_AGAIN = {
  expense: {
    id: 'exp-2',
    description: '',
    amount: '3.00',
    payer_id: 'mem-1',
    created_by: 'mem-1',
    created_at: '2026-09-03T09:00:00.000000',
    allocations: [
      { member_id: 'mem-1', amount: '1.00' },
      { member_id: 'mem-2', amount: '1.00' },
      { member_id: 'mem-3', amount: '1.00' }
    ]
  }
};

const ADD_MODES = ['add-mode-equal', 'add-mode-some', 'add-mode-exact'];

async function addBoot(page, roster) {
  /* Every add scenario starts on the add screen, so its request list is the session
     read and this screen's own roster read, with no feed or balances read involved.
     That is a screen which reads only on its own route working as designed. */
  page.startAt('#/add');
  page.respond('GET', '/session', ok(A_MEMBER));
  page.respond('GET', '/members', ok(roster));
  await page.boot();
}

async function addChooseMode(page, id) {
  /* What a browser does when a radio in a group is tapped: the group's other radios
     go unchecked, that one goes checked, and change fires on it. The stub models no
     radio group, so the scenario does that half rather than the screen doing it. */
  ADD_MODES.forEach((mode) => {
    page.el(mode).checked = mode === id;
  });
  await page.dispatch(page.el(id), 'change');
}

function addPayerOptions(page) {
  return page.el('add-payer').querySelectorAll('option');
}

function addPersonFields(page) {
  return page.query('.add-person input');
}

function addModeChecks(page) {
  return ADD_MODES.map((id) => page.el(id).checked);
}

function addRosterStates(page) {
  return ['add-roster-busy', 'add-roster-error', 'add-empty-roster'].map(
    (id) => !page.el(id).hidden
  );
}

function addErrorsShown(page) {
  return ['add-error-amount', 'add-error-roster', 'add-error-server'].map(
    (id) => !page.el(id).hidden
  );
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
  },

  /* --- Task 10: the add screen ------------------------------------------- */

  {
    /* The ten second requirement, in the only two facts that exist at the moment the
       roster read goes out: the keypad is already up, and the screen already says
       what it is doing. Focus is asserted while the add screen is the visible one,
       and the scenario below is its pair. */
    name: 'opening_add_focuses_the_amount_field_and_reads_the_roster',
    async run(page) {
      page.startAt('#/add');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/members', ok(ADD_ROSTER));
      let whenAsked = null;
      page.onRequest('GET', '/members', () => {
        whenAsked = {
          focused: page.focused === page.el('add-amount'),
          busy: !page.el('add-roster-busy').hidden,
          options: addPayerOptions(page).length
        };
      });
      await page.boot();
      page.same(
        whenAsked,
        { focused: true, busy: true, options: 0 },
        'when the roster read went out'
      );
      page.same(addRosterStates(page), [false, false, false], 'the roster states');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)', 'Ali', 'Jo'],
        '#add-payer option text'
      );
      page.same(
        addPayerOptions(page).map((option) => option.value),
        ['mem-1', 'mem-2', 'mem-3'],
        '#add-payer option values'
      );
      page.is(page.el('add-payer').value, 'mem-1', '#add-payer value');
      page.is(page.el('add-people').childNodes.length, 0, '#add-people rows');
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      page.is(page.el('add-currency').hidden, false, '#add-currency');
      page.is(page.el('add-currency-code').textContent, 'AUD', '#add-currency-code');
      page.expectRequests(['GET /api/session', 'GET /api/members']);
    }
  },

  {
    /* The pair to the focus assertion above. focus() on a hidden element is recorded
       as a focus anyway, per issue #37, so every focus claim here is made while the
       add screen is the visible one and paired with one that shows focus went
       elsewhere when it is not. */
    name: 'the_add_screen_takes_focus_only_while_it_is_the_current_screen',
    async run(page) {
      page.startAt('#/add');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/members', ok(ADD_ROSTER));
      page.respond('GET', '/expenses', ok(EMPTY_FEED));
      await page.boot();
      page.same(visibleScreens(page), ['screen-add'], 'the screens on show');
      page.is(page.focused, page.el('add-amount'), 'focus on entering add');
      await page.goTo('#/feed');
      page.same(visibleScreens(page), ['screen-feed'], 'after leaving');
      page.is(page.focused, page.el('title-feed'), 'focus after leaving');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        'GET /api/expenses',
        'GET /api/members'
      ]);
    }
  },

  {
    /* The common case, and the whole reason the screen is shaped the way it is: an
       amount and one tap. The payer, the description and the split need no input. */
    name: 'an_amount_and_one_tap_records_an_equal_split_across_everyone',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* "Everyone except one" is a single untick, and it still sends `equal`: split.py
       says equal across everyone and equal across a subset are both split_equally
       over the member list the caller assembles. */
    name: 'unticking_someone_sends_an_equal_split_over_the_rest',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      await addChooseMode(page, 'add-mode-some');
      const rows = addPersonFields(page);
      page.is(rows.length, 3, 'the people rows');
      page.same(
        rows.map((row) => row.type),
        ['checkbox', 'checkbox', 'checkbox'],
        'the row controls'
      );
      page.same(rows.map((row) => row.checked), [true, true, true], 'every row ticked');
      page.is(page.el('add-hint-some').hidden, false, '#add-hint-some');
      page.is(page.el('add-hint-exact').hidden, true, '#add-hint-exact');
      rows[1].checked = false;
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_WITHOUT_ALI }
      ]);
    }
  },

  {
    /* The shares go out as the characters that were typed, and a member left blank is
       left out of the request entirely, which is what "not sharing this one" means. */
    name: 'uneven_amounts_are_sent_as_strings_and_the_blanks_are_left_out',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '10.00';
      await addChooseMode(page, 'add-mode-exact');
      const rows = addPersonFields(page);
      page.is(rows.length, 3, 'the people rows');
      page.same(rows.map((row) => row.type), ['text', 'text', 'text'], 'the row controls');
      page.same(rows.map((row) => row.value), ['', '', ''], 'every row empty');
      page.is(page.el('add-hint-exact').hidden, false, '#add-hint-exact');
      page.is(page.el('add-hint-some').hidden, true, '#add-hint-some');
      /* Typed with surrounding whitespace, and the pinned body below is unchanged by
         it: what goes out is the characters that were typed with that whitespace
         removed and nothing else touched. No comma stripped, no digit padded. */
      rows[0].value = '  8.00 ';
      rows[2].value = '2.00 ';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_UNEVEN }
      ]);
    }
  },

  {
    /* The refusal that matters most, shown in the resolver's own words including its
       raw cent figures, and nothing the person typed is thrown away by it. */
    name: 'shares_that_do_not_add_up_show_the_resolvers_own_message_and_keep_the_draft',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond(
        'POST',
        '/expenses',
        failure(400, CODES.invalidSplit, ADD_SUM_REFUSED)
      );
      page.el('add-amount').value = '10.00';
      await addChooseMode(page, 'add-mode-exact');
      const rows = addPersonFields(page);
      rows[0].value = '8.00';
      rows[2].value = '1.50';
      await page.dispatch(page.el('add-form'), 'submit');
      appIsUp(page, 'a refused save');
      page.is(page.el('add-error').hidden, false, '#add-error');
      page.is(
        page.el('add-error-server').textContent,
        ADD_SUM_REFUSED,
        '#add-error-server text'
      );
      page.same(addErrorsShown(page), [false, false, true], 'the three error children');
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.is(page.el('add-amount').value, '10.00', '#add-amount');
      page.same(
        addPersonFields(page).map((row) => row.value),
        ['8.00', '', '1.50'],
        'the typed shares'
      );
      page.same(addModeChecks(page), [false, false, true], 'the three mode radios');
      page.is(page.el('add-submit').disabled, false, '#add-submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_UNEVEN_SHORT }
      ]);
    }
  },

  {
    /* One of the screen's own two refusals: a check on whether there is anything to
       send, not a judgement of an amount. parse_amount is the only judge, and asking
       it costs a save. */
    name: 'saving_with_no_amount_typed_asks_for_one_and_sends_nothing',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(page.el('add-error').hidden, false, '#add-error');
      page.same(addErrorsShown(page), [true, false, false], 'the three error children');
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.expectRequests(['GET /api/session', 'GET /api/members']);
    }
  },

  {
    /* The confirmation is evidence rather than a claim: every word of it comes from
       the 201 body and none of it from what was typed. The screen stays where it is,
       so a second receipt is ten seconds again. */
    name: 'a_successful_save_clears_the_form_and_confirms_from_the_response',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      /* Both typed with surrounding whitespace, and both pinned below without it. */
      page.el('add-amount').value = ' 9.99';
      page.el('add-description').value = '  what was typed  ';
      await addChooseMode(page, 'add-mode-some');
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(page.el('add-saved').hidden, false, '#add-saved');
      page.is(page.el('add-saved-amount').textContent, '12.50', '#add-saved-amount');
      page.is(
        page.el('add-saved-description').textContent,
        ' for Milk',
        '#add-saved-description'
      );
      page.is(page.el('add-amount').value, '', '#add-amount');
      page.is(page.el('add-description').value, '', '#add-description');
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      page.is(page.el('add-people').childNodes.length, 0, '#add-people rows');
      page.is(page.el('add-payer').value, 'mem-1', '#add-payer value');
      page.same(addErrorsShown(page), [false, false, false], 'the three error children');
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.is(page.hash, '#/add', 'location.hash');
      page.same(page.pushStates, [], 'history.pushState');
      page.same(page.replaceStates, [], 'history.replaceState');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_DESCRIBED }
      ]);
    }
  },

  {
    /* A 403 that is not member_not_linked, which announce() passes straight through
       to the caller. The screen shows the server's message and neither curtain
       appears. */
    name: 'a_stale_form_refused_by_the_server_says_so_on_the_screen',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', csrfRefused());
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      appIsUp(page, 'a stale form');
      page.is(page.el('notice-unlinked').hidden, true, '#notice-unlinked');
      page.is(page.el('notice-offline').hidden, true, '#notice-offline');
      page.is(
        page.el('add-error-server').textContent,
        'That form went stale.',
        '#add-error-server text'
      );
      page.same(addErrorsShown(page), [false, false, true], 'the three error children');
      page.is(page.el('add-amount').value, '12.50', '#add-amount');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* Observed when the request goes out, because that is the only moment it exists,
       and asserted after settling. Whether a disabled control really refuses a tap is
       browser-only and is not claimed here. */
    name: 'the_save_control_is_disabled_while_the_save_is_in_flight',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      let inFlight = null;
      page.onRequest('POST', '/expenses', () => {
        inFlight = {
          disabled: page.el('add-submit').disabled,
          saving: !page.el('add-saving').hidden
        };
      });
      page.el('add-amount').value = '12.50';
      page.is(page.el('add-submit').disabled, false, '#add-submit before');
      page.is(page.el('add-saving').hidden, true, '#add-saving before');
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(
        inFlight,
        { disabled: true, saving: true },
        'while the save was in flight'
      );
      page.is(page.el('add-submit').disabled, false, '#add-submit afterwards');
      page.is(page.el('add-saving').hidden, true, '#add-saving afterwards');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* The screen's own in-flight flag is the guard, not the disabled attribute: the
       form's submit listener is re-invoked directly through the stub's listeners map
       while the first request is still in the air, which is what a dispatched submit
       does whatever the control looks like. */
    name: 'a_second_submit_while_the_first_is_in_flight_sends_one_request',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      let again = true;
      page.onRequest('POST', '/expenses', () => {
        if (!again) {
          return;
        }
        /* Once only. A screen without the flag would otherwise recurse rather than
           fail with a readable request list. */
        again = false;
        const event = {
          type: 'submit',
          defaultPrevented: false,
          preventDefault() {
            event.defaultPrevented = true;
          }
        };
        (page.el('add-form').listeners.submit || []).forEach((handler) =>
          handler(event)
        );
      });
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(again, false, 'the second submit ran');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* A roster that did not arrive is not an empty group and must never read as one,
       and it never costs the person what they have typed. */
    name: 'a_roster_that_does_not_arrive_offers_a_retry_and_keeps_what_was_typed',
    async run(page) {
      page.startAt('#/add');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respondInOrder('GET', '/members', [unreadable(404), ok(ADD_ROSTER)]);
      await page.boot();
      page.same(addRosterStates(page), [false, true, false], 'the roster states');
      page.is(page.el('add-payer').childNodes.length, 0, '#add-payer options');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(addErrorsShown(page), [false, true, false], 'the three error children');
      await page.dispatch(page.el('add-roster-retry'), 'click');
      page.same(addRosterStates(page), [false, false, false], 'after the retry');
      page.is(page.el('add-amount').value, '12.50', '#add-amount after the retry');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)', 'Ali', 'Jo'],
        '#add-payer option text'
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        'GET /api/members'
      ]);
    }
  },

  {
    /* A flat of one is a real group, and nothing on the screen says anything special
       about it: the same form, the same states and the same split shape. */
    name: 'a_group_with_one_member_still_records_an_expense',
    async run(page) {
      await addBoot(page, ADD_ONE_MEMBER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.same(addRosterStates(page), [false, false, false], 'the roster states');
      page.same(addErrorsShown(page), [false, false, false], 'the three error children');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)'],
        '#add-payer option text'
      );
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_ALONE }
      ]);
    }
  },

  {
    /* Reachable through a half-finished setup_group.py run. There is nobody to share
       an expense with, so the screen says so and sends nothing. */
    name: 'a_group_with_no_members_says_so_and_saves_nothing',
    async run(page) {
      await addBoot(page, EMPTY_ROSTER);
      page.same(addRosterStates(page), [false, false, true], 'the roster states');
      page.is(page.el('add-payer').childNodes.length, 0, '#add-payer options');
      page.is(page.el('add-people').childNodes.length, 0, '#add-people rows');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(addErrorsShown(page), [false, true, false], 'the three error children');
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.expectRequests(['GET /api/session', 'GET /api/members']);
    }
  },

  {
    /* The offline notice is api.js's and covers the whole frame. This screen writes
       nothing underneath it and throws nothing away, which is what makes that
       notice's standing promise, "nothing you have recorded is lost", true here. */
    name: 'a_save_that_gets_no_answer_never_says_it_saved',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', networkFailure());
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await page.dispatch(page.el('add-form'), 'submit');
      noticeIsUp(page, 'offline', 'a save that got no answer', true);
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.is(page.el('add-error').hidden, true, '#add-error');
      page.same(addErrorsShown(page), [false, false, false], 'the three error children');
      page.is(page.el('add-error-server').textContent, '', '#add-error-server text');
      page.is(page.el('add-amount').value, '12.50', '#add-amount');
      page.is(page.el('add-description').value, 'Milk', '#add-description');
      page.is(page.el('add-submit').disabled, false, '#add-submit');
      page.is(page.el('add-saving').hidden, true, '#add-saving');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_MILK }
      ]);
    }
  },

  {
    /* The payer decides who is owed money on a shared ledger, so the default gets a
       roster whose first member is not the acting one. Against a roster headed by the
       acting member the two rules answer the same id and neither is falsifiable. */
    name: 'the_payer_defaults_to_whoever_is_entering_not_to_the_top_of_the_roster',
    async run(page) {
      await addBoot(page, ADD_ACTING_SECOND);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Ali', 'Sam (you)', 'Jo'],
        '#add-payer option text'
      );
      page.is(page.el('add-payer').value, 'mem-1', '#add-payer value');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_ACTING_PAYER }
      ]);
    }
  },

  {
    /* Recording that a flatmate paid is a normal entry, not an impersonation, and the
       picker's own value is what goes out: neither the default nor the head of the
       roster can stand in for it. */
    name: 'choosing_a_different_payer_sends_that_member_as_the_payer',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      page.el('add-payer').value = 'mem-3';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_CHOSEN_PAYER }
      ]);
    }
  },

  {
    /* Without preventDefault the browser submits the form itself, which is a full page
       navigation on Save. The worker answers a navigation from the cache, so the shell
       comes straight back and it looks like it worked while nothing was recorded. The
       gate has this same assertion for the same reason. */
    name: 'the_add_form_never_lets_the_browser_navigate',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      const event = await page.dispatch(page.el('add-form'), 'submit');
      page.is(event.defaultPrevented, true, 'preventDefault on the submit event');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* A 200 whose body is not the documented shape is a failure, not an empty group
       and not a picker full of blanks. */
    name: 'a_roster_that_arrives_in_the_wrong_shape_is_a_failure_not_an_empty_group',
    async run(page) {
      await addBoot(page, ADD_BROKEN_ROSTER);
      page.same(addRosterStates(page), [false, true, false], 'the roster states');
      page.is(page.el('add-payer').childNodes.length, 0, '#add-payer options');
      page.is(page.el('add-people').childNodes.length, 0, '#add-people rows');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(addErrorsShown(page), [false, true, false], 'the three error children');
      page.expectRequests(['GET /api/session', 'GET /api/members']);
    }
  },

  {
    /* Entering three receipts in a row is the flow this screen stays on #/add for, so
       it is the flow that gets a scenario. The confirmation belongs to the save that
       produced it and is cleared at the start of the next one, observed at the only
       moment that fact exists. */
    name: 'a_second_save_clears_the_first_confirmation_before_it_goes_out',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respondInOrder('POST', '/expenses', [
        created(ADD_CREATED),
        created(ADD_CREATED_AGAIN)
      ]);
      let posts = 0;
      let atSecond = null;
      page.onRequest('POST', '/expenses', () => {
        posts += 1;
        if (posts === 2) {
          atSecond = {
            saved: !page.el('add-saved').hidden,
            anyError: !page.el('add-error').hidden
          };
        }
      });
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(page.el('add-saved').hidden, false, '#add-saved after the first save');
      page.is(page.el('add-saved-amount').textContent, '12.50', 'the first figure');
      page.el('add-amount').value = '3.00';
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(
        atSecond,
        { saved: false, anyError: false },
        'when the second save went out'
      );
      page.is(page.el('add-saved').hidden, false, '#add-saved after the second save');
      page.is(page.el('add-saved-amount').textContent, '3.00', 'the second figure');
      /* The second expense came back with no description, and none is invented. */
      page.is(page.el('add-saved-description').textContent, '', 'the second description');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY },
        { method: 'POST', path: '/expenses', body: ADD_SECOND_SAVE }
      ]);
    }
  },

  {
    /* Correcting a refused entry and saving it is the other half of that flow. A
       message about the attempt that failed must not still be on screen beside a
       confirmation for the one that worked. */
    name: 'a_refused_save_followed_by_a_good_one_leaves_no_stale_message',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respondInOrder('POST', '/expenses', [
        failure(400, CODES.invalidSplit, ADD_SUM_REFUSED),
        created(ADD_CREATED)
      ]);
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(addErrorsShown(page), [false, false, true], 'after the refusal');
      page.is(page.el('add-saved').hidden, true, '#add-saved after the refusal');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(page.el('add-saved').hidden, false, '#add-saved after the good save');
      page.is(page.el('add-error').hidden, true, '#add-error after the good save');
      page.same(addErrorsShown(page), [false, false, false], 'after the good save');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY },
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* Every visit starts a fresh entry, and this is the only add scenario that returns
       to the route, which is what makes the block's own hashchange listener visible at
       all: the fields are cleared, the confirmation is gone, the mode is back to
       Equally, and the picker holds three options rather than six. */
    name: 'leaving_add_and_coming_back_starts_a_fresh_entry',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('GET', '/expenses', ok(EMPTY_FEED));
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await addChooseMode(page, 'add-mode-some');
      await page.dispatch(page.el('add-form'), 'submit');
      page.is(page.el('add-saved').hidden, false, '#add-saved before leaving');
      /* Typed again after the save, so the fields hold something at the moment the
         route is left: asserting they are empty afterwards says nothing if the save
         had already emptied them. */
      page.el('add-amount').value = '7.00';
      page.el('add-description').value = 'half typed';
      await page.goTo('#/feed');
      await page.goTo('#/add');
      page.is(page.el('add-amount').value, '', '#add-amount');
      page.is(page.el('add-description').value, '', '#add-description');
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.is(page.el('add-error').hidden, true, '#add-error');
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      page.is(page.el('add-people').childNodes.length, 0, '#add-people rows');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)', 'Ali', 'Jo'],
        '#add-payer option text'
      );
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_MILK },
        'GET /api/expenses',
        'GET /api/members',
        'GET /api/members'
      ]);
    }
  },

  {
    /* The other half of the payer default. An account linked to a member the group no
       longer carries still gets a working picker: the first member in roster order,
       never the last, and no name is marked as the person holding the phone. */
    name: 'a_roster_without_the_acting_member_defaults_to_the_first_one',
    async run(page) {
      await addBoot(page, ADD_WITHOUT_ACTING);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Ali', 'Jo'],
        '#add-payer option text'
      );
      page.is(page.el('add-payer').value, 'mem-2', '#add-payer value');
      page.el('add-amount').value = '12.50';
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_FALLBACK_PAYER }
      ]);
    }
  },

  {
    /* Switching modes rebuilds the people list from the held roster, and rebuilding
       means replacing rather than adding to it: a member named twice in a split is a
       400 at best and a wrong share at worst. */
    name: 'switching_modes_twice_still_names_every_member_once',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', created(ADD_CREATED));
      page.el('add-amount').value = '12.50';
      await addChooseMode(page, 'add-mode-some');
      await addChooseMode(page, 'add-mode-exact');
      await addChooseMode(page, 'add-mode-some');
      const rows = addPersonFields(page);
      page.is(rows.length, 3, 'the people rows');
      page.same(rows.map((row) => row.type), ['checkbox', 'checkbox', 'checkbox'], 'the row controls');
      await page.dispatch(page.el('add-form'), 'submit');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY }
      ]);
    }
  },

  {
    /* The fast path this screen is built for, and the one that produced a false
       sentence. The amount stays typeable while the roster is in the air on purpose,
       so saving during that window is a normal thing to do; it is refused, correctly,
       because there is nobody to share the expense with yet. The moment the roster
       lands that sentence stops being true and has to go.

       The second half pins that the clear is scoped to the one child the roster owns.
       A bare addShowError('') here would also withdraw a message the server sent about
       a refused save, which is still true and is not this screen's to take back. That
       state is not reachable by tapping today, because the retry control only appears
       while the roster panel is up and a server refusal needs a roster in hand; the
       retry listener is invoked directly, and this assertion exists so the scope of
       the clear survives a later change that does make it reachable. */
    name: 'a_save_refused_while_the_roster_loads_stops_saying_so_once_it_arrives',
    async run(page) {
      page.startAt('#/add');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respondInOrder('GET', '/members', [ok(ADD_ROSTER), ok(ADD_ROSTER)]);
      page.respond(
        'POST',
        '/expenses',
        failure(400, CODES.invalidSplit, ADD_SUM_REFUSED)
      );
      let reads = 0;
      let duringLoad = null;
      page.onRequest('GET', '/members', () => {
        reads += 1;
        if (reads !== 1) {
          return;
        }
        /* Typed and saved while the read is still in the air, which is exactly what
           the screen invites by leaving the field focused and usable throughout. The
           form's own submit listener is what a tap on Save reaches. */
        page.el('add-amount').value = '12.50';
        const event = {
          type: 'submit',
          defaultPrevented: false,
          preventDefault() {
            event.defaultPrevented = true;
          }
        };
        (page.el('add-form').listeners.submit || []).forEach((handler) =>
          handler(event)
        );
        duringLoad = addErrorsShown(page);
      });
      await page.boot();
      page.same(duringLoad, [false, true, false], 'while the roster was in flight');
      page.same(addErrorsShown(page), [false, false, false], 'once the roster arrived');
      page.is(page.el('add-error').hidden, true, '#add-error once the roster arrived');
      page.is(page.el('add-amount').value, '12.50', '#add-amount');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)', 'Ali', 'Jo'],
        '#add-payer option text'
      );
      await page.dispatch(page.el('add-form'), 'submit');
      page.same(addErrorsShown(page), [false, false, true], 'after the refused save');
      await page.dispatch(page.el('add-roster-retry'), 'click');
      page.same(
        addErrorsShown(page),
        [false, false, true],
        'after a roster read that followed a server refusal'
      );
      page.is(
        page.el('add-error-server').textContent,
        ADD_SUM_REFUSED,
        '#add-error-server text'
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_EQUALLY },
        'GET /api/members'
      ]);
    }
  },
  /* --- Task 43: a screen waits for a session, and a draft survives signing back
         in ------------------------------------------------------------------ */

  {
    /* Three route changes with the gate up. Nothing is read, focus stays in the
       gate, and the sentence the server sent about the refused sign-in is still
       there to read afterwards: a request nobody asked for takes a 401, and that
       401 blanks #gate-error and refocuses #gate-title on its way past, so a person
       who pressed Back would lose what they had just been told. Everything render()
       does apart from moving focus is unchanged, which is why the screens, the tab
       and the title are asserted here as well. */
    name: 'a_route_change_behind_the_gate_asks_for_nothing_and_leaves_the_gate_alone',
    async run(page) {
      page.respond('GET', '/session', noSession());
      page.respond('POST', '/session', refusal(REFUSED));
      await page.boot();
      await signIn(page, 'sam@example.com', 'hunter2');
      page.is(
        page.el('gate-error').textContent,
        REFUSED,
        '#gate-error text before the route changes'
      );
      /* Set directly, so the claim that the add screen left it alone is falsifiable:
         a screen that cleared it would otherwise be indistinguishable from one that
         never ran at all. */
      page.el('add-amount').value = '12.50';
      await page.goTo('#/add');
      await page.goTo('#/balances');
      page.same(visibleScreens(page), ['screen-balances'], 'the screens on show');
      page.same(currentTabs(page), ['#/balances'], 'aria-current');
      page.is(page.title, 'Balances - ' + APP_NAME, 'document.title');
      await page.goTo('#/feed');
      gateIsUp(page, 'after three route changes behind the gate');
      page.is(page.focused, page.el('gate-title'), 'focus');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, REFUSED, '#gate-error text');
      page.is(page.el('add-amount').value, '12.50', '#add-amount');
      page.same(visibleScreens(page), ['screen-feed'], 'the screens at the end');
      page.expectRequests([
        'GET /api/session',
        { method: 'POST', path: '/session', body: SIGN_IN_BODY }
      ]);
    }
  },

  {
    /* The same three route changes with the not-linked notice up. A session view is
       held here and it carries no member, which is what says no: every endpoint
       these three screens read refuses an account nobody has linked, by name. */
    name: 'a_route_change_behind_the_not_linked_notice_asks_for_nothing',
    async run(page) {
      page.respond('GET', '/session', ok(NO_MEMBER));
      await page.boot();
      await page.goTo('#/add');
      await page.goTo('#/balances');
      await page.goTo('#/feed');
      noticeIsUp(page, 'unlinked', 'three route changes behind the notice', true);
      page.is(
        page.global('window.SplitwiseApi.cachedSession().member'),
        null,
        'the cached session view carries no member'
      );
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* The case a session check on its own cannot catch. A 500 raises a curtain and
       leaves the cached session view exactly where it was, which is api.js's
       decision and stands, so this client still holds a live and linked session
       while nobody can see the ledger. What refuses the three reads here is that
       show() last raised a notice, and nothing else would. */
    name: 'a_route_change_under_a_curtain_a_live_session_raised_asks_for_nothing',
    async run(page) {
      page.startAt('#/balances');
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/members', ok(EMPTY_ROSTER));
      page.respond('GET', '/balances', serverError());
      await page.boot();
      noticeIsUp(page, 'problem', 'a 500 answering the balances read', true);
      await page.goTo('#/feed');
      await page.goTo('#/add');
      await page.goTo('#/balances');
      noticeIsUp(page, 'problem', 'three route changes under the curtain', true);
      page.is(
        page.el('notice-problem').textContent,
        GENERIC_500,
        '#notice-problem text'
      );
      page.is(
        page.global('window.SplitwiseApi.cachedSession().member.id'),
        'mem-1',
        'the session this curtain went up over is still live and still linked'
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        'GET /api/balances'
      ]);
    }
  },

  {
    /* With no client there is nothing to ask and nothing to ask it with. Whether one
       is loaded is read before anything is read off it, so a hashchange that arrives
       before the client has loaded, or after it has failed to load at all, returns
       rather than throwing on its way to the offline curtain. */
    name: 'a_route_change_with_no_api_client_loaded_asks_for_nothing',
    async run(page) {
      page.absent('api.js');
      await page.boot();
      await page.goTo('#/add');
      await page.goTo('#/balances');
      await page.goTo('#/feed');
      noticeIsUp(page, 'offline', 'three route changes with no client', false);
      page.is(page.global('typeof window.SplitwiseApi'), 'undefined', 'SplitwiseApi');
      page.expectRequests([]);
    }
  },

  {
    /* Both retry controls, each clicked while its own screen's route is the current
       one, so the route guard cannot be what refuses them and the session guard is
       what does. Neither read even reaches its in-flight state. */
    name: 'the_retry_controls_behind_the_gate_ask_for_nothing',
    async run(page) {
      page.respond('GET', '/session', noSession());
      await page.boot();
      await page.dispatch(page.el('feed-retry'), 'click');
      await page.goTo('#/add');
      await page.dispatch(page.el('add-roster-retry'), 'click');
      gateIsUp(page, 'after both retry controls behind the gate');
      page.is(page.focused, page.el('gate-title'), 'focus');
      page.is(page.el('feed-loading').hidden, true, '#feed-loading');
      page.same(addRosterStates(page), [false, false, false], 'the roster states');
      page.expectRequests(['GET /api/session']);
    }
  },

  {
    /* The 401 keeps everything typed, which is today's behaviour and is pinned here
       at the mid-point. Then the person does the one thing the gate is telling them
       to do, and it is all still there afterwards: the curtain coming down on a
       screen they never left is not a visit to it. The roster is read again and the
       picker rebuilt, so the marker and the default payer are true for whoever is
       signed in now. */
    name: 'an_interrupted_save_keeps_what_was_typed_through_signing_back_in',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', sessionDied(EXPIRED));
      page.respond('POST', '/session', ok(A_MEMBER));
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await page.dispatch(page.el('add-form'), 'submit');
      gateIsUp(page, 'a save the session did not survive');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, EXPIRED, '#gate-error text');
      page.is(
        page.el('add-amount').value,
        '12.50',
        '#add-amount while the gate is up'
      );
      page.is(
        page.el('add-description').value,
        'Milk',
        '#add-description while the gate is up'
      );
      page.is(page.el('add-submit').disabled, false, '#add-submit');
      await signIn(page, 'sam@example.com', 'hunter2');
      appIsUp(page, 'after signing back in');
      page.is(
        page.el('add-amount').value,
        '12.50',
        '#add-amount after signing back in'
      );
      page.is(
        page.el('add-description').value,
        'Milk',
        '#add-description after signing back in'
      );
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.is(page.el('add-error').hidden, true, '#add-error');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam (you)', 'Ali', 'Jo'],
        '#add-payer option text'
      );
      page.is(page.el('add-payer').value, 'mem-1', '#add-payer value');
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_MILK },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* What a resume keeps and what it rebuilds, pinned as a decision rather than
       left as an accident. The mode stays on uneven amounts, because returning it to
       Equally would silently turn three uneven shares into an even split, which is a
       wrong ledger entry one tap away; the rows come back empty, because the roster
       read rebuilds them, and rebuilding is what keeps the marker and the default
       payer true for whoever is holding the phone now. */
    name: 'an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', sessionDied(EXPIRED));
      page.respond('POST', '/session', ok(A_MEMBER));
      page.el('add-amount').value = '10.00';
      await addChooseMode(page, 'add-mode-exact');
      const shares = addPersonFields(page);
      shares[0].value = '8.00';
      shares[2].value = '1.50';
      await page.dispatch(page.el('add-form'), 'submit');
      gateIsUp(page, 'a save the session did not survive');
      /* Held at the mid-point, so "rebuilt empty" below is a change and not a field
         that was empty all along. */
      page.same(
        addPersonFields(page).map((row) => row.value),
        ['8.00', '', '1.50'],
        'the typed shares while the gate is up'
      );
      await signIn(page, 'sam@example.com', 'hunter2');
      appIsUp(page, 'after signing back in');
      page.is(page.el('add-amount').value, '10.00', '#add-amount');
      page.same(addModeChecks(page), [false, false, true], 'the three mode radios');
      page.same(
        addPersonFields(page).map((row) => row.value),
        ['', '', ''],
        'the share fields, rebuilt empty'
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_UNEVEN_SHORT },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* A visit that really ended takes the draft with it, and a flat shares phones:
       without this, Sam types an expense, signs out, and Ali signs in to find Sam's
       amount and description sitting in the form with Ali named as the payer. It is
       still empty when the next sign-in brings the frame back, because a resume
       clears nothing and there is nothing left to keep. */
    name: 'signing_out_clears_the_draft_before_the_next_person_signs_in',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('DELETE', '/session', noContent());
      page.respond('POST', '/session', ok(A_MEMBER));
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await addChooseMode(page, 'add-mode-exact');
      await page.dispatch(page.el('sign-out'), 'click');
      gateIsUp(page, 'after signing out');
      page.is(page.el('add-amount').value, '', '#add-amount after signing out');
      page.is(
        page.el('add-description').value,
        '',
        '#add-description after signing out'
      );
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      await signIn(page, 'sam@example.com', 'hunter2');
      appIsUp(page, 'the next person signing in');
      page.is(page.el('add-amount').value, '', '#add-amount');
      page.is(page.el('add-description').value, '', '#add-description');
      page.same(
        addModeChecks(page),
        [true, false, false],
        'the three mode radios after signing in'
      );
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'DELETE', path: '/session', body: NO_BODY },
        { method: 'POST', path: '/session', body: SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* A sign out the server refused did not end the visit, so it takes nothing with
       it. The curtain over it is the client's, escalated because the sign out button
       discards its own rejection and nobody else speaks for this one. */
    name: 'a_sign_out_the_server_refuses_leaves_the_draft_alone',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('DELETE', '/session', csrfRefused());
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await page.dispatch(page.el('sign-out'), 'click');
      noticeIsUp(page, 'problem', 'a refused sign out', true);
      page.is(page.el('notice-problem').textContent, STALE_FORM, '#notice-problem text');
      page.is(page.el('add-amount').value, '12.50', '#add-amount');
      page.is(page.el('add-description').value, 'Milk', '#add-description');
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'DELETE', path: '/session', body: NO_BODY }
      ]);
    }
  },

  {
    /* The phone changes hands, and nobody signs out anywhere in this. A 401 on save
       is the dominant way a curtain comes down over a live draft, and it is the path
       this whole guard exists to serve: Sam types, saves, takes the 401, and hands
       the phone to Ali, who signs in. What Sam typed is not Ali's to save, and the
       picker rebuilt for Ali names Ali as the payer of it, which is a wrong ledger
       entry one tap away. So the resume asks who is coming back rather than assuming
       it is the person who left, and starts a fresh entry for anybody else.

       Held at the mid-point, so "empty afterwards" is a change and not a field that
       was empty all along. */
    name: 'a_401_on_save_then_a_different_person_signs_in_starts_a_fresh_entry',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', sessionDied(EXPIRED));
      page.el('add-amount').value = '12.50';
      page.el('add-description').value = 'Milk';
      await page.dispatch(page.el('add-form'), 'submit');
      gateIsUp(page, 'a save the session did not survive');
      page.is(
        page.el('add-amount').value,
        '12.50',
        "Sam's #add-amount while the gate is up"
      );
      page.is(
        page.el('add-description').value,
        'Milk',
        "Sam's #add-description while the gate is up"
      );
      /* Somebody else entirely: another account, another member row. */
      page.respond('POST', '/session', ok(A_SECOND_MEMBER));
      page.respond('GET', '/session', ok(A_SECOND_MEMBER));
      await signIn(page, 'ali@example.com', 'opensesame');
      appIsUp(page, 'after a different person signs in');
      page.is(page.el('add-amount').value, '', "Sam's draft amount shown to Ali");
      page.is(
        page.el('add-description').value,
        '',
        "Sam's draft description shown to Ali"
      );
      page.is(page.el('add-saved').hidden, true, '#add-saved');
      page.is(page.el('add-error').hidden, true, '#add-error');
      page.same(
        addPayerOptions(page).map((option) => option.textContent),
        ['Sam', 'Ali (you)', 'Jo'],
        '#add-payer option text'
      );
      page.is(page.el('add-payer').value, 'mem-2', '#add-payer value');
      page.is(page.focused, page.el('add-amount'), 'focus');
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_MILK },
        { method: 'POST', path: '/session', body: SECOND_SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* The exception a resume makes for the split mode is an exception for the person
       who chose it, not for the phone. Sam's Exact and the shares under it go with
       the amount and the description when somebody else signs in, so Ali's fresh
       entry cannot open on three uneven shares nobody sitting at it typed. The mirror
       of an_interrupted_save_keeps_the_split_mode_and_rebuilds_the_person_rows, which
       pins the same act for the same person coming back. */
    name: 'a_401_on_save_then_a_different_person_signs_in_returns_the_split_to_equally',
    async run(page) {
      await addBoot(page, ADD_ROSTER);
      page.respond('POST', '/expenses', sessionDied(EXPIRED));
      page.el('add-amount').value = '10.00';
      await addChooseMode(page, 'add-mode-exact');
      const shares = addPersonFields(page);
      shares[0].value = '8.00';
      shares[2].value = '1.50';
      await page.dispatch(page.el('add-form'), 'submit');
      gateIsUp(page, 'a save the session did not survive');
      page.same(
        addModeChecks(page),
        [false, false, true],
        'the mode while the gate is up'
      );
      page.same(
        addPersonFields(page).map((row) => row.value),
        ['8.00', '', '1.50'],
        "Sam's typed shares while the gate is up"
      );
      page.respond('POST', '/session', ok(A_SECOND_MEMBER));
      page.respond('GET', '/session', ok(A_SECOND_MEMBER));
      await signIn(page, 'ali@example.com', 'opensesame');
      appIsUp(page, 'after a different person signs in');
      page.is(page.el('add-amount').value, '', '#add-amount');
      page.same(addModeChecks(page), [true, false, false], 'the three mode radios');
      /* Gone rather than rebuilt empty: Equally shows no per-person row at all, so
         the rows Sam's Exact put up are not there for Ali to inherit either. */
      page.same(
        addPersonFields(page).map((row) => row.value),
        [],
        "the person rows Sam's Exact put up"
      );
      page.expectRequests([
        'GET /api/session',
        'GET /api/members',
        { method: 'POST', path: '/expenses', body: ADD_UNEVEN_SHORT },
        { method: 'POST', path: '/session', body: SECOND_SIGN_IN_BODY },
        'GET /api/session',
        'GET /api/members'
      ]);
    }
  },

  {
    /* Task 12a. api.debt is the whole of what that task adds to app/, and no screen
       calls it yet: issue #14 owns the drill-down. So this boots to the app, starts the
       request through the shipped client itself, and reads the payload back off the
       promise rather than off the page. Nothing is rendered, so this scenario reaches
       for no part of the DOM stub: document.createTextNode and an element id property
       are there for issue #14's drill-down, and an element type property has been
       there since the add screen.

       The fixture is a local rather than a module constant on purpose: this file is
       being edited on another branch at the same time, and one appended block conflicts
       with less than a constant threaded into the fixtures above.

       Real member ids come from new_id() and are plain UUIDs, but the roster an
       operator writes is not bound to that, so both ids here carry a space, a percent
       sign and a hash, and the declared request list holds the exact encoded path. */
    name: 'the_api_client_builds_a_debt_path_from_two_ids',
    async run(page) {
      const debtView = {
        currency: 'AUD',
        debtor_id: 'a b',
        creditor_id: 'c%d#e',
        amount: '5.50',
        direction: 'owes',
        entries: [
          {
            kind: 'expense',
            effect: 'adds',
            id: 'exp-1',
            description: 'Milk',
            created_at: '2026-09-05T09:00:00.000000+00:00',
            amount: '5.50'
          }
        ]
      };
      screensLoad(page);
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/debts/a%20b/c%25d%23e', ok(debtView));
      await page.boot();
      page.global(
        'window.debt = null;' +
          "window.SplitwiseApi.debt('a b', 'c%d#e').then(function (view) {" +
          '  window.debt = view;' +
          '});'
      );
      /* settle() drives nothing and drains what is already in flight, which is what it
         exists for: this scenario starts a request through the client rather than
         through an affordance on the page. */
      await page.settle();
      page.is(page.global('window.debt.amount'), '5.50', 'amount');
      page.is(page.global('window.debt.direction'), 'owes', 'direction');
      page.is(page.global('window.debt.entries.length'), 1, 'entries');
      page.is(page.global('window.debt.entries[0].effect'), 'adds', 'effect');
      page.expectRequests([
        'GET /api/session',
        'GET /api/expenses',
        'GET /api/members',
        'GET /api/debts/a%20b/c%25d%23e'
      ]);
    }
  },

  {
    /* Task 13, the mixed shape, which is task 5's own worked fixture: one payment
       made of more than one debt, with a direct debt among them appearing in both
       lists. One debt here is only partly covered, so both readings of a debt row
       are on screen at once. Sam is the acting member, so every mention of Sam
       carries ` (you)` inside the drill-down as it does in the two outer lists. */
    name: 'opening_a_suggested_payment_shows_both_ends_of_it',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Ali' },
          { id: 'mem-3', display_name: 'Cass' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [
          { member_id: 'mem-1', amount: '600.00', direction: 'owes' },
          { member_id: 'mem-2', amount: '600.00', direction: 'owed' },
          { member_id: 'mem-3', amount: '0.00', direction: 'settled' }
        ],
        transfers: [
          {
            from_member_id: 'mem-1',
            to_member_id: 'mem-2',
            amount: '600.00',
            payer_debts: [
              absorbed('mem-1', 'mem-2', '300.00', '300.00', true),
              absorbed('mem-1', 'mem-3', '300.00', '500.00', false)
            ],
            receiver_credits: [
              absorbed('mem-1', 'mem-2', '300.00', '300.00', true),
              absorbed('mem-3', 'mem-2', '300.00', '300.00', true)
            ]
          }
        ]
      };
      await onBalances(page, roster, figures);

      const rows = transferRows(page);
      page.is(rows.length, 1, 'transfer rows');
      const row = rows[0];
      /* Task 14 finds the transfer a row belongs to through these two, and neither
         is ever rendered as text. */
      page.is(row.getAttribute('data-from'), 'mem-1', 'data-from');
      page.is(row.getAttribute('data-to'), 'mem-2', 'data-to');
      /* Exactly two, so task 14 can append a third without unpicking either. */
      page.is(row.childNodes.length, 2, 'children of the transfer row');

      const button = row.childNodes[0];
      const detail = row.childNodes[1];
      page.is(button.tagName, 'BUTTON', 'the control');
      page.is(button.type, 'button', 'the control type');
      page.is(button.getAttribute('aria-expanded'), 'false', 'aria-expanded closed');
      page.is(button.getAttribute('aria-controls'), detail.id, 'aria-controls');
      page.is(detail.hidden, true, 'the region while closed');
      page.is(regionFor(page, button), detail, 'the region the button names');

      /* Byte for byte what task 12 rendered, payer first, the amount inserted
         exactly as received and inside its own figure. */
      page.is(lineOf(button).textContent, 'Sam (you) pays Ali 600.00', 'the row');
      page.same(figuresIn(button), ['600.00'], 'the figures on the row');
      const indicators = button.querySelectorAll('.balances-indicator');
      page.is(indicators.length, 1, 'the indicator');
      page.is(
        indicators[0].getAttribute('aria-hidden'),
        'true',
        'the indicator to a reader'
      );
      page.is(indicators[0].textContent, '+', 'the closed indicator');
      /* Shown, because at least one rendered row really opens. */
      page.is(page.el('balances-drill-hint').hidden, false, 'the drill-down hint');

      await page.dispatch(button, 'click');
      page.is(button.getAttribute('aria-expanded'), 'true', 'aria-expanded open');
      page.is(detail.hidden, false, 'the region while open');
      page.is(indicators[0].textContent, '-', 'the open indicator');

      /* Both ends, each under a label naming whose end it is, every row in the order
         its array arrived, nothing sorted, merged or deduplicated: (mem-1, mem-2) is
         in both lists and renders in both, which is the two-ended view and not a
         duplicate. The mixed shape says nothing about a shared expense, and closes
         with the one sentence that stops 300 and 300 reading as 600 owed twice. */
      page.same(
        detailLines(detail),
        [
          'What Sam (you) owes',
          'Sam (you) owes Ali 300.00',
          'Sam (you) owes Cass 300.00 of 500.00',
          'What Ali is owed',
          'Sam (you) owes Ali 300.00',
          'Cass owes Ali 300.00',
          'The same payment seen from each end. These are not two payments.'
        ],
        'the open payment'
      );
      /* Every figure in its own span, inserted exactly as received. */
      page.same(
        debtRowsIn(detail).map((item) => figuresIn(item.childNodes[0])),
        [['300.00'], ['300.00', '500.00'], ['300.00'], ['300.00']],
        'the figures inside the payment'
      );
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* The case the whole task exists for: Jo has never bought anything with Kit, and
       the row still has to explain itself. Ali is named because both lists name Ali,
       and no chain, arrow or "via" clause is drawn between the three. Sam is in the
       roster and in neither list, and is named nowhere inside the open payment. */
    name: 'a_payment_to_someone_you_never_shared_an_expense_with_says_why',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Kit' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [
          { member_id: 'mem-1', amount: '0.00', direction: 'settled' },
          { member_id: 'mem-2', amount: '400.00', direction: 'owes' },
          { member_id: 'mem-3', amount: '0.00', direction: 'settled' },
          { member_id: 'mem-4', amount: '400.00', direction: 'owed' }
        ],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-4',
            amount: '400.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '400.00', '400.00', true)],
            receiver_credits: [absorbed('mem-3', 'mem-4', '400.00', '400.00', true)]
          }
        ]
      };
      await onBalances(page, roster, figures);

      const button = transferRows(page)[0].childNodes[0];
      const detail = regionFor(page, button);
      await page.dispatch(button, 'click');
      page.same(
        detailLines(detail),
        [
          'Jo and Kit have not shared an expense. These are the debts on each side ' +
            'of this payment.',
          'What Jo owes',
          'Jo owes Ali 400.00',
          'What Kit is owed',
          'Ali owes Kit 400.00',
          'The same payment seen from each end. These are not two payments.'
        ],
        'the open payment'
      );
      /* No path is drawn. The open payment names only the members its two lists
         name, and Sam, who is in the roster and in neither list, is not among
         them. */
      page.is(detail.textContent.indexOf('Sam'), -1, 'a member neither list names');
      page.is(detail.textContent.indexOf('via'), -1, 'a via clause');
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* The simple case task 5's "direct debt first" rule guarantees. Two labelled
       lists holding the same single row would read as a bug, so this shows one list
       under one sentence, and no "seen from each end" line: there is only one end
       here to see it from. */
    name: 'a_payment_that_settles_one_debt_directly_shows_it_once',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [
          { member_id: 'mem-1', amount: '0.00', direction: 'settled' },
          { member_id: 'mem-2', amount: '50.00', direction: 'owes' },
          { member_id: 'mem-3', amount: '50.00', direction: 'owed' }
        ],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '50.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '50.00', '50.00', true)],
            receiver_credits: [absorbed('mem-2', 'mem-3', '50.00', '50.00', true)]
          }
        ]
      };
      await onBalances(page, roster, figures);

      const button = transferRows(page)[0].childNodes[0];
      const detail = regionFor(page, button);
      await page.dispatch(button, 'click');
      page.same(
        detailLines(detail),
        ['This payment settles what Jo owes Ali directly.', 'Jo owes Ali 50.00'],
        'the open payment'
      );
      page.is(debtRowsIn(detail).length, 1, 'debt rows in a direct payment');
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* Task 5's chain fixture: Bo owes Ali 10.00 and Ali owes Cass 4.00, which
       simplifies to two payments, and the debt Bo owes Ali is split across both of
       them. Open both and the same pair is on screen twice. What stops that reading
       as 10.00 owed twice is the whole total on each row. */
    name: 'a_debt_split_across_two_payments_shows_each_share_of_the_whole',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Bo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Cass' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [
          { member_id: 'mem-1', amount: '0.00', direction: 'settled' },
          { member_id: 'mem-2', amount: '10.00', direction: 'owes' },
          { member_id: 'mem-3', amount: '6.00', direction: 'owed' },
          { member_id: 'mem-4', amount: '4.00', direction: 'owed' }
        ],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '6.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '6.00', '10.00', false)],
            receiver_credits: [absorbed('mem-2', 'mem-3', '6.00', '10.00', false)]
          },
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-4',
            amount: '4.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '4.00', '10.00', false)],
            receiver_credits: [absorbed('mem-3', 'mem-4', '4.00', '4.00', true)]
          }
        ]
      };
      await onBalances(page, roster, figures);

      const rows = transferRows(page);
      page.is(rows.length, 2, 'transfer rows');
      const first = rows[0].childNodes[0];
      const second = rows[1].childNodes[0];
      await page.dispatch(first, 'click');
      await page.dispatch(second, 'click');

      page.same(
        detailLines(regionFor(page, first)),
        [
          'This payment settles what Bo owes Ali directly.',
          'Bo owes Ali 6.00 of 10.00'
        ],
        'the first payment'
      );
      page.same(
        detailLines(regionFor(page, second)),
        [
          'Bo and Cass have not shared an expense. These are the debts on each side ' +
            'of this payment.',
          'What Bo owes',
          'Bo owes Ali 4.00 of 10.00',
          'What Cass is owed',
          'Ali owes Cass 4.00',
          'The same payment seen from each end. These are not two payments.'
        ],
        'the second payment'
      );

      /* Every region id is this task's own sequence number, unique in the document
         and derived from no member id: the pair (mem-2, mem-3) has a debt row in
         both payments, and those two rows carry two different ids. */
      const ids = regionIds(page);
      page.is(ids.length, 5, 'regions in the document');
      page.same(unique(ids), ids, 'every region id is its own');
      page.ok(
        ids.every((id) => /^balances-detail-[0-9]+$/.test(id)),
        'every region id is balances-detail-N: ' + JSON.stringify(ids)
      );
      page.ok(
        ids.every((id) => id.indexOf('mem-') === -1),
        'no region id carries a member id: ' + JSON.stringify(ids)
      );
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* The "of" clause is dropped on one strict equality with true and on nothing
       else. false keeps it, and so does a value of the wrong type: the clause states
       two figures the server sent and claims nothing, while dropping it claims the
       payment clears the whole debt, which a garbled flag has not earned. */
    name: 'a_payment_that_covers_a_whole_debt_does_not_say_of_itself',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Kit' },
          { id: 'mem-5', display_name: 'Mo' },
          { id: 'mem-6', display_name: 'Ray' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '4.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '4.00',
            payer_debts: [
              absorbed('mem-2', 'mem-3', '1.00', '1.00', true),
              absorbed('mem-2', 'mem-4', '1.00', '2.00', false),
              /* The string 'true' and null: present, so the transfer still carries
                 usable provenance, and not true, so the clause stays. */
              absorbed('mem-2', 'mem-5', '1.00', '1.00', 'true'),
              absorbed('mem-2', 'mem-6', '1.00', '1.00', null)
            ],
            receiver_credits: [absorbed('mem-2', 'mem-3', '4.00', '4.00', true)]
          }
        ]
      };
      await onBalances(page, roster, figures);

      const button = transferRows(page)[0].childNodes[0];
      const detail = regionFor(page, button);
      await page.dispatch(button, 'click');
      page.same(
        detailLines(detail),
        [
          'What Jo owes',
          'Jo owes Ali 1.00',
          'Jo owes Kit 1.00 of 2.00',
          'Jo owes Mo 1.00 of 1.00',
          'Jo owes Ray 1.00 of 1.00',
          'What Ali is owed',
          'Jo owes Ali 4.00',
          'The same payment seen from each end. These are not two payments.'
        ],
        'the open payment'
      );
      /* A row that says "of" carries two figures; a row that covers the whole debt
         carries one. No amount string is compared to decide which. */
      page.same(
        debtRowsIn(detail).map((item) => figuresIn(item.childNodes[0]).length),
        [1, 2, 2, 2, 1],
        'figures per debt row'
      );
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* A payload with no usable provenance renders the row exactly as task 12 did: an
       inert span, with nothing on it that looks tappable. Four different ways of
       being unusable, beside one good row, and the good row is still a button, the
       net list and the currency line are still there and nothing threw. */
    name: 'a_transfer_row_without_provenance_is_not_tappable',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' }
        ]
      };
      const good = {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '9.00',
        payer_debts: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)],
        receiver_credits: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)]
      };
      /* No payer_debts at all; an empty receiver_credits; an amount that is not a
         string; and a row with no covers_whole_debt property. */
      const noList = {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '1.00',
        receiver_credits: [absorbed('mem-2', 'mem-3', '1.00', '1.00', true)]
      };
      const emptyList = {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '2.00',
        payer_debts: [absorbed('mem-2', 'mem-3', '2.00', '2.00', true)],
        receiver_credits: []
      };
      const numberAmount = {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '3.00',
        payer_debts: [
          {
            debtor_id: 'mem-2',
            creditor_id: 'mem-3',
            amount: 3,
            debt_total: '3.00',
            covers_whole_debt: true
          }
        ],
        receiver_credits: [absorbed('mem-2', 'mem-3', '3.00', '3.00', true)]
      };
      const noFlag = {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '4.00',
        payer_debts: [absorbed('mem-2', 'mem-3', '4.00', '4.00', true)],
        receiver_credits: [
          { debtor_id: 'mem-2', creditor_id: 'mem-3', amount: '4.00', debt_total: '4.00' }
        ]
      };
      const net = [
        { member_id: 'mem-1', amount: '0.00', direction: 'settled' },
        { member_id: 'mem-2', amount: '19.00', direction: 'owes' },
        { member_id: 'mem-3', amount: '19.00', direction: 'owed' }
      ];
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', ok(EMPTY_FEED));
      page.respond('GET', '/members', ok(roster));
      page.respondInOrder('GET', '/balances', [
        ok({
          currency: 'AUD',
          net: net,
          transfers: [noList, good, emptyList, numberAmount, noFlag]
        }),
        ok({ currency: 'AUD', net: net, transfers: [noList, emptyList] })
      ]);
      page.startAt('#/balances');
      await page.boot();

      const rows = transferRows(page);
      page.is(rows.length, 5, 'transfer rows');
      page.same(
        rows.map((row) => row.childNodes[0].tagName),
        ['SPAN', 'BUTTON', 'SPAN', 'SPAN', 'SPAN'],
        'what each row leads with'
      );
      rows.forEach((row, index) => {
        if (index === 1) {
          return;
        }
        page.is(row.childNodes.length, 1, 'children of inert row ' + index);
        page.is(row.childNodes[0].className, 'balances-line', 'inert row ' + index);
        page.is(row.className, 'balances-row', 'the class on inert row ' + index);
        page.is(
          row.childNodes[0].getAttribute('aria-expanded'),
          null,
          'aria-expanded on inert row ' + index
        );
        page.is(
          row.querySelectorAll('.balances-indicator').length,
          0,
          'the indicator on inert row ' + index
        );
      });
      /* The inert rows still say exactly what task 12 had them say. */
      page.is(rows[0].textContent, 'Jo pays Ali 1.00', 'the first inert row');
      /* One malformed row affects nothing else: the good row still opens, and the
         net list and the currency line are untouched. */
      page.is(page.el('balances-net').childNodes.length, 3, 'the net list');
      page.is(page.el('balances-currency').hidden, false, 'the currency line');
      page.is(page.el('balances-currency-code').textContent, 'AUD', 'the currency');
      page.is(
        page.el('balances-drill-hint').hidden,
        false,
        'the hint beside one good row'
      );
      await page.dispatch(rows[1].childNodes[0], 'click');
      page.is(
        regionFor(page, rows[1].childNodes[0]).hidden,
        false,
        'the good row still opens'
      );

      /* A list in which nothing can be opened hides the hint again. */
      await page.goTo('#/feed');
      await page.goTo('#/balances');
      page.same(
        transferRows(page).map((row) => row.childNodes[0].tagName),
        ['SPAN', 'SPAN'],
        'a list of inert rows'
      );
      page.is(
        page.el('balances-drill-hint').hidden,
        true,
        'the hint with nothing to open'
      );
      page.expectRequests(
        BALANCES_ENTRY.concat([
          'GET /api/expenses',
          'GET /api/members',
          'GET /api/members',
          'GET /api/balances'
        ])
      );
    }
  },

  {
    /* Collapsing somebody else's row to open yours is surprising, so more than one
       payment may be open at once, and more than one debt inside one payment. */
    name: 'a_second_payment_opens_without_closing_the_first',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Kit' },
          { id: 'mem-5', display_name: 'Mo' },
          { id: 'mem-6', display_name: 'Ray' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '5.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '5.00',
            payer_debts: [
              absorbed('mem-2', 'mem-3', '3.00', '3.00', true),
              absorbed('mem-2', 'mem-4', '2.00', '2.00', true)
            ],
            receiver_credits: [
              absorbed('mem-2', 'mem-3', '3.00', '3.00', true),
              absorbed('mem-4', 'mem-3', '2.00', '2.00', true)
            ]
          },
          {
            from_member_id: 'mem-5',
            to_member_id: 'mem-6',
            amount: '1.00',
            payer_debts: [absorbed('mem-5', 'mem-6', '1.00', '1.00', true)],
            receiver_credits: [absorbed('mem-5', 'mem-6', '1.00', '1.00', true)]
          }
        ]
      };
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/members', ok(roster));
      page.respond('GET', '/balances', ok(figures));
      page.respond('GET', '/debts/mem-2/mem-3', ok(oneEntryDebt('mem-2', 'mem-3')));
      page.respond('GET', '/debts/mem-2/mem-4', ok(oneEntryDebt('mem-2', 'mem-4')));
      page.startAt('#/balances');
      await page.boot();

      const rows = transferRows(page);
      const first = rows[0].childNodes[0];
      const second = rows[1].childNodes[0];
      await page.dispatch(first, 'click');
      const firstDetail = regionFor(page, first);
      const debts = debtRowsIn(firstDetail);
      await page.dispatch(debts[0].childNodes[0], 'click');
      await page.dispatch(debts[1].childNodes[0], 'click');
      await page.dispatch(second, 'click');

      page.is(first.getAttribute('aria-expanded'), 'true', 'the first payment');
      page.is(firstDetail.hidden, false, 'the first region');
      page.is(second.getAttribute('aria-expanded'), 'true', 'the second payment');
      page.is(regionFor(page, second).hidden, false, 'the second region');
      page.same(
        debts.slice(0, 2).map((item) => item.childNodes[0].getAttribute('aria-expanded')),
        ['true', 'true'],
        'two debts open inside one payment'
      );
      page.same(
        debts.slice(0, 2).map((item) => item.childNodes[1].hidden),
        [false, false],
        'both debt regions'
      );
      page.expectRequests(
        BALANCES_ENTRY.concat([
          'GET /api/debts/mem-2/mem-3',
          'GET /api/debts/mem-2/mem-4'
        ])
      );
    }
  },

  {
    /* The second read, and the whole point of it: what one pairwise debt is made of,
       in the words the entry's own kind and effect choose. Seven entries covering
       the four sentences, a settlement's fixed name, an empty description, and a
       kind and an effect nobody expected. The feed renders the same instant on the
       way past, so "one ledger, one date spelling" is asserted against the feed
       itself rather than against a second copy of feedDate written here. */
    name: 'opening_a_debt_lists_the_expenses_behind_it',
    async run(page) {
      const first = '2026-09-04T08:00:00.000000+00:00';
      const second = '2026-09-02T23:30:00.000000+00:00';
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '9.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '9.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)],
            receiver_credits: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)]
          }
        ]
      };
      const behind = {
        currency: 'AUD',
        debtor_id: 'mem-2',
        creditor_id: 'mem-3',
        amount: '9.00',
        direction: 'owes',
        entries: [
          entry('expense', 'adds', 'exp-1', 'Milk run', first, '4.00'),
          entry('expense', 'reduces', 'exp-2', 'Bus fare', first, '2.00'),
          entry('settlement', 'reduces', 'set-1', '', first, '5.00'),
          /* A description on a settlement, which the wire never sends: kind decides
             the name before the description is looked at. */
          entry('settlement', 'adds', 'set-2', 'ignored', second, '1.00'),
          entry('refund', 'wobbles', 'odd-1', 'Odd one', second, '3.00'),
          entry('expense', 'sideways', 'odd-2', 'Sideways', second, '7.00'),
          entry('expense', 'adds', 'exp-3', '   ', second, '9.00')
        ]
      };
      page.respond('GET', '/debts/mem-2/mem-3', ok(behind));
      await onBalances(page, roster, figures);
      const transfer = transferRows(page)[0].childNodes[0];
      await page.dispatch(transfer, 'click');
      const payment = regionFor(page, transfer);
      /* Nothing was asked for on entering the route or on opening the payment. */
      page.same(page.requests, BALANCES_ENTRY, 'requests before the debt opens');

      const item = debtRowsIn(payment)[0];
      const button = item.childNodes[0];
      const region = item.childNodes[1];
      page.is(button.tagName, 'BUTTON', 'the debt control');
      page.is(button.type, 'button', 'the debt control type');
      page.is(button.getAttribute('aria-expanded'), 'false', 'the debt closed');
      page.is(button.getAttribute('aria-controls'), region.id, 'the debt aria-controls');
      page.is(region.hidden, true, 'the debt region while closed');
      page.is(regionFor(page, button), region, 'the region the debt button names');

      /* A transfer region carries no live region and no aria-busy of its own: the
         request belongs to a debt row, and so does everything said about it. */
      page.is(payment.getAttribute('aria-busy'), null, 'aria-busy on a payment');
      page.same(
        payment.childNodes.map((child) => child.getAttribute('role')),
        [null, null],
        'roles on a payment region'
      );

      await page.dispatch(button, 'click');
      page.is(button.getAttribute('aria-expanded'), 'true', 'the debt open');
      page.is(region.hidden, false, 'the debt region while open');
      page.is(region.getAttribute('aria-busy'), null, 'aria-busy once it settled');

      /* Exactly one live region per debt, holding one sentence and nothing else,
         with the entry list as its sibling rather than its child. */
      page.is(region.childNodes.length, 2, 'children of a debt region');
      const status = statusIn(region);
      const list = entryListIn(region);
      page.is(status.getAttribute('role'), 'status', 'the live region');
      page.is(status.textContent, '', 'the live region once the entries arrived');
      page.is(list.className, 'balances-entries', 'the entry list');
      page.is(list.hidden, false, 'the entry list once it has entries');

      const parts = entriesIn(region).map(entryParts);
      page.is(parts.length, 7, 'entries');
      page.same(
        parts.map((part) => part.description),
        [
          'Milk run',
          'Bus fare',
          'A settlement',
          'A settlement',
          'Odd one',
          'Sideways',
          'No description'
        ],
        'descriptions'
      );
      page.same(
        parts.map((part) => part.amount),
        ['4.00', '2.00', '5.00', '1.00', '3.00', '7.00', '9.00'],
        'amounts'
      );
      /* The four sentences, and no sentence at all for a kind or an effect nobody
         expected: inventing a direction for one would be worse than saying nothing. */
      page.same(
        parts.map((part) => part.effect),
        [
          'Adds to this debt: Ali paid, and Jo shared',
          'Takes off this debt: Jo paid, and Ali shared',
          'Takes off this debt: Jo paid Ali',
          'Adds to this debt: Ali paid Jo',
          null,
          null,
          'Adds to this debt: Ali paid, and Jo shared'
        ],
        'effect lines'
      );
      /* In the order the server sent them and in no other. */
      page.same(
        parts.map((part) => part.datetime),
        [first, first, first, second, second, second, second],
        'the instants, unchanged and in the order they arrived'
      );
      page.same(
        parts.map((part) => part.dateTag),
        ['TIME', 'TIME', 'TIME', 'TIME', 'TIME', 'TIME', 'TIME'],
        'the date elements'
      );
      page.same(
        parts.map((part) => part.dateText),
        [first, first, first, second, second, second, second].map(spelledDate),
        'the dates, absolute and local'
      );
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-3']));
    }
  },

  {
    /* A live region whose text changed while it was hidden announces nothing in
       several screen readers, so the reveal comes first, then aria-busy, then the
       sentence, and only then the request. onRequest sees the page at the one moment
       that ordering is observable. */
    name: 'the_waiting_line_is_on_screen_before_the_request_goes_out',
    async run(page) {
      const { region, button, transfer } = await oneOpenPayment(page, ok(oneEntryDebt('mem-2', 'mem-3')));
      let seen = null;
      page.onRequest('GET', '/debts/mem-2/mem-3', () => {
        seen = {
          hidden: region.hidden,
          busy: region.getAttribute('aria-busy'),
          expanded: button.getAttribute('aria-expanded'),
          disabled: button.disabled,
          status: statusIn(region).textContent
        };
      });
      await page.dispatch(button, 'click');
      page.ok(seen !== null, 'the request went out');
      page.same(
        seen,
        {
          hidden: false,
          busy: 'true',
          expanded: 'true',
          disabled: false,
          status: 'Looking up the expenses behind this.'
        },
        'the page at the moment the request went out'
      );
      /* Settled, so the busy flag is gone and the sentence has been replaced by the
         entries it was waiting for. */
      page.is(region.getAttribute('aria-busy'), null, 'aria-busy after it settled');
      page.is(statusIn(region).textContent, '', 'the waiting line afterwards');
      page.is(entriesIn(region).length, 1, 'the entries');
      page.is(transfer.getAttribute('aria-expanded'), 'true', 'the payment above');
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-3']));
    }
  },

  {
    /* The answer is in that row's own DOM, so closing and opening it again asks
       nothing further. Not a cache: it lives in the row and dies with it. */
    name: 'the_expenses_behind_a_debt_are_asked_for_once',
    async run(page) {
      const { region, button } = await oneOpenPayment(page, ok(oneEntryDebt('mem-2', 'mem-3')));
      await page.dispatch(button, 'click');
      await page.dispatch(button, 'click');
      await page.dispatch(button, 'click');
      page.is(button.getAttribute('aria-expanded'), 'true', 'open again');
      page.is(region.hidden, false, 'the region, open again');
      page.is(entriesIn(region).length, 1, 'the entries, still there');
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-3']));
    }
  },

  {
    /* A failure keeps nothing, so asking again is asking afresh. The sentence is
       this screen's own for every kind: the one this route composes for its own 400
       names a member id, and no member id is ever shown here. */
    name: 'a_debt_whose_expenses_do_not_arrive_says_so_and_can_be_asked_again',
    async run(page) {
      const refusal = failure(400, CODES.malformedRequest, MALFORMED_DEBT);
      const { region, button, transfer, payment } = await oneOpenPayment(page, [
        refusal,
        ok(oneEntryDebt('mem-2', 'mem-3'))
      ]);
      await page.dispatch(button, 'click');
      page.is(
        statusIn(region).textContent,
        'Those expenses could not be listed just now.',
        'the failure sentence'
      );
      page.is(region.getAttribute('aria-busy'), null, 'aria-busy after a failure');
      page.is(entryListIn(region).hidden, true, 'the entry list after a failure');
      page.is(entriesIn(region).length, 0, 'entries after a failure');
      /* One row's failure, not the screen's: the payment above stays open with its
         debt rows listed, the net list is untouched and the screen's own message
         stays hidden. Nothing the server said is on screen. */
      page.is(transfer.getAttribute('aria-expanded'), 'true', 'the payment above');
      page.is(payment.hidden, false, 'the payment region');
      page.is(debtRowsIn(payment).length, 1, 'the debt rows');
      page.is(page.el('balances-error').hidden, true, '#balances-error');
      page.is(page.el('balances-net').childNodes.length, 1, 'the net list');
      const shown = page.el('screen-balances').textContent;
      page.is(shown.indexOf(MALFORMED_DEBT), -1, "the server's own sentence");
      page.is(shown.indexOf('mem-'), -1, 'a member id as visible text');

      await page.dispatch(button, 'click');
      await page.dispatch(button, 'click');
      page.is(entriesIn(region).length, 1, 'the entries, asked for again');
      page.is(statusIn(region).textContent, '', 'the failure sentence afterwards');
      page.expectRequests(
        BALANCES_ENTRY.concat([
          'GET /api/debts/mem-2/mem-3',
          'GET /api/debts/mem-2/mem-3'
        ])
      );
    }
  },

  {
    /* An empty list is a valid answer and not a failure: the ledger can move between
       the balances read and this request. It is an answer, so the row keeps it and
       asks nothing further. */
    name: 'a_debt_with_nothing_behind_it_says_so_rather_than_failing',
    async run(page) {
      const empty = {
        currency: 'AUD',
        debtor_id: 'mem-2',
        creditor_id: 'mem-3',
        amount: '0.00',
        direction: 'settled',
        entries: []
      };
      const { region, button } = await oneOpenPayment(page, ok(empty));
      await page.dispatch(button, 'click');
      page.is(
        statusIn(region).textContent,
        'Nothing is recorded behind this debt.',
        'the nothing-recorded sentence'
      );
      /* No list at all, rather than an empty one. */
      page.is(entryListIn(region).hidden, true, 'the entry list');
      page.is(entriesIn(region).length, 0, 'entries');
      page.is(page.el('balances-error').hidden, true, '#balances-error');
      await page.dispatch(button, 'click');
      await page.dispatch(button, 'click');
      page.is(
        statusIn(region).textContent,
        'Nothing is recorded behind this debt.',
        'the sentence on a second look'
      );
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-3']));
    }
  },

  {
    /* "Nothing is recorded behind this debt" is a claim about the ledger, and a
       payload this screen could not read is no evidence for it. Five ways of being
       unreadable, one per debt row, all of them 200s. */
    name: 'a_debt_that_answers_with_the_wrong_shape_is_a_failure_not_an_empty_debt',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Kit' },
          { id: 'mem-5', display_name: 'Mo' },
          { id: 'mem-6', display_name: 'Ray' },
          { id: 'mem-7', display_name: 'Wu' }
        ]
      };
      const head = {
        currency: 'AUD',
        debtor_id: 'mem-2',
        creditor_id: 'mem-3',
        amount: '1.00',
        direction: 'owes'
      };
      const good = entry('expense', 'adds', 'exp-1', 'Milk run', WHEN, '1.00');
      const missing = { kind: 'expense', effect: 'adds', id: 'exp-1',
        description: 'Milk run', created_at: WHEN };
      const numbered = { kind: 'expense', effect: 'adds', id: 'exp-1',
        description: 'Milk run', created_at: 4, amount: '1.00' };
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', ok(EMPTY_FEED));
      page.respond('GET', '/members', ok(roster));
      page.respond('GET', '/balances', ok({
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '5.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '5.00',
            payer_debts: [
              absorbed('mem-2', 'mem-3', '1.00', '1.00', true),
              absorbed('mem-2', 'mem-4', '1.00', '1.00', true),
              absorbed('mem-2', 'mem-5', '1.00', '1.00', true),
              absorbed('mem-2', 'mem-6', '1.00', '1.00', true),
              absorbed('mem-2', 'mem-7', '1.00', '1.00', true)
            ],
            receiver_credits: [absorbed('mem-2', 'mem-3', '5.00', '5.00', true)]
          }
        ]
      }));
      /* No entries key at all; entries that are not an array; an element that is not
         an object; an element with no amount; an element whose created_at is a
         number rather than the string the wire sends. */
      page.respond('GET', '/debts/mem-2/mem-3', ok(head));
      page.respond('GET', '/debts/mem-2/mem-4', ok({ ...head, entries: {} }));
      page.respond('GET', '/debts/mem-2/mem-5', ok({ ...head, entries: ['nope'] }));
      page.respond('GET', '/debts/mem-2/mem-6', ok({ ...head, entries: [good, missing] }));
      page.respond('GET', '/debts/mem-2/mem-7', ok({ ...head, entries: [numbered] }));
      page.startAt('#/balances');
      await page.boot();

      const transfer = transferRows(page)[0].childNodes[0];
      await page.dispatch(transfer, 'click');
      const rows = debtRowsIn(regionFor(page, transfer)).slice(0, 5);
      for (const item of rows) {
        await page.dispatch(item.childNodes[0], 'click');
      }
      page.same(
        rows.map((item) => statusIn(item.childNodes[1]).textContent),
        [
          'Those expenses could not be listed just now.',
          'Those expenses could not be listed just now.',
          'Those expenses could not be listed just now.',
          'Those expenses could not be listed just now.',
          'Those expenses could not be listed just now.'
        ],
        'every unreadable answer is a failure'
      );
      page.same(
        rows.map((item) => entriesIn(item.childNodes[1]).length),
        [0, 0, 0, 0, 0],
        'nothing was rendered from an unreadable answer'
      );
      page.is(page.el('balances-error').hidden, true, '#balances-error');
      page.expectRequests(
        BALANCES_ENTRY.concat([
          'GET /api/debts/mem-2/mem-3',
          'GET /api/debts/mem-2/mem-4',
          'GET /api/debts/mem-2/mem-5',
          'GET /api/debts/mem-2/mem-6',
          'GET /api/debts/mem-2/mem-7'
        ])
      );
    }
  },

  {
    /* A member id means nothing to a flatmate and is never shown, so a row whose
       member the roster does not know still shows the money under one fixed name.
       Hiding a debt because a name is missing is the worse failure, and the refusal
       this route composes for that id names it, which is why the row prints its own
       sentence and never the server's. */
    name: 'a_member_missing_from_the_roster_still_shows_the_debt',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' }
        ]
      };
      page.respond('GET', '/session', ok(A_MEMBER));
      page.respond('GET', '/expenses', ok(EMPTY_FEED));
      page.respond('GET', '/members', ok(roster));
      page.respond('GET', '/balances', ok({
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '5.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-9',
            amount: '5.00',
            payer_debts: [absorbed('mem-2', 'mem-9', '5.00', '8.00', false)],
            receiver_credits: [absorbed('mem-2', 'mem-9', '5.00', '8.00', false)]
          }
        ]
      }));
      page.respond(
        'GET',
        '/debts/mem-2/mem-9',
        failure(400, CODES.malformedRequest, MALFORMED_DEBT)
      );
      page.startAt('#/balances');
      await page.boot();

      const transfer = transferRows(page)[0].childNodes[0];
      page.is(lineOf(transfer).textContent, 'Jo pays Unknown member 5.00', 'the row');
      await page.dispatch(transfer, 'click');
      const payment = regionFor(page, transfer);
      page.same(
        detailLines(payment),
        [
          'This payment settles what Jo owes Unknown member directly.',
          'Jo owes Unknown member 5.00 of 8.00'
        ],
        'the open payment'
      );
      const item = debtRowsIn(payment)[0];
      await page.dispatch(item.childNodes[0], 'click');
      page.is(
        statusIn(item.childNodes[1]).textContent,
        'Those expenses could not be listed just now.',
        'the failure sentence'
      );
      /* At every level, in every state, the failure state included. */
      const shown = page.el('screen-balances').textContent;
      page.is(shown.indexOf('mem-'), -1, 'a member id as visible text');
      page.is(shown.indexOf(MALFORMED_DEBT), -1, "the server's own sentence");
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-9']));
    }
  },

  {
    /* The same answer the feed and the add retries give behind a curtain, through
       the same shared helper. Signing out leaves the rows in the document, so both
       controls are still there to be pressed and both do nothing at all. */
    name: 'a_drill_down_behind_a_curtain_asks_for_nothing',
    async run(page) {
      const { region, button, transfer, payment } = await oneOpenPayment(page, ok(oneEntryDebt('mem-2', 'mem-3')), { keepClosed: true });
      page.respond('DELETE', '/session', noContent());
      await page.dispatch(page.el('sign-out'), 'click');
      gateIsUp(page, 'after signing out');

      await page.dispatch(transfer, 'click');
      await page.dispatch(button, 'click');
      page.is(transfer.getAttribute('aria-expanded'), 'false', 'the payment');
      page.is(payment.hidden, true, 'the payment region');
      page.is(button.getAttribute('aria-expanded'), 'false', 'the debt');
      page.is(region.hidden, true, 'the debt region');
      page.is(region.getAttribute('aria-busy'), null, 'aria-busy');
      page.is(statusIn(region).textContent, '', 'the live region');
      page.expectRequests(
        BALANCES_ENTRY.concat([{ method: 'DELETE', path: '/session', body: NO_BODY }])
      );
    }
  },

  {
    /* A 401 is task 9a's gate, reached through announce() exactly as every other 401
       is, and this screen adds nothing to it: no second sentence anywhere outside
       the row that asked. */
    name: 'a_401_on_a_drill_down_is_the_gate_and_not_this_screens_message',
    async run(page) {
      const { region, button } = await oneOpenPayment(page, sessionDied(EXPIRED));
      await page.dispatch(button, 'click');
      gateIsUp(page, 'after a 401 on a drill-down');
      page.is(page.el('gate-error').hidden, false, '#gate-error hidden');
      page.is(page.el('gate-error').textContent, EXPIRED, '#gate-error text');
      page.is(page.el('balances-error').hidden, true, '#balances-error');
      /* Written into a row nobody can see, which is harmless and keeps one path. */
      page.is(
        statusIn(region).textContent,
        'Those expenses could not be listed just now.',
        'the row that asked'
      );
      page.expectRequests(BALANCES_ENTRY.concat(['GET /api/debts/mem-2/mem-3']));
    }
  },

  {
    /* Entering the route costs the same two reads however large the plan is, and
       opening a payment costs nothing at all: no hash, no history entry, no fourth
       route, and no other row touched. */
    name: 'opening_a_payment_changes_no_route_and_no_history',
    async run(page) {
      const roster = {
        members: [
          { id: 'mem-1', display_name: 'Sam' },
          { id: 'mem-2', display_name: 'Jo' },
          { id: 'mem-3', display_name: 'Ali' },
          { id: 'mem-4', display_name: 'Kit' },
          { id: 'mem-5', display_name: 'Mo' }
        ]
      };
      const figures = {
        currency: 'AUD',
        net: [{ member_id: 'mem-2', amount: '3.00', direction: 'owes' }],
        transfers: [
          {
            from_member_id: 'mem-2',
            to_member_id: 'mem-3',
            amount: '2.00',
            payer_debts: [absorbed('mem-2', 'mem-3', '2.00', '2.00', true)],
            receiver_credits: [absorbed('mem-2', 'mem-3', '2.00', '2.00', true)]
          },
          {
            from_member_id: 'mem-4',
            to_member_id: 'mem-5',
            amount: '1.00',
            payer_debts: [absorbed('mem-4', 'mem-5', '1.00', '1.00', true)],
            receiver_credits: [absorbed('mem-4', 'mem-5', '1.00', '1.00', true)]
          }
        ]
      };
      await onBalances(page, roster, figures);
      /* Two reads on entry and no drill-down request, whatever the plan holds. */
      page.same(page.requests, BALANCES_ENTRY, 'requests on entering the route');

      const rows = transferRows(page);
      const other = rows[1].childNodes[0];
      const otherRegion = regionFor(page, other);
      const otherLine = lineOf(other).textContent;
      await page.dispatch(rows[0].childNodes[0], 'click');

      page.is(page.hash, '#/balances', 'the hash');
      page.same(page.pushStates, [], 'history entries pushed');
      page.same(page.replaceStates, [], 'history entries replaced');
      page.is(page.focused, null, 'focus');
      /* The other row is neither re-rendered nor closed. */
      page.is(other.getAttribute('aria-expanded'), 'false', 'the other payment');
      page.is(otherRegion.hidden, true, 'the other region');
      page.is(lineOf(other).textContent, otherLine, 'the other row');
      page.is(regionFor(page, other), otherRegion, 'the other region, same node');
      page.expectRequests(BALANCES_ENTRY);
    }
  },

  {
    /* Nothing survives a navigation. The whole list is rebuilt closed, and an answer
       that arrives after the rebuild is written into the row that asked for it,
       which is no longer in the document, and never into the new list. The answer is
       held open here until the navigation has happened, which is the only way that
       ordering is observable. */
    name: 'leaving_the_balances_screen_and_returning_closes_every_drill_down',
    async run(page) {
      let release = null;
      const held = {
        status: 200,
        ok: true,
        json: () =>
          new Promise((resolve) => {
            release = () => resolve(oneEntryDebt('mem-2', 'mem-3'));
          })
      };
      const { region, button, transfer } = await oneOpenPayment(page, held);
      await page.dispatch(button, 'click');
      page.ok(release !== null, 'the request went out and is waiting');
      page.is(
        statusIn(region).textContent,
        'Looking up the expenses behind this.',
        'the waiting line'
      );

      await page.goTo('#/feed');
      await page.goTo('#/balances');
      const rebuilt = transferRows(page);
      page.is(rebuilt.length, 1, 'transfer rows after returning');
      page.ok(rebuilt[0] !== transfer, 'the row was rebuilt rather than reused');
      const freshTransfer = rebuilt[0].childNodes[0];
      page.is(freshTransfer.getAttribute('aria-expanded'), 'false', 'the payment');
      page.is(regionFor(page, freshTransfer).hidden, true, 'the payment region');

      release();
      await page.settle();
      /* The late answer went to the row that asked, which is detached, and nowhere
         near the list that replaced it. */
      page.is(entriesIn(region).length, 1, 'the detached row that asked');
      await page.dispatch(freshTransfer, 'click');
      const fresh = debtRowsIn(regionFor(page, freshTransfer))[0];
      page.is(fresh.childNodes[0].getAttribute('aria-expanded'), 'false', 'the debt');
      page.is(fresh.childNodes[1].hidden, true, 'the debt region');
      page.is(entriesIn(fresh.childNodes[1]).length, 0, 'entries in the new list');
      page.is(statusIn(fresh.childNodes[1]).textContent, '', 'the new live region');
      page.expectRequests(
        BALANCES_ENTRY.concat([
          'GET /api/debts/mem-2/mem-3',
          'GET /api/expenses',
          'GET /api/members',
          'GET /api/members',
          'GET /api/balances'
        ])
      );
    }
  }
];

/* --- Task 43: a second person at the same phone ---------------------------------

   A session view for somebody who is not Sam, so a scenario can put two people at one
   phone and assert what each of them sees. Every other session fixture in this file
   is acc-1/mem-1, or that same account with member: null, which is why the shared
   phone case was unassertable and the defect hiding in it went unseen.

   These sit below SCENARIOS rather than beside A_MEMBER because this task appends to
   this file and edits none of it, while task 38 appends to the same array. Module
   evaluation reaches them long before main() runs, which is all a scenario body
   needs. */
const A_SECOND_MEMBER = {
  account: { id: 'acc-2', email: 'ali@example.com', display_name: 'Ali' },
  group: { id: 'grp-1', name: 'Flat', currency: 'AUD' },
  member: { id: 'mem-2', display_name: 'Ali' }
};
/* Spelled out rather than rebuilt from what the scenario typed, for the reason
   SIGN_IN_BODY is: a body asserted against a copy of the code that built it asserts
   nothing. */
const SECOND_SIGN_IN_BODY = '{"email":"ali@example.com","password":"opensesame"}';


/* --- Task 13: the transfer drill-down -------------------------------------------

   Below SCENARIOS for the reason task 43's block above is: this task appends to this
   file and edits none of it, and module evaluation reaches these long before main()
   runs, which is all a scenario body needs. What is shared here is the reaching, not
   the data: every fixture stays local to its own scenario, following task 38's note
   that one appended block conflicts with less on a file other branches are editing. */

/* One absorbed pairwise debt, in the five keys _absorbed_view sends. */
function absorbed(debtorId, creditorId, amount, total, covers) {
  return {
    debtor_id: debtorId,
    creditor_id: creditorId,
    amount: amount,
    debt_total: total,
    covers_whole_debt: covers
  };
}

/* The six top-level keys _read_debt sends, with one expense behind the pair. */
function oneEntryDebt(debtorId, creditorId) {
  return {
    currency: 'AUD',
    debtor_id: debtorId,
    creditor_id: creditorId,
    amount: '3.00',
    direction: 'owes',
    entries: [
      {
        kind: 'expense',
        effect: 'adds',
        id: 'exp-1',
        description: 'Milk run',
        created_at: '2026-09-04T08:00:00.000000+00:00',
        amount: '3.00'
      }
    ]
  };
}

/* Boots straight onto the balances route, so the feed never reads and the recorded
   request list is about this screen alone. */
async function onBalances(page, roster, figures) {
  page.respond('GET', '/session', ok(A_MEMBER));
  page.respond('GET', '/expenses', ok(EMPTY_FEED));
  page.respond('GET', '/members', ok(roster));
  page.respond('GET', '/balances', ok(figures));
  page.startAt('#/balances');
  await page.boot();
}

/* Entering the route costs exactly these three and no drill-down request, however
   large the plan is. */
const BALANCES_ENTRY = ['GET /api/session', 'GET /api/members', 'GET /api/balances'];

function transferRows(page) {
  return page.el('balances-transfers').childNodes;
}

/* page.el knows only the ids parsed out of app/index.html and throws for anything
   else, so a region app.js built at run time is reached through the button that
   names it in aria-controls. */
function regionFor(page, button) {
  const found = page.query('#' + button.getAttribute('aria-controls'));
  return found.length === 1 ? found[0] : null;
}

/* The sentence-carrying child of a disclosure button, which is its first child; the
   indicator is its second. */
function lineOf(button) {
  return button.childNodes[0];
}

function figuresIn(node) {
  return node.querySelectorAll('.balances-figure').map((figure) => figure.textContent);
}

function debtRowsIn(detail) {
  return detail.querySelectorAll('.balances-debt');
}

/* What an open payment reads as, top to bottom: every sentence and label it holds,
   and the line on every debt row inside it, in document order. */
function detailLines(detail) {
  const lines = [];
  detail.childNodes.forEach((child) => {
    if (child.tagName === 'UL') {
      child.childNodes.forEach((item) => {
        lines.push(lineOf(item.childNodes[0]).textContent);
      });
    } else {
      lines.push(child.textContent);
    }
  });
  return lines;
}

/* Every detail region in the document, at both levels. */
function regionIds(page) {
  return page
    .query('.balances-transfer-detail')
    .concat(page.query('.balances-debt-detail'))
    .map((region) => region.id);
}

/* One entry behind a pairwise debt, in the six keys _debt_entry_view sends. */
function entry(kind, effect, id, description, when, amount) {
  return {
    kind: kind,
    effect: effect,
    id: id,
    description: description,
    created_at: when,
    amount: amount
  };
}

const WHEN = '2026-09-04T08:00:00.000000+00:00';

/* feedDate's spelling of one instant, recomputed here. Be clear about how much that
   is worth: this is a second copy of the rule feedDate applies, not an independent
   oracle, so a mutation both copies would make in step is not caught by it. What it
   does catch is the whole of what a date can get wrong on this screen: the wrong
   field read, an instant printed in UTC rather than in the reader's own timezone, a
   relative label, or a second format. A hard-coded string could not, because the
   day a given instant falls on depends on the machine running the suite.

   Reading the feed's own spelling of the same instant would be the independent
   check, and it is not available: feedRender calls document.createDocumentFragment,
   which this stub does not fake, so no scenario in this repo has ever rendered a
   feed row. Issue #14's task file forbids widening the stub for anything but the two
   properties it names, so that stays for whoever covers the feed. */
const SPELLED_MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
];

function spelledDate(when) {
  const at = new Date(when);
  return at.getDate() + ' ' + SPELLED_MONTHS[at.getMonth()] + ' ' + at.getFullYear();
}

/* The sentence _read_debt composes for its own 400, which names a member id and is
   therefore the one this screen may never render. Spelled out here rather than
   imported, and asserted absent from the screen character for character. */
const MALFORMED_DEBT =
  "a debt path names a member id that is not a member of this group: 'mem-9'";

/* The commonest fixture: one payment settling one debt directly, opened, with the
   one debt row inside it left closed for the scenario to open. `answer` is the
   response the drill-down request gets, or a list consumed in order. */
async function oneOpenPayment(page, answer, options) {
  const roster = {
    members: [
      { id: 'mem-1', display_name: 'Sam' },
      { id: 'mem-2', display_name: 'Jo' },
      { id: 'mem-3', display_name: 'Ali' }
    ]
  };
  const figures = {
    currency: 'AUD',
    net: [{ member_id: 'mem-2', amount: '9.00', direction: 'owes' }],
    transfers: [
      {
        from_member_id: 'mem-2',
        to_member_id: 'mem-3',
        amount: '9.00',
        payer_debts: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)],
        receiver_credits: [absorbed('mem-2', 'mem-3', '9.00', '9.00', true)]
      }
    ]
  };
  page.respond('GET', '/session', ok(A_MEMBER));
  page.respond('GET', '/expenses', ok(EMPTY_FEED));
  page.respond('GET', '/members', ok(roster));
  page.respond('GET', '/balances', ok(figures));
  if (Array.isArray(answer)) {
    page.respondInOrder('GET', '/debts/mem-2/mem-3', answer);
  } else {
    page.respond('GET', '/debts/mem-2/mem-3', answer);
  }
  page.startAt('#/balances');
  await page.boot();

  const transfer = transferRows(page)[0].childNodes[0];
  if (!(options && options.keepClosed)) {
    await page.dispatch(transfer, 'click');
  }
  const payment = regionFor(page, transfer);
  const item = debtRowsIn(payment)[0];
  return { transfer, payment, item, button: item.childNodes[0], region: item.childNodes[1] };
}

function statusIn(region) {
  return region.childNodes[0];
}

function entryListIn(region) {
  return region.childNodes[1];
}

function entriesIn(region) {
  return region.querySelectorAll('.balances-entry');
}

/* One entry, split into the three parts criterion 36 names: a first line holding
   the description and the amount, an effect sentence that is absent when neither
   the kind nor the effect was recognised, and the date. */
function entryParts(item) {
  const first = item.childNodes[0];
  const last = item.childNodes[item.childNodes.length - 1];
  return {
    description: first.childNodes[0].textContent,
    amount: first.childNodes[1].textContent,
    effect: item.childNodes.length === 3 ? item.childNodes[1].textContent : null,
    dateTag: last.tagName,
    dateText: last.textContent,
    datetime: last.getAttribute('datetime')
  };
}

function unique(values) {
  return values.filter((value, at) => values.indexOf(value) === at);
}

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

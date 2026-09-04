# Task 8: Mobile web shell

**Depends on:** 1 (complete)
**Consumed by:** 10 (expense entry screen), 11 (expense feed), 12 (balances screen)

Sharpened from `plans/backlog.md` task 8. The backlog entry stays as written; this file
is the implementable version.

## Goal

The repo gains an `app/` directory of plain static files that a person can open on a
phone, install to the home screen, and navigate between three placeholder screens: feed,
add and balances. It has no build step, no new dependency, and no knowledge of the domain
layer. Tasks 10, 11 and 12 fill a screen by replacing one render function, not by
restructuring the shell.

## The build-step decision

**Decided here: plain HTML, CSS and JavaScript, no build step, no npm, no bundler, no
framework, no new Python package.** The engineer implements this decision; they do not
re-open it.

The reasoning, so a later task can argue with it on the record:

* Every module in this repo is standard library Python with zero runtime dependencies,
  and CLAUDE.md makes dependencies a deliberate, declared decision. There is even a hook
  (`.claude/hooks/guard-deps.hs.sh`) that blocks `uv add` and `pip install`. Introducing
  npm means a second package manager, a second lockfile, a `node_modules`, and a build
  artefact that has to be produced before anything can be served. That is a large,
  permanent cost.
* What it buys is nothing this task needs. This is a placeholder shell. The screens have
  no data, no forms and no state. Tasks 10 to 16 add the real content, and each of them
  can make its own case for tooling at the point where it would actually pay.
* A directory of plain files is the easiest thing for a later task to serve. Task 10
  needs a back end to hand these files to a browser; a static directory mounts behind any
  Python web framework with one line and no build step in the deploy path. A bundler
  would put a compile step between "clone the repo" and "see the app".
* Browsers that can install a PWA run modern JavaScript natively. There is nothing here
  to transpile and, at this size, nothing to bundle.

**If implementation seems to need npm, a bundler, a JS framework, a CSS framework, an
icon font, a JS test runner, or any Python package: stop and raise it with the user
before writing code.** That approval is not the engineer's to give inside this task, and
adding it silently puts the lockfile, the venv and the declared project out of step.

## How it runs

The run command is:

    uv run python scripts/serve.py

It serves `app/` on `http://localhost:8000`.

`scripts/serve.py` is a ~30 line standard library wrapper around
`http.server.SimpleHTTPRequestHandler`. It exists for one reason: Python's `mimetypes`
consults the Windows registry, where `.js` is commonly mapped to `text/plain`. Browsers
enforce a JavaScript MIME type on service worker scripts strictly, so a bare
`python -m http.server` can leave the service worker unregistered and the app
uninstallable on exactly the machine this project is developed on. The wrapper pins the
content types instead of guessing them.

`uv run python -m http.server -d app 8000` still serves the same directory and is fine
for layout work. It is not the documented command, because it cannot be relied on to
register the service worker.

The app must be reached at `http://localhost:8000` or `http://127.0.0.1:8000`. Those are
secure contexts; a LAN address such as `http://192.168.1.10:8000` is not, and service
workers and installability will not work there. Pick one of the two hostnames and stay on
it, because an installed app is bound to its origin.

## Routing

**Decided here: hash-based routing, one document, three routes.** `#/feed`, `#/add`,
`#/balances`.

* There is no server-side routing in this repo and will not be until task 10. With the
  History API, refreshing or deep-linking `/balances` asks the static server for a file
  that does not exist and gets a 404. That is the exact failure already hit once in this
  repo. A fragment never reaches the server, so refresh and deep-link work against any
  static file server, including the one in the standard library.
* Three separate HTML pages would also survive a static server, but every navigation
  becomes a full document load: the header and nav re-parse, the view flashes, and the
  markup is triplicated while the screens are still placeholders. The product's headline
  risk is that entry feels slow, so a full reload between tabs is the wrong default.
* Navigation is plain `<a href="#/add">` anchors plus a `hashchange` listener. No click
  handlers. Back, forward, reload, deep-link, long-press-to-copy and keyboard navigation
  then all work without any code written for them.
* Accepted trade-off: hash URLs are uglier, and the fragment is invisible to the server,
  so no route can ever be server-rendered without switching. If a later task adds a
  catch-all back end route, the switch to the History API is contained inside the router
  function in `app/app.js`.

## File layout

Everything the browser loads lives under `app/`, referenced by relative URLs, so the
directory can be mounted at the site root now and behind a prefix later without editing
every file.

| Path | What it is |
|---|---|
| `app/index.html` | The one document. Header, three screen sections, bottom nav. |
| `app/styles.css` | All styling. One file. |
| `app/app.js` | Router, title and focus handling, service worker registration. |
| `app/sw.js` | Service worker. Must sit at the `app/` root so its scope is `/`. |
| `app/manifest.json` | Web app manifest. |
| `app/icons/icon-192.png` | Manifest icon, `purpose: "any"`. |
| `app/icons/icon-512.png` | Manifest icon, `purpose: "any"`. |
| `app/icons/icon-maskable-512.png` | Manifest icon, `purpose: "maskable"`. |
| `app/icons/apple-touch-icon-180.png` | iOS home screen icon, linked from the HTML. |
| `scripts/serve.py` | Dev static server, standard library only. |
| `scripts/make_icons.py` | Deterministic PNG generator for the four icons. |
| `tests/test_web_shell.py` | Structural assertions over `app/`. |
| `tests/test_dev_server.py` | Serves `app/` on a loopback port and asserts responses. |

The extension is `.json`, not `.webmanifest`, deliberately: Python's `mimetypes` has no
mapping for `.webmanifest`, so a stdlib static server hands it back as
`application/octet-stream`. `.json` maps to `application/json`, which browsers accept for
a manifest. `scripts/serve.py` maps both anyway; the file name is the belt to that
braces, so the directory stays servable by anything.

## Acceptance criteria

**Files and layout**

- Every file in the table above exists at exactly that path, and no other file is added
  under `app/` or `scripts/`.
- No `package.json`, no `node_modules`, no lockfile other than the existing `uv.lock`, no
  bundler or transpiler config, and no change to `pyproject.toml`.
- No file under `app/` is a Python file, and nothing under `app/` is imported by the
  `splitwise_lite` package.
- Nothing under `app/` references an absolute `http://` or `https://` URL. No CDN, no
  web font, no analytics, no icon font. Every asset is local and relative.

**Running it**

- `uv run python scripts/serve.py` starts a server on `http://localhost:8000` and prints
  that URL. Opening it renders the feed screen.
- `scripts/serve.py` resolves `app/` relative to its own file, not the current working
  directory, so it runs the same from the repo root or anywhere else.
- It accepts an optional port as its first argument and defaults to 8000.
- It binds `127.0.0.1`, not `0.0.0.0`. A LAN address is not a secure context, so exposing
  one would only invite a confusing failure.
- It sets an explicit extension map covering at least `.html`, `.css`, `.js`, `.json`,
  `.webmanifest`, `.png` and `.ico`, rather than inheriting whatever the host OS thinks
  `.js` is.
- It sends `Cache-Control: no-store` on every response, so a stale browser cache never
  masks an edit during development.
- It imports only the standard library, imports nothing from `splitwise_lite`, and starts
  no server at import time: binding happens inside a `main()` behind an
  `if __name__ == "__main__"` guard, so a test can import it safely.
- `uv run python -m http.server -d app 8000` also serves the shell. Layout and routing
  work under it; only service worker registration is at the mercy of the host MIME map.

**The document shell**

- `app/index.html` has `<!doctype html>`, `<html lang="en">`, `<meta charset="utf-8">` as
  the first thing in `<head>`, and a `<title>`.
- The layout is a fixed header carrying the app name, a scrollable `<main>`, and a fixed
  bottom `<nav>` with three items in the order Feed, Add, Balances. Add sits in the middle
  because it is the highest-frequency action and the middle slot is the easiest thumb
  reach; the spec makes entry speed the product's main risk.
- The header exists because an installed app has no browser chrome and therefore no other
  place showing what the user is looking at.
- Nav items are anchors with `href="#/feed"`, `href="#/add"`, `href="#/balances"`, with
  text labels. No icon font, no emoji, no image-only buttons.
- The `<nav>` has an `aria-label`, and the active item carries `aria-current="page"` as
  well as a visible style. Colour alone never marks the active tab.
- Each of the three screens is a section with its own `<h1>`. Inactive screens carry the
  `hidden` attribute, so assistive technology and find-in-page do not reach them.
- A `<noscript>` block states that the app needs JavaScript. Routing is client-side, so
  without it the user would otherwise see a blank frame.
- Body text is at least 16px, and no rule sets a font size below 16px on an interactive
  element. Anything smaller triggers iOS auto-zoom the moment task 10 adds a text input.
- Loading any route produces zero console errors and zero 404s, including for the favicon.
  If no `favicon.ico` is shipped, an explicit `<link rel="icon">` points at an icon that
  exists.
- Loading any route issues zero cross-origin requests.

**Routing**

- `#/feed`, `#/add` and `#/balances` each show exactly one screen and hide the other two.
- Opening `http://localhost:8000/` with no fragment shows feed and rewrites the URL to
  `#/feed` without adding a history entry, so the first Back press leaves the app rather
  than bouncing.
- Opening `http://localhost:8000/#/balances` directly shows balances. The document request
  returns 200, never 404, for every route.
- An unknown fragment such as `#/nope` or `#/` shows feed and replaces the URL with
  `#/feed`. It must replace rather than push, so Back cannot loop between the bad URL and
  feed. A stale home screen shortcut therefore never lands on a dead screen.
- Reloading on any route restores the same screen.
- Back and forward move between visited screens in order. Tapping a nav item adds exactly
  one history entry, not two.
- Navigation does not re-request `index.html`. The Network panel shows no new document
  request when moving between tabs.
- Tapping the nav item for the screen already showing is a no-op: no error, no extra
  history entry, no visible flicker.
- Routing works through anchors and `hashchange` alone. No click handler is registered on
  a nav link.
- `document.title` changes per route, ending in the app name, for example
  `Balances - Splitwise Lite`.
- On a route change, focus moves to the newly shown screen's `<h1>` (which carries
  `tabindex="-1"`), so a screen reader announces the new view. Focus is not moved on first
  load, where the user has not navigated anywhere.
- The router is the only place that knows the route-to-screen mapping, so tasks 10 to 12
  add real content by filling a screen section, not by touching navigation.

**Responsive layout**

- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`.
  `viewport-fit=cover` is not decoration: without it `env(safe-area-inset-*)` is zero on a
  notched iPhone and the safe-area rules below do nothing.
- The viewport meta does not contain `user-scalable=no` or `maximum-scale`. Pinch zoom
  stays available.
- At 320 CSS px wide there is no horizontal scroll: `document.documentElement.scrollWidth`
  equals `clientWidth`. Checked at 320x568, 360x640 and 390x844.
- At 320 px wide all three nav labels are fully visible and unclipped, and no text
  overlaps another element.
- Every interactive element has a hit area of at least 44x44 CSS px at every tested width,
  including the nav items.
- Full-height layout uses `100dvh` with a `100vh` fallback, so the bottom nav is not cut
  off when a mobile URL bar collapses.
- The bottom nav's bottom padding includes `env(safe-area-inset-bottom, 0px)`, the header's
  top padding includes `env(safe-area-inset-top, 0px)`, and horizontal padding includes the
  left and right insets for landscape on a notched device. Every `env()` call has a `0px`
  fallback, so a browser without support renders correctly rather than collapsing.
- The scrolling content area reserves space for the fixed nav, so the last line of content
  is never hidden behind it. Scrolling to the very bottom proves it.
- Interactive elements set `touch-action: manipulation`, removing the double-tap zoom delay.
- In landscape at 844x390 the layout still works: the nav is reachable, content scrolls,
  nothing is clipped. Orientation is not locked in the manifest, because locking it would
  break users who have rotation lock set for accessibility reasons.
- Above roughly 480 px the content column is capped and centred rather than stretched
  across a laptop screen. This is a phone app that will be developed on a desktop.
- Body text meets 4.5:1 contrast against its background.
- Fonts come from a system font stack. No font is downloaded.
- If any transition or animation is used, it is disabled under
  `@media (prefers-reduced-motion: reduce)`.

**Installability: the manifest**

- `app/index.html` has `<link rel="manifest" href="manifest.json">`, and that file exists.
- `app/manifest.json` parses as JSON and contains `name`, `short_name`, `id`, `start_url`,
  `scope`, `display`, `background_color`, `theme_color` and `icons`.
- `short_name` is at most 12 characters, so a home screen label is not truncated.
- `display` is `"standalone"`.
- `id` is set explicitly. Without it, app identity is derived from `start_url`, and a later
  task changing `start_url` would install a second, separate app on every existing device.
- `start_url` and `scope` are relative (`"."`), not absolute paths, so the directory can be
  mounted under a prefix later without breaking installed copies.
- `theme_color` is identical to the `<meta name="theme-color">` value in the HTML.
- `background_color` is identical to the CSS background colour of the page, so the Android
  splash screen does not flash a different colour before the app paints.
- A `shortcuts` array holds one entry pointing at `#/add`, named for adding an expense.
  Long-pressing the installed icon on Android then jumps straight to entry, which is the
  cheapest available mitigation for the spec's "under ten seconds from lock screen"
  requirement. iOS ignores `shortcuts`, which is acceptable: it is an enhancement, and
  nothing else depends on it.
- Every URL in the manifest, including shortcut URLs and icon sources, resolves to a file
  or route that exists. A manifest that names a missing icon is the single most common way
  an app silently stops being installable.
- `<meta name="mobile-web-app-capable" content="yes">` and
  `<meta name="apple-mobile-web-app-capable" content="yes">` are both present. Chrome warns
  about the Apple one alone; older iOS needs it.
- `<meta name="apple-mobile-web-app-title">` is set, so the iOS home screen label is chosen
  rather than derived from `<title>`.

**Installability: icons**

- `icons` lists at least a 192x192 and a 512x512 PNG with `"type": "image/png"` and
  `"purpose": "any"`, plus a 512x512 entry with `"purpose": "maskable"`. Chromium treats the
  192 and 512 pair as the installability floor.
- The declared `sizes` of every icon matches the actual pixel dimensions in the PNG's IHDR
  header. A wrongly declared size is invisible until an install silently stops being
  offered.
- Every icon PNG is 8-bit RGB with no alpha channel (IHDR colour type 2). Transparency is
  then structurally impossible, which matters twice: Android's maskable crop would show
  transparent corners, and iOS renders alpha as black.
- In `icon-maskable-512.png` the mark sits inside the central 60% of the canvas, well
  within Android's 80% safe circle, and the background colour reaches every edge.
- `app/icons/apple-touch-icon-180.png` is 180x180 and is linked with
  `<link rel="apple-touch-icon" href="icons/apple-touch-icon-180.png">`. iOS prefers this
  over manifest icons, and older iOS ignores manifest icons entirely.
- `uv run python scripts/make_icons.py` regenerates all four PNGs byte for byte identically
  to the committed files, leaving `git status` clean. Icons are then reproducible without a
  design tool or an image library, and nobody has to wonder where a binary came from.
- `scripts/make_icons.py` uses the standard library only (`zlib` and `struct` are enough to
  write a PNG) and imports nothing from `splitwise_lite`.
- The mark is a simple geometric shape in the theme colour family. No wordmark, no text
  rendering, no third-party logo.

**Installability: the service worker**

- `app/sw.js` is registered from `app/app.js`, is served from the `app/` root so its scope
  is `/`, and registration is wrapped so a failure logs a clear message rather than
  breaking the page.
- The worker precaches exactly the shell files: `index.html`, `styles.css`, `app.js`,
  `manifest.json` and the four icons. Every entry in the precache list resolves to a file
  that exists.
- It has a `fetch` handler that returns a real response when the network is unavailable.
  Chromium's installability check has historically required this, and a home screen icon
  that opens a browser error page is not an installed app in any sense a user recognises.
- Navigation requests fall back to the cached `index.html`, so every route opens offline.
  Hash routing makes this simple: every route requests the same document.
- The cache name embeds a version constant. On `activate`, every cache whose name does not
  match the current version is deleted, leaving exactly one entry in Cache Storage.
- The worker calls `skipWaiting()` on install and `clients.claim()` on activate, so bumping
  the version and reloading picks up new assets instead of waiting for every tab to close.
- Nothing is cached beyond the listed shell files. No request whose path begins with `/api`
  is ever cached, so task 10's data cannot go stale behind a cache nobody remembers exists.
- The worker stores no application data, no request queue and no user input. The spec cuts
  offline entry from v1: the shell may open offline, and that is the whole of it.
- With DevTools set to Offline, reloading renders the shell and all three routes still
  navigate, with no console errors.
- Editing `styles.css`, bumping the version constant and reloading shows the change. A
  developer must not have to fight the cache to see their own edit.

**Placeholder content**

- Each screen shows its own `<h1>`, one sentence describing what will live there, and a
  visible marker that it is a placeholder, naming the task that fills it, for example
  "Placeholder. Task 11 fills this with the expense feed."
- No fake amounts, no currency symbols, no invented member names, and no fake dates appear
  anywhere in the shell. On a money app, plausible fake numbers are indistinguishable from
  wrong real ones, and the spec names "looks authoritative while being wrong" as the
  product's largest risk.
- No greyed skeleton rows, no spinners and no "loading" text. Nothing is loading. A
  skeleton reads as broken, and a spinner that never resolves reads as worse.
- No empty screen. Every screen has enough content that a reader can tell it is unfinished
  on purpose.
- The three screens are visually distinguishable from each other, so route changes are
  obviously working.

**Independence from the domain**

- No file under `app/` calls `fetch`, `XMLHttpRequest`, `EventSource` or `WebSocket`, and
  none references an API path. This task is deliberately parallel to the whole 2 to 7 chain
  and has no back end to call.
- No file under `app/` names a domain concept in a way that implies it has one: no
  allocation maths, no money formatting, no split logic, no session or auth handling.
  Money formatting already exists in `splitwise_lite.money` and will be reached through the
  back end in task 10; a second implementation in JavaScript is exactly the drift that rule
  is written to prevent.
- Nothing under `src/splitwise_lite/` or in the existing domain tests is modified.

**Docs**

- CLAUDE.md line 10 no longer reads "nothing to run yet". It names the real command:
  `uv run python scripts/serve.py`, the URL it opens on, and that there is no build step.
- CLAUDE.md's opening sentence no longer says the mobile web front end is not built yet.
- CLAUDE.md's "Where things live" list gains `app/` (the static front end shell) and
  `scripts/` (the dev server and the icon generator).
- README.md gains a "Run the app" section with the same command, and its status line stops
  claiming there is no product code.
- One of those two files states how to clear a stuck service worker (DevTools, Application,
  Service Workers, Unregister), because the first person to hit a stale shell will otherwise
  lose an hour to it.
- No document claims the shell shows real data.

**Automated tests**

- `tests/test_web_shell.py` asserts the structural facts above by parsing the files, using
  the standard library only: `json` for the manifest, `html.parser` for the HTML, `struct`
  for the PNG headers. It imports nothing from `splitwise_lite` and adds no dependency.
- It locates `app/` relative to its own file, never from the current working directory, so
  the suite passes from any directory.
- It covers at least: every promised file exists; the manifest parses and holds every
  required key; every manifest URL and every precache entry resolves to a file that exists;
  every icon's declared size matches its IHDR dimensions and its colour type is 2; the
  viewport meta string is exactly as specified; `theme_color` matches the meta tag; the
  manifest, apple-touch-icon, stylesheet and script links all resolve; no file under `app/`
  contains an absolute `http://` or `https://` URL; no file under `app/` contains `fetch(`,
  `XMLHttpRequest` or an `/api` path.
- It asserts the docs criteria: CLAUDE.md contains the exact run command and no longer
  contains "nothing to run yet".
- `tests/test_dev_server.py` starts `scripts/serve.py`'s server on port 0 on 127.0.0.1 in a
  thread, and asserts real responses: 200 and `text/html` for `/`, 200 and a JavaScript
  content type for `/app.js` and `/sw.js`, 200 and `application/json` for `/manifest.json`,
  200 and `image/png` for an icon, `Cache-Control: no-store` on each, and 404 for a path
  that does not exist. The server is shut down in fixture teardown and the thread is a
  daemon, so a failure cannot hang the suite.
- The JavaScript-only behaviour (routing, focus, service worker lifecycle) is not covered by
  automated tests, because testing it would mean a browser automation dependency. It is
  covered by the hand checklist below instead. Do not paper over the gap with a test that
  asserts the router's source text.
- No test is skipped or marked xfail. If loopback binding turns out to be blocked in this
  environment, stop and raise it rather than skipping `tests/test_dev_server.py`.

**Verified by hand**

Each of these is a check QA can perform and record. Chrome DevTools is the tool; Lighthouse
is not, because it no longer ships PWA installability audits.

- With the device toolbar at 320x568, then 360x640, then 390x844, then landscape 844x390:
  no horizontal scroll, all nav labels legible, nothing clipped or overlapping, and the
  bottom of the content reachable.
- Application, Manifest: the panel parses the manifest, renders the icons, and reports no
  installability errors.
- Application, Service Workers: exactly one worker, status activated, scope `/`.
- Application, Cache Storage: exactly one cache, holding the precached shell files and
  nothing else.
- The install affordance appears in Chrome (the omnibox install icon). Installing it puts
  the icon on the home screen or launcher with the app's own icon, not a screenshot of the
  page, and launching it opens standalone with no address bar.
- In the installed window, every screen is still reachable, because there is no browser Back
  button to fall back on.
- Network set to Offline, then reload: the shell renders and all three routes navigate.
- Console is clean on load and after visiting all three routes, online and offline.
- On iOS Safari where a device is available: Share, Add to Home Screen shows the intended
  name and icon, and launching shows no Safari chrome. Where no device is available, record
  it as unverified rather than as passing. The metas and alpha-free PNGs that make it work
  are asserted by the automated tests either way.

**Suite**

- `uv run python -m pytest` passes. Every test already in `tests/` keeps passing unchanged,
  and `tests/test_smoke.py` is untouched.

## Out of scope

- Any real data. No expenses, no members, no balances, no amounts, no dates. Tasks 10, 11
  and 12 wire those in, and each owns its own screen's content.
- Any import from, or knowledge of, `splitwise_lite`. The shell is deliberately parallel to
  the entire 2 to 7 chain, which is the only reason it can be built now.
- Auth, login, signup, sessions or any "who am I" concept. Task 7 owns those.
- A back end, an HTTP API, a route handler, a template engine, or serving `app/` from
  anything other than the dev script. Task 10 chooses how the application serves these
  files and may move or mount `app/` then; that is why every URL in the shell is relative.
- Forms and inputs, including an amount field. The add screen is a placeholder in this task;
  task 10 builds entry, and entry speed is judged there.
- Offline data entry, a local queue, background sync or conflict resolution. The spec cuts
  these from v1. The service worker caches the shell and nothing else.
- Push notifications, badging, and anything else the spec's "Notifications" cut covers. The
  service worker gets a `fetch` handler and no `push` handler.
- A custom install button driven by `beforeinstallprompt`. The browser's own affordance is
  enough, the event never fires on iOS, and a button that does nothing on half the target
  devices is worse than no button.
- Dark mode, theming, and `prefers-color-scheme`. One light theme, matching `theme_color`
  and `background_color`.
- Orientation locking, splash screen images beyond `background_color`, and iOS startup
  images.
- Multi-group navigation, a group switcher, or any fourth screen. The spec exposes one
  group and the backlog names three screens.
- A JavaScript test runner, browser automation, a linter, a formatter or a type checker for
  either language. Any of those is a dependency decision, and this task's decision is no.
- ES modules and a multi-file JavaScript structure. One `app.js` is enough for a router this
  size, and classic scripts sidestep the strict module MIME check that trips up stdlib
  static servers. A later task with real client logic can revisit it.
- Packaging `app/` into the wheel. `pyproject.toml` is not touched; how the shell ships is
  task 10's problem.

## Constraints

- Files to create: `app/index.html`, `app/styles.css`, `app/app.js`, `app/sw.js`,
  `app/manifest.json`, `app/icons/icon-192.png`, `app/icons/icon-512.png`,
  `app/icons/icon-maskable-512.png`, `app/icons/apple-touch-icon-180.png`,
  `scripts/serve.py`, `scripts/make_icons.py`, `tests/test_web_shell.py`,
  `tests/test_dev_server.py`. Nothing else.
- Files to modify: `CLAUDE.md` and `README.md`, for the run command and the layout notes
  only.
- Do not modify anything under `src/splitwise_lite/`, anything in `tests/` other than the
  two new files, `pyproject.toml`, `uv.lock`, `plans/backlog.md`, `plans/spec.md`, this
  file, or anything under `.claude/`.
- **No new dependency of any kind, in either language.** Nothing is added to
  `pyproject.toml`, and no `package.json` is created. Per CLAUDE.md, a dependency is
  declared in `pyproject.toml` and installed with `uv sync`, never ad hoc, and
  `.claude/hooks/guard-deps.hs.sh` blocks the ad hoc route anyway. If something here
  genuinely cannot be built without a package, stop and raise it.
- The run command is exactly `uv run python scripts/serve.py`, serving `app/` on
  `http://localhost:8000`. That exact string goes in CLAUDE.md and README.md.
- Python files use the standard library only and target Python 3.12: `http.server`,
  `socketserver`, `pathlib`, `functools`, `sys`, `zlib`, `struct`, and in the tests `json`,
  `html.parser`, `urllib.request` and `threading`.
- JavaScript is plain, browser-native, classic (non-module) scripts. No framework, no
  polyfill, no transpilation, no minification. The committed file is the file the browser
  runs.
- CSS is hand-written in one file. No preprocessor, no utility framework, no reset library.
  Custom properties for the two or three colours are fine and keep the manifest and the meta
  tag in step.
- Every URL inside `app/` is relative, never rooted at `/`. That is what lets a later task
  mount the directory under a prefix without editing every file, and what makes
  `start_url: "."` correct.
- The router owns the route-to-screen mapping in one place. Adding a route must mean adding
  one entry, not editing three files.
- Tests locate `app/` from `Path(__file__).resolve().parents[1]`, never from the current
  working directory.
- Tests use exact assertions, not substring guesses at formatting, per
  `.claude/rules/testing.md`. No test is skipped or xfailed.
- The default route is feed. Task 10 may argue for launching straight into add once entry
  exists and can be timed against the ten-second requirement; that is a decision made with
  a measurement, not now.
- Every non-obvious choice already made here (hash routing, `manifest.json` over
  `.webmanifest`, the dev server's extension map, classic scripts) gets a one-line comment
  in the file that implements it, so the next person does not undo it by tidying.

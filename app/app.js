/* Splitwise Lite shell: routing, the document title, focus, the auth gate and
   registering the service worker.

   A classic (non-module) script on purpose: there is one file to load, and a
   standard library static server can hand back a MIME type that the strict module
   check rejects, which would leave the app blank.

   This file never talks to the back end. It loads the API client and calls it, so
   there is exactly one network chokepoint and one answer to a 401. The client is
   pulled in from here rather than from a second <script> tag in the document,
   because the document loads exactly one script and the router is it. */

(function () {
  'use strict';

  var APP_NAME = 'Splitwise Lite';

  /* Hash routing, not the History API: a fragment never reaches the server, so a
     reload or a deep link works against any static file server. This table is the
     only place that knows which route maps to which screen, so tasks 10 to 12 fill
     a screen by editing its section, not by touching navigation. Adding a route is
     one entry here plus one section in index.html. */
  var ROUTES = {
    '#/feed': { screen: 'screen-feed', title: 'Feed' },
    '#/add': { screen: 'screen-add', title: 'Add' },
    '#/balances': { screen: 'screen-balances', title: 'Balances' }
  };
  var DEFAULT_ROUTE = '#/feed';

  var current = null;
  var api = null;

  /* Whether the three screens below may read the ledger and move focus into it.
     Declared here, in the preamble, because every screen block asks it and none of
     them owns it; `showing` is the gate block's, assigned by show() and read back
     here. Three conditions, and each covers a case no other one does:

       the client is loaded. This file loads it as a second script, so a hashchange
       can arrive before that has happened, and the client may fail to load at all.
       Read first, so nothing below it ever reaches into a client that is not there.

       the client holds a session view carrying a member. Nobody is signed in when
       there is no view; somebody signed in with no member row is refused by every
       endpoint these screens read, by name, on every request they make.

       show() last put the app frame up. The only one of the three that catches an
       offline or a problem curtain: api.js drops the cached view for a session the
       server has disowned and deliberately leaves it alone for the rest, so a
       curtain can be up over a session that is still live and still linked.

     Two harms, both real, and neither cosmetic. A screen that reads while a curtain
     is up sends a request that is certain to be refused, and the refusal raises a
     curtain over the curtain: a person who has just been told why their sign-in
     failed loses that sentence to a request they never asked for. And a screen that
     moves focus while a curtain is up puts the cursor inside hidden content, which
     for a screen reader or a keyboard user means focus leaving the password field
     with nothing announcing why.

     This asks the client what session it holds, and asks this file what it last
     drew. Both are answers somebody has already decided; neither is an answer from
     the server being interpreted a second time here, and api.js remains the one
     file that decides what such an answer means.

     One honest note for whoever changes this next. Dropping the member half of the
     second condition turns no scenario red, and that is not an oversight in the
     scenarios: show('app') has one caller, and it is reached only for a view that
     carries a member, so the app frame over a memberless view is unreachable today.
     It is kept because it is the condition that says what this helper means, and
     because callers read a member off that view once this has said yes. Treat it as
     the invariant's statement rather than as the line the tests are holding. */
  function ledgerIsUp() {
    if (!api) {
      return false;
    }
    var view = api.cachedSession();
    if (!view || !view.member) {
      return false;
    }
    return showing === 'app';
  }

  function known(hash) {
    return Object.prototype.hasOwnProperty.call(ROUTES, hash);
  }

  function render(hash, moveFocus) {
    var changed = hash !== current;
    current = hash;

    Object.keys(ROUTES).forEach(function (route) {
      var screen = document.getElementById(ROUTES[route].screen);
      if (screen) {
        screen.hidden = route !== hash;
      }
    });

    var tabs = document.querySelectorAll('.tabbar a');
    Array.prototype.forEach.call(tabs, function (tab) {
      if (tab.getAttribute('href') === hash) {
        tab.setAttribute('aria-current', 'page');
      } else {
        tab.removeAttribute('aria-current');
      }
    });

    document.title = ROUTES[hash].title + ' - ' + APP_NAME;

    if (changed && moveFocus && ledgerIsUp()) {
      /* Focus the heading of the screen that just appeared, so a screen reader
         announces the new view. The heading carries tabindex="-1" for this.

         Not while a curtain is up. Every heading sits inside .content, which the
         gate and the two notices hide, so moving focus there would take it out of
         the password field and put it somewhere nobody can see, with nothing
         announcing why. Everything above this line still tracks the hash, so
         signing in reveals the screen the person was already on. */
      var shown = document.getElementById(ROUTES[hash].screen);
      var heading = shown ? shown.querySelector('h1') : null;
      if (heading) {
        heading.focus();
      }
    }
  }

  function route(moveFocus) {
    var hash = window.location.hash;
    if (!known(hash)) {
      /* Replace, never push: a stale shortcut or a typo must not leave a dead
         entry that Back can loop through, and the first load must not cost the
         user two Back presses to leave the app. */
      window.history.replaceState(null, '', DEFAULT_ROUTE);
      hash = DEFAULT_ROUTE;
    }
    render(hash, moveFocus);
  }

  /* Anchors plus hashchange do all the navigation. No click handler is registered
     on a nav link, so Back, forward, reload, deep linking, long-press-to-copy and
     keyboard navigation all work with no code written for them. */
  window.addEventListener('hashchange', function () {
    route(true);
  });

  /* No focus move on first load: the user has not navigated anywhere yet. */
  route(false);

  /* --- The expense feed ------------------------------------------------- */

  /* Fills #screen-feed from the expenses endpoint and the roster. Read-only: editing
     and voiding are task 17, and the staleness signal is task 16.

     Four states, and exactly one of them is up at any moment: the in-flight line, the
     empty statement, the failure notice and the list. That is structural rather than
     careful, because every state change goes through feedState(), which hides all
     four and then shows one. A blank feed area while a request is in the air is
     indistinguishable from a group that has recorded nothing, and that confusion is
     the product's largest stated risk in miniature.

     No money arithmetic. Amounts arrive as strings the server has already formatted
     and reach the DOM untouched: nothing here parses, adds, divides, rounds or
     reformats a cent value. The detail shows every share and then the total those
     shares are shares of, and claims no relationship between them. ExpenseEvent
     already enforces that they sum exactly, and a second implementation of that sum
     here is the drift the no-arithmetic rule exists to prevent.

     Every piece of user data reaches the DOM through textContent. An expense
     described as <img src=x onerror=alert(1)> renders as those literal characters.

     Every name in this block is prefixed, because the task 12 branch is adding its
     own block to this same file and this same scope. */

  /* The one route literal outside ROUTES, and the accepted cost of not editing
     render(), which the sibling branch also needs. The route-to-screen mapping itself
     still lives in ROUTES, so task 8's constraint holds. */
  var FEED_ROUTE = '#/feed';

  var FEED_MONTHS = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ];
  var FEED_MONTHS_FULL = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ];

  var feedLoading = document.getElementById('feed-loading');
  var feedEmpty = document.getElementById('feed-empty');
  var feedError = document.getElementById('feed-error');
  var feedRetry = document.getElementById('feed-retry');
  var feedCurrency = document.getElementById('feed-currency');
  var feedList = document.getElementById('feed-list');
  var feedBusy = false;

  function feedText(tag, className, value) {
    var element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    element.textContent = value;
    return element;
  }

  function feedState(which) {
    /* One of 'loading', 'empty', 'error' or 'list'. Every state change comes through
       here, which is what makes "exactly one is visible" structural rather than a
       rule four call sites have to remember. */
    feedLoading.hidden = which !== 'loading';
    feedEmpty.hidden = which !== 'empty';
    feedError.hidden = which !== 'error';
    feedCurrency.hidden = which !== 'list';
    feedList.hidden = which !== 'list';
    if (which !== 'list') {
      /* No list is ever shown beside a failure notice, and a failure never shows the
         empty state: those are three different things and must look like three. */
      feedList.replaceChildren();
    }
  }

  function feedIsText(value) {
    return typeof value === 'string';
  }

  function feedValidEntry(entry) {
    if (!entry || typeof entry !== 'object') {
      return false;
    }
    if (!feedIsText(entry.id) || !feedIsText(entry.description)) {
      return false;
    }
    if (!feedIsText(entry.amount) || !feedIsText(entry.payer_id)) {
      return false;
    }
    if (!feedIsText(entry.created_by) || !feedIsText(entry.created_at)) {
      return false;
    }
    if (!Array.isArray(entry.allocations)) {
      return false;
    }
    for (var index = 0; index < entry.allocations.length; index += 1) {
      var allocation = entry.allocations[index];
      if (!allocation || typeof allocation !== 'object') {
        return false;
      }
      if (!feedIsText(allocation.member_id) || !feedIsText(allocation.amount)) {
        return false;
      }
    }
    return true;
  }

  function feedValidPayload(payload) {
    if (!payload || typeof payload !== 'object') {
      return false;
    }
    if (!feedIsText(payload.currency) || !Array.isArray(payload.expenses)) {
      return false;
    }
    for (var index = 0; index < payload.expenses.length; index += 1) {
      if (!feedValidEntry(payload.expenses[index])) {
        return false;
      }
    }
    return true;
  }

  function feedValidRoster(payload) {
    if (!payload || typeof payload !== 'object') {
      return false;
    }
    if (!Array.isArray(payload.members)) {
      return false;
    }
    for (var index = 0; index < payload.members.length; index += 1) {
      var member = payload.members[index];
      if (!member || typeof member !== 'object') {
        return false;
      }
      if (!feedIsText(member.id) || !feedIsText(member.display_name)) {
        return false;
      }
    }
    return true;
  }

  function feedNames(members) {
    /* Object.create(null), so a member id spelled '__proto__' cannot reach through to
       Object.prototype and answer for a member who does not exist. */
    var names = Object.create(null);
    for (var index = 0; index < members.length; index += 1) {
      names[members[index].id] = members[index].display_name;
    }
    return names;
  }

  function feedKnows(names, memberId) {
    return Object.prototype.hasOwnProperty.call(names, memberId);
  }

  function feedNameFor(names, memberId) {
    /* An id the roster does not know renders as words, never as a blank and never as
       a raw id: a UUID on screen is noise that helps nobody. One unresolvable id must
       not stop its row, or any other row, from rendering. Two members may share a
       display name, which store.Member allows on purpose; both render the same text
       and this screen does not invent a "Sam (2)" to tell them apart. */
    if (feedKnows(names, memberId)) {
      return names[memberId];
    }
    return 'Unknown member';
  }

  function feedRosterOrder(allocations, members, names) {
    /* Roster order rather than allocation order, so the same set of people reads the
       same way on every row and the summary line and the detail agree. An allocation
       the roster does not know keeps its place at the end rather than vanishing. */
    var ordered = [];
    var member;
    var index;
    for (member = 0; member < members.length; member += 1) {
      for (index = 0; index < allocations.length; index += 1) {
        if (allocations[index].member_id === members[member].id) {
          ordered.push(allocations[index]);
        }
      }
    }
    for (index = 0; index < allocations.length; index += 1) {
      if (!feedKnows(names, allocations[index].member_id)) {
        ordered.push(allocations[index]);
      }
    }
    return ordered;
  }

  function feedParticipants(ordered, names) {
    /* Three or fewer are all named; four or more become the first two and a count, so
       six 100 character display names cannot run the line off a 320px screen.
       Counting participants is not money arithmetic: no cent value is touched. A zero
       cent share is a participant like any other and is counted, because a
       participant list that disagrees with the detail is a bug the reader cannot
       see. */
    var shown = [];
    var index;
    if (ordered.length <= 3) {
      for (index = 0; index < ordered.length; index += 1) {
        shown.push(feedNameFor(names, ordered[index].member_id));
      }
      if (shown.length < 2) {
        return shown.join('');
      }
      return shown.slice(0, shown.length - 1).join(', ') +
        ' and ' + shown[shown.length - 1];
    }
    for (index = 0; index < 2; index += 1) {
      shown.push(feedNameFor(names, ordered[index].member_id));
    }
    return shown.join(', ') + ' and ' + (ordered.length - 2) + ' others';
  }

  function feedInstant(createdAt) {
    /* The server's instant, read in the reader's timezone. The client clock is never
       read: there is no Date built with no argument anywhere in this block, no
       elapsed time and no relative label. created_at carries six fractional digits,
       which is more than the ECMAScript date-time grammar requires an engine to
       accept, so an engine that refuses it gets a fallback rather than NaN. */
    var when = new Date(createdAt);
    if (isNaN(when.getTime())) {
      return null;
    }
    return when;
  }

  function feedDate(createdAt) {
    /* Absolute, and local rather than UTC. A flat in Australia entering the milk at
       8am local on the 5th stores it as the 4th in UTC, and printing that would tell
       them they logged it yesterday. Spelled by hand rather than by locale, so every
       reader of one ledger sees one spelling. No Today, no Yesterday, no N days ago:
       relative time is task 16's vocabulary, and a feed that cheerfully says Today
       over a two week old ledger is the confident wrongness task 16 exists to
       prevent. */
    var when = feedInstant(createdAt);
    if (when === null) {
      return String(createdAt).slice(0, 10);
    }
    return when.getDate() + ' ' + FEED_MONTHS[when.getMonth()] +
      ' ' + when.getFullYear();
  }

  function feedTwoDigits(value) {
    var text = String(value);
    if (text.length < 2) {
      return '0' + text;
    }
    return text;
  }

  function feedDateAndTime(createdAt) {
    /* The detail spells the same instant out in full, still local and still
       absolute. 24 hour, so no am and pm has to be worked out or read wrongly. */
    var when = feedInstant(createdAt);
    if (when === null) {
      return String(createdAt).slice(0, 10);
    }
    return when.getDate() + ' ' + FEED_MONTHS_FULL[when.getMonth()] +
      ' ' + when.getFullYear() + ' at ' + feedTwoDigits(when.getHours()) +
      ':' + feedTwoDigits(when.getMinutes());
  }

  function feedShares(entry, memberId) {
    for (var index = 0; index < entry.allocations.length; index += 1) {
      if (entry.allocations[index].member_id === memberId) {
        return true;
      }
    }
    return false;
  }

  function feedDetail(entry, names, ordered) {
    var detail = document.createElement('div');
    detail.className = 'expense-detail';
    /* Derived from the expense id, so it is unique in the document and the summary's
       aria-controls can name it. */
    detail.id = 'expense-detail-' + entry.id;
    /* Hidden when collapsed, so neither a screen reader nor find-in-page reaches a
       closed detail. */
    detail.hidden = true;

    var shares = document.createElement('ul');
    shares.className = 'expense-shares';
    var index;
    for (index = 0; index < ordered.length; index += 1) {
      var share = document.createElement('li');
      share.className = 'expense-share';
      share.appendChild(feedText(
        'span',
        'expense-share-name',
        feedNameFor(names, ordered[index].member_id)
      ));
      /* Every allocation, a zero cent share included, rendered exactly as the API
         spelled it. Never dropped, never blanked and never dashed out. */
      share.appendChild(feedText('span', 'expense-figure', ordered[index].amount));
      shares.appendChild(share);
    }
    detail.appendChild(shares);

    /* The shares, then the total those shares are shares of, and no sentence claiming
       a relationship between the two: the front end is in no position to have checked
       one. The screen never adds the shares up. */
    var total = document.createElement('p');
    total.className = 'expense-total';
    total.appendChild(feedText('span', 'expense-total-label', 'Total'));
    total.appendChild(feedText('span', 'expense-figure', entry.amount));
    detail.appendChild(total);

    if (!feedShares(entry, entry.payer_id)) {
      /* Task 4 supports paying for a meal you did not eat. The payer is not quietly
         added to the participant list and no share is implied for them; the fact is
         stated here instead. */
      detail.appendChild(feedText(
        'p',
        'expense-note',
        feedNameFor(names, entry.payer_id) + ' paid and is not sharing this expense.'
      ));
    }
    if (entry.created_by !== entry.payer_id) {
      detail.appendChild(feedText(
        'p',
        'expense-note',
        'Recorded by ' + feedNameFor(names, entry.created_by) + '.'
      ));
    }
    detail.appendChild(feedText(
      'p',
      'expense-when',
      feedDateAndTime(entry.created_at)
    ));
    return detail;
  }

  function feedRow(entry, members, names) {
    var ordered = feedRosterOrder(entry.allocations, members, names);
    var row = document.createElement('li');
    row.className = 'expense-row';
    var detail = feedDetail(entry, names, ordered);

    /* An inline disclosure, not a modal, not a bottom sheet and not a fourth route.
       It pushes nothing onto the history stack, so Back still leaves the app from the
       feed and task 8's history criteria survive untouched; and it needs none of the
       focus trap, escape handler, scroll lock and inert background a modal on a phone
       would need and would get half right. The whole row is the tap target. */
    var summary = document.createElement('button');
    summary.type = 'button';
    summary.className = 'expense-summary';
    summary.setAttribute('aria-expanded', 'false');
    summary.setAttribute('aria-controls', detail.id);

    var body = document.createElement('span');
    body.className = 'expense-body';

    var first = document.createElement('span');
    first.className = 'expense-line';
    var described = String(entry.description).trim();
    if (described === '') {
      /* A fixed literal, never a summary invented from the other fields: "Milk run"
         is indistinguishable from a description a person typed, which is the
         authoritative-while-wrong failure the spec names as the largest risk. Not
         blank either, because a blank first line makes the row look broken. */
      first.appendChild(feedText(
        'span',
        'expense-description expense-description--none',
        'No description'
      ));
    } else {
      first.appendChild(feedText('span', 'expense-description', described));
    }
    /* The amount as format_amount produced it: no symbol prepended, no digit
       reformatted, no separator changed. */
    first.appendChild(feedText('span', 'expense-figure', entry.amount));
    body.appendChild(first);

    var second = document.createElement('span');
    second.className = 'expense-line';
    second.appendChild(feedText(
      'span',
      'expense-payer',
      'Paid by ' + feedNameFor(names, entry.payer_id)
    ));
    var stamp = feedText('time', 'expense-date', feedDate(entry.created_at));
    /* The raw instant survives in the markup even though the visible text is rounded
       to a day. */
    stamp.setAttribute('datetime', entry.created_at);
    second.appendChild(stamp);
    body.appendChild(second);

    var third = document.createElement('span');
    third.className = 'expense-line expense-line--split';
    third.appendChild(feedText(
      'span',
      'expense-split',
      'Split across ' + feedParticipants(ordered, names)
    ));
    body.appendChild(third);

    summary.appendChild(body);
    /* Open and closed are told apart by this glyph as well as by the detail itself,
       and never by colour alone. It is aria-hidden because aria-expanded already says
       the same thing to a screen reader, twice would be noise. */
    var indicator = feedText('span', 'expense-indicator', '+');
    indicator.setAttribute('aria-hidden', 'true');
    summary.appendChild(indicator);

    summary.addEventListener('click', function () {
      /* More than one row may be open at once: collapsing somebody else's row to open
         yours is surprising, and single-open would be a piece of state the next
         render has to preserve. Nothing here scrolls the page, touches the hash, adds
         a history entry or re-renders another row. */
      var open = summary.getAttribute('aria-expanded') === 'true';
      summary.setAttribute('aria-expanded', open ? 'false' : 'true');
      detail.hidden = open;
      indicator.textContent = open ? '+' : '-';
    });

    row.appendChild(summary);
    row.appendChild(detail);
    return row;
  }

  function feedRender(payload, roster) {
    var members = roster.members;
    var names = feedNames(members);
    var rows = document.createDocumentFragment();
    /* Rendered in the order the array arrived, with nothing here sorting, reversing,
       comparing or grouping it. web.py owns the ordering rule and has it written
       down: store.list_expenses returns ascending (created_at, id) and the endpoint
       turns it around, giving newest first with ties broken by id descending. A
       second ordering rule here would be a second contract to keep in step with the
       first, and the two would disagree the first time either one changed. */
    for (var index = 0; index < payload.expenses.length; index += 1) {
      rows.appendChild(feedRow(payload.expenses[index], members, names));
    }
    /* Each load replaces the whole list, so a reload never duplicates a row.
       Expansion state resets with it, which is accepted. */
    feedList.replaceChildren(rows);
    /* The group's one currency code, spelled as the server spells it. Never turned
       into a symbol: web.py formats amounts with symbol=False on purpose and the
       front end does not overrule that. No per-row marker either, because the group
       has exactly one currency and repeating it on every line is noise. */
    feedCurrency.textContent = 'Amounts in ' + payload.currency + '.';
    feedState('list');
  }

  function loadFeed() {
    /* Three guards before anything happens: somebody is signed in and looking at the
       ledger rather than at a curtain, this screen's route is the current one, and no
       load is already running. The helper in the preamble carries the first one and
       says why. A load while a load is running is skipped rather than queued, so repeated tab
       taps cannot stack requests. */
    if (!ledgerIsUp() || window.location.hash !== FEED_ROUTE || feedBusy) {
      return;
    }
    feedBusy = true;
    feedState('loading');

    function done() {
      feedBusy = false;
    }

    /* Both requests go out together and the list renders only once both have
       answered. The expenses carry ids and the roster carries the names, and there is
       no endpoint that joins the two: that is the design, not an oversight. Nothing
       is kept between loads, so there is no cache here for two concurrent branches to
       have to agree on, and nothing reaches browser storage. */
    Promise.all([api.expenses(), api.members()]).then(
      function (answers) {
        if (!feedValidPayload(answers[0]) || !feedValidRoster(answers[1])) {
          /* A 200 carrying something other than the documented shape is a failure,
             not an empty group. */
          feedState('error');
        } else if (answers[0].expenses.length === 0) {
          /* A group on day one. Not an error, and never dressed up as a settled
             ledger: the copy says only that nothing has been recorded. */
          feedState('empty');
        } else {
          feedRender(answers[0], answers[1]);
        }
      },
      function () {
        /* 401, 403 member_not_linked, a network failure and any 5xx are already
           claimed by api.js, which raises the gate or one of the two notices over the
           whole frame. The status code is deliberately not read here: there is
           exactly one place that decides what a 401 means, and it is not this screen.
           This notice sits behind that curtain, where nobody sees it. */
        feedState('error');
      }
    ).then(done, done);
  }

  /* Re-issues both requests and returns to the in-flight state while they run. */
  feedRetry.addEventListener('click', function () {
    loadFeed();
  });

  /* The feed loads when its own route becomes current, and once more when the frame
     is shown after a successful session check. Nothing else: no polling, no timer, no
     interval, no visibility handler and no reload when the window regains focus.
     Leaving for Add or Balances and coming back re-requests, because a feed that
     loaded once and never again would show a stale list the moment task 10 records an
     expense, which is the same authoritative-while-wrong failure in another costume.
     This block listens for itself rather than editing render(), which the task 12
     branch also needs. */
  window.addEventListener('hashchange', function () {
    loadFeed();
  });


  /* --- The expense entry form ------------------------------------------- */

  /* Fills #screen-add and records one expense. "Log a spend in under ten seconds" is
     the requirement this block exists to pay for, not a nice to have: the spec names
     adoption rather than arithmetic as the risk that kills the product, and a
     half-filled ledger looks authoritative while being wrong.

     Three things buy those ten seconds, and each is separately checkable. The amount
     field is focused the moment the screen opens, before the roster has even been
     asked for, so the keypad is up while the request is still in the air. Equal
     across everyone is the default, and it is the default in the committed markup, so
     nothing has to load or resolve for the common case to be right. With the roster
     in, a complete expense is an amount plus one tap on Save.

     No money arithmetic, anywhere. The amount is the characters that were typed with
     surrounding whitespace removed and nothing else changed: no comma stripped, no
     symbol removed, no digit padded and no decimal point added. Nothing here parses,
     adds, divides, rounds, compares or reformats a cent value, so there is no running
     total of the uneven shares, no remaining figure and no "you are out by" line.
     parse_amount at the input edge is the only judge of an amount in this system, and
     a second one here would be a rule that drifts.

     Every refusal the server can make is shown in the server's own words. A screen
     that substitutes its own copy per error code is a second error contract that
     drifts from the first the day either changes.

     Every name in this block is prefixed, because two sibling branches are editing
     this same file and this same scope. */

  /* The one route literal outside ROUTES, and the accepted cost of not editing
     render(), which both sibling branches also need. */
  var ADD_ROUTE = '#/add';
  /* This block's own literal, matching the balances screen's suffix. No helper is
     shared across regions: a shared helper is a shared edit to a file three branches
     are changing at once. */
  var ADD_ACTING_SUFFIX = ' (you)';
  /* The one JavaScript literal on the failure path, for a refusal that carried no
     message at all. It mirrors the gate's existing 'That did not work.' */
  var ADD_SAVE_FAILED = 'That did not save.';

  var addCurrency = document.getElementById('add-currency');
  var addCurrencyCode = document.getElementById('add-currency-code');
  var addForm = document.getElementById('add-form');
  var addAmount = document.getElementById('add-amount');
  var addDescription = document.getElementById('add-description');
  var addPayer = document.getElementById('add-payer');
  var addModeEqual = document.getElementById('add-mode-equal');
  var addModeSome = document.getElementById('add-mode-some');
  var addModeExact = document.getElementById('add-mode-exact');
  var addHintSome = document.getElementById('add-hint-some');
  var addHintExact = document.getElementById('add-hint-exact');
  var addPeople = document.getElementById('add-people');
  var addRosterBusy = document.getElementById('add-roster-busy');
  var addRosterFailed = document.getElementById('add-roster-error');
  var addRosterRetry = document.getElementById('add-roster-retry');
  var addEmptyRoster = document.getElementById('add-empty-roster');
  var addSubmit = document.getElementById('add-submit');
  var addSavingLine = document.getElementById('add-saving');
  var addSavedPanel = document.getElementById('add-saved');
  var addSavedAmount = document.getElementById('add-saved-amount');
  var addSavedDescription = document.getElementById('add-saved-description');
  var addErrorRegion = document.getElementById('add-error');
  var addErrorAmount = document.getElementById('add-error-amount');
  var addErrorRoster = document.getElementById('add-error-roster');
  var addErrorServer = document.getElementById('add-error-server');

  /* The roster for the life of one visit, because switching split modes rebuilds the
     people list from it and a second read would be a second request for data the
     screen already has. Re-read on every entry to the route, and it reaches no
     browser storage: a copy of server state kept in the browser is how a signed-out
     page keeps showing a ledger. */
  var addRoster = null;
  /* One row per member while a mode that needs them is chosen, paired with the member
     it belongs to, so reading the ticks and the typed shares back never depends on
     walking the DOM or on matching a name. */
  var addRows = [];
  /* The chosen mode, held in one variable and written by each radio's own listener.
     The three radios are never scanned to discover which is checked. */
  var addMode = 'equal';
  var addRosterInFlight = false;
  var addSaveInFlight = false;

  function addShowError(which) {
    /* One of 'amount', 'roster', 'server' or ''. Every change comes through here,
       which is what makes "at most one is ever visible" structural rather than a rule
       four call sites have to remember. The alert region itself goes down with its
       children: an empty alert is still a landmark a screen reader lands in. */
    addErrorAmount.hidden = which !== 'amount';
    addErrorRoster.hidden = which !== 'roster';
    addErrorServer.hidden = which !== 'server';
    addErrorRegion.hidden = which === '';
  }

  function addRosterArrived() {
    /* "The people in this group have not arrived yet" stops being true the moment they
       do, so the refusal that said so comes down with it rather than waiting for the
       next tap to withdraw it. Typing while the roster loads is the whole point of this
       screen, so saving during that window is a normal thing to do and a stale refusal
       left behind it is a false sentence on the fast path.

       Scoped to the one child this path owns, and deliberately not a blanket clear: a
       message the server sent about a refused save is still true and is not this
       screen's to take back. addShowError keeps at most one of the three visible, so
       reading the one child answers "is this mine to clear" without guessing at the
       others. */
    if (!addErrorRoster.hidden) {
      addShowError('');
    }
  }

  function addRosterState(which) {
    /* One of 'busy', 'error', 'empty' or ''. A blank area while a request is in the
       air is indistinguishable from a group that has nobody in it, and that confusion
       is the product's largest stated risk in miniature. No skeleton and no spinner:
       a skeleton reads as broken. */
    addRosterBusy.hidden = which !== 'busy';
    addRosterFailed.hidden = which !== 'error';
    addEmptyRoster.hidden = which !== 'empty';
  }

  function addIsText(value) {
    return typeof value === 'string';
  }

  function addValidRoster(payload) {
    if (!payload || typeof payload !== 'object') {
      return false;
    }
    if (!Array.isArray(payload.members)) {
      return false;
    }
    for (var index = 0; index < payload.members.length; index += 1) {
      var member = payload.members[index];
      if (!member || typeof member !== 'object') {
        return false;
      }
      if (!addIsText(member.id) || !addIsText(member.display_name)) {
        return false;
      }
    }
    return true;
  }

  function addHasMember(members, memberId) {
    for (var index = 0; index < members.length; index += 1) {
      if (members[index].id === memberId) {
        return true;
      }
    }
    return false;
  }

  function addActingId() {
    /* Whoever is entering, taken from the session view the client already holds, so
       defaulting the payer costs no extra round trip. A missing view, or one whose
       member is null because nobody has linked the account, defaults nothing and
       breaks nothing else on the screen. */
    var view = api.cachedSession();
    if (view && view.member && view.member.id) {
      return view.member.id;
    }
    return null;
  }

  function addNameFor(member, actingId) {
    if (actingId !== null && member.id === actingId) {
      return member.display_name + ADD_ACTING_SUFFIX;
    }
    return member.display_name;
  }

  function addShowCurrency() {
    /* The roster read carries no currency, so the code comes from the session view
       the client already holds. If it holds none the line stays down rather than
       guessing, and it is never turned into a symbol: web.py formats amounts without
       one on purpose and the front end does not overrule that. */
    var view = api.cachedSession();
    var code = view && view.group ? view.group.currency : null;
    if (addIsText(code) && code !== '') {
      addCurrencyCode.textContent = code;
      addCurrency.hidden = false;
      return;
    }
    addCurrencyCode.textContent = '';
    addCurrency.hidden = true;
  }

  function addDefaultPayer() {
    /* Assigned to the picker's value, never left to a browser to select the first
       option and never written as a `selected` attribute on one: which member pays by
       default is a decision this screen makes and should be able to change in one
       place. */
    if (addRoster === null || addRoster.length === 0) {
      return;
    }
    var actingId = addActingId();
    if (actingId !== null && addHasMember(addRoster, actingId)) {
      addPayer.value = actingId;
      return;
    }
    addPayer.value = addRoster[0].id;
  }

  function addFillPayer() {
    var actingId = addActingId();
    /* One option per member, in the order the payload returned. Nothing is sorted,
       reversed, filtered or deduplicated: the roster's order is the group's order and
       there is no second one here to drift from it. */
    for (var index = 0; index < addRoster.length; index += 1) {
      var option = document.createElement('option');
      option.value = addRoster[index].id;
      /* textContent, so a member called <img src=x onerror=alert(1)> renders as those
         literal characters and is never markup. */
      option.textContent = addNameFor(addRoster[index], actingId);
      addPayer.appendChild(option);
    }
    addDefaultPayer();
  }

  function addPersonRow(member) {
    var row = document.createElement('label');
    row.className = 'add-person';
    var field = document.createElement('input');
    if (addMode === 'some') {
      field.type = 'checkbox';
      field.className = 'add-person-tick';
      /* Everyone ticked, so the usual case of "everyone except one" is one untick. */
      field.checked = true;
    } else {
      field.type = 'text';
      field.className = 'add-person-share';
      field.setAttribute('inputmode', 'decimal');
      /* Left empty, and an empty field means "not sharing this one": that member is
         left out of the request entirely. Somebody sharing nothing types a zero. */
    }
    row.appendChild(field);
    var name = document.createElement('span');
    name.className = 'add-person-name';
    name.textContent = member.display_name;
    row.appendChild(name);
    return { member: member, field: field, row: row };
  }

  function addBuildPeople() {
    /* Rebuilt from the held roster on every mode switch. Ticks and typed shares do
       not survive a switch, which is accepted: keeping them would be state, and this
       screen keeps none. */
    addPeople.replaceChildren();
    addRows = [];
    addHintSome.hidden = addMode !== 'some';
    addHintExact.hidden = addMode !== 'exact';
    if (addRoster === null || addMode === 'equal') {
      return;
    }
    for (var index = 0; index < addRoster.length; index += 1) {
      var built = addPersonRow(addRoster[index]);
      addRows.push(built);
      addPeople.appendChild(built.row);
    }
  }

  function addSetMode(mode) {
    addMode = mode;
    /* All three written explicitly rather than left to the browser's own radio group
       behaviour, so clearing the form after a save really does return the choice to
       Equally rather than only looking as if it had. */
    addModeEqual.checked = mode === 'equal';
    addModeSome.checked = mode === 'some';
    addModeExact.checked = mode === 'exact';
    addBuildPeople();
  }

  function addSplit() {
    var index;
    if (addMode === 'exact') {
      /* Object.create(null), so a member id the payload spelled '__proto__' cannot
         reach through to Object.prototype. Each share is the characters that were
         typed with surrounding whitespace removed and nothing else changed. */
      var amounts = Object.create(null);
      for (index = 0; index < addRows.length; index += 1) {
        var typed = String(addRows[index].field.value).trim();
        if (typed !== '') {
          amounts[addRows[index].member.id] = typed;
        }
      }
      return { mode: 'exact', amounts: amounts };
    }
    /* One API shape covers two of the three modes on screen, and split.py says so in
       its own docstring: equal across everyone and equal across a subset are both
       split_equally over the member list the caller assembles. */
    var memberIds = [];
    if (addMode === 'some') {
      for (index = 0; index < addRows.length; index += 1) {
        if (addRows[index].field.checked) {
          memberIds.push(addRows[index].member.id);
        }
      }
    } else {
      for (index = 0; index < addRoster.length; index += 1) {
        memberIds.push(addRoster[index].id);
      }
    }
    return { mode: 'equal', member_ids: memberIds };
  }

  function addCurtained(error) {
    /* Whether api.js has already put a whole screen in front of this failure: the
       sign-in gate, the not-linked notice, or one of the two paragraphs on the notice
       curtain. This block registers none of those handlers and writes no message of
       its own for any of them, because a second message underneath a curtain nobody
       can see past is a second error contract.

       refused is the one kind that raises no curtain, because it names something
       about this one request rather than about the whole session, and neither request
       this screen makes is one of the two api.js escalates. So it is the only kind
       this screen speaks for.

       Asked of kind rather than of a status. This function used to reconstruct the
       answer from 401, 403 and 500, which is api.js's classification spelled a second
       time in a second file, and two spellings of one decision drift the moment
       either is edited. kind states it outright. It also fixes a case the status
       version got wrong: an answer whose status this client cannot read at all
       returned false here and wrote underneath a curtain. */
    return !error || error.kind !== 'refused';
  }

  function addConfirm(payload) {
    /* The confirmation carries what the server echoed in the 201 body and never what
       was typed, so it says the ledger holds this rather than that the screen tried.
       A body that is not the documented shape is still a success, because the status
       said the expense was recorded: the figure is left empty rather than an error
       claiming a recorded expense did not save. */
    var recorded = payload && typeof payload === 'object' ? payload.expense : null;
    if (!recorded || typeof recorded !== 'object') {
      recorded = null;
    }
    addSavedAmount.textContent =
      recorded !== null && addIsText(recorded.amount) ? recorded.amount : '';
    if (recorded !== null && addIsText(recorded.description) &&
        recorded.description !== '') {
      addSavedDescription.textContent = ' for ' + recorded.description;
    } else {
      /* No description is invented for an expense that has none. */
      addSavedDescription.textContent = '';
    }
    addSavedPanel.hidden = false;
  }

  function addSaved(payload) {
    addConfirm(payload);
    /* Nothing re-hides the errors here: every submit hides all three before it sends,
       and the in-flight flag means nothing can show one while this save is in the air.
       A second clear here would be a line no test could ever falsify. */
    /* Cleared back to its defaults, and the screen deliberately stays on this route.
       Entering three receipts in a row is a real flow, and bouncing to the feed after
       each one costs a tab tap and a re-request every time; this app also navigates
       itself nowhere, by task 8's design. The anchor in the confirmation is how
       somebody who wants stronger proof gets it. */
    addAmount.value = '';
    addDescription.value = '';
    addSetMode('equal');
    addDefaultPayer();
    addAmount.focus();
  }

  function addRefused(error) {
    if (addCurtained(error)) {
      /* Nothing typed is touched either, which is what makes the offline notice's
         standing promise, "nothing you have recorded is lost", true on this screen. */
      return;
    }
    /* The server's own words, verbatim: no rewording, no truncation, no added
       punctuation and no per-code substitution. web.py's messages were written in
       this repo for a person to read. That includes split_exact's refusal, whose
       figures are raw cents against the dollars somebody typed; it is shown as it
       arrived, because the alternatives are inventing replacement copy for one code
       or dividing by a hundred here, and the second is the one thing this codebase
       exists to prevent. Raised as its own issue against split.py. */
    addErrorServer.textContent = (error && error.message) || ADD_SAVE_FAILED;
    addShowError('server');
  }

  function addSubmitted(event) {
    event.preventDefault();
    if (addSaveInFlight) {
      /* This flag is the guard, and the disabled attribute below is an affordance: a
         dispatched submit reaches this handler whatever the control looks like. */
      return;
    }
    /* The confirmation is cleared at the start of every save, and every error with
       it, so nothing on screen belongs to the previous attempt. Never on a timer. */
    addSavedPanel.hidden = true;
    addShowError('');

    var typed = String(addAmount.value).trim();
    if (typed === '') {
      /* Both of this screen's own refusals are checks on whether there is anything to
         send at all, never judgements of an amount. A split with nobody in it, a zero
         total, three decimals and a comma used as a decimal point all go to the
         server as typed and are refused there, because a rule implemented twice is a
         rule that drifts. */
      addShowError('amount');
      addAmount.focus();
      return;
    }
    if (addRoster === null || addRoster.length === 0) {
      addShowError('roster');
      return;
    }

    addSaveInFlight = true;
    addSubmit.disabled = true;
    addSavingLine.hidden = false;

    function settled() {
      addSaveInFlight = false;
      addSubmit.disabled = false;
      addSavingLine.hidden = true;
    }

    /* Exactly four keys, in this order. It never names currency, id, created_at,
       created_by or now: web.py refuses an unrecognised key by name, and all five are
       the server's to decide, which is also why no control here offers a date. */
    api.addExpense({
      description: String(addDescription.value).trim(),
      amount: typed,
      payer_id: addPayer.value,
      split: addSplit()
    }).then(
      function (payload) {
        settled();
        addSaved(payload);
      },
      function (error) {
        settled();
        addRefused(error);
      }
    );
  }

  function addLoadRoster() {
    /* Three guards before anything is read: somebody is signed in and looking at the
       ledger rather than at a curtain, this screen's route is the current one, and no
       read is already running. The helper in the preamble carries the first one and
       says why, and it is what makes the retry control below dead behind a curtain. */
    if (!ledgerIsUp() || window.location.hash !== ADD_ROUTE || addRosterInFlight) {
      return;
    }
    addRosterInFlight = true;
    addRoster = null;
    addPayer.replaceChildren();
    addPeople.replaceChildren();
    addRows = [];
    addRosterState('busy');
    /* The amount and the description are deliberately untouched here and stay usable
       throughout: typing while the roster loads is the whole point. */
    api.members().then(
      function (payload) {
        addRosterInFlight = false;
        if (!addValidRoster(payload)) {
          /* A 200 carrying something other than the documented shape is a failure,
             not an empty group. */
          addRosterState('error');
          return;
        }
        addRoster = payload.members;
        if (addRoster.length === 0) {
          /* Reachable through a half-finished setup_group.py run, which is why the
             balances screen has this state too. */
          addRosterState('empty');
          return;
        }
        addRosterState('');
        addRosterArrived();
        addFillPayer();
        addBuildPeople();
      },
      function () {
        addRosterInFlight = false;
        /* The status code is deliberately not read: a 401, a 403 member_not_linked, a
           network failure and any 5xx are already claimed by the client, which raises
           the gate or one of the two notices over the whole frame. This notice sits
           behind that curtain, where nobody sees it, and it never reads as an empty
           group or as a form that has been thrown away. */
        addRosterState('error');
      }
    );
  }

  /* The one place this screen throws away what somebody typed, and it is called from
     exactly three: entering the route, a resume by somebody who is not the person who
     typed it, and a sign out the server confirmed. A save the server confirmed clears
     the form too, in addSaved(), from the response it was answered with; that is a
     different act and stays where it is. */
  function addCleared() {
    addAmount.value = '';
    addDescription.value = '';
    addSetMode('equal');
    addSavedPanel.hidden = true;
    addShowError('');
  }

  /* Who the amount, the description and the mode below belong to: the member who was
     signed in when this screen was opened. addOpened() is the only writer of it and
     addResumed() the only reader.

     Written on the way in, while somebody is demonstrably signed in and looking at the
     ledger, rather than when a curtain goes up over the draft. By then the answer can
     already be gone: a 401 makes api.js drop its cached session view before showGate()
     is reached, and a 401 on save is the commonest way this curtain ever comes down
     over something typed. Null until this screen has been opened once, which no
     member id ever equals, so a resume before that clears rather than guesses. */
  var addDraftMember = null;

  /* Everything opening this screen does that is true whether the entry is fresh or a
     resumed one: record whose entry it is, say which currency, put the keypad up, read
     the roster. */
  function addOpened() {
    addDraftMember = addActingId();
    addShowCurrency();
    /* Focus moves on to the field, deliberately overriding the heading focus render()
       just made: this is the one screen that does, because the keypad has to be up
       before the roster has even been asked for. The section keeps its
       aria-labelledby, so what is announced is the amount field inside the Add region
       rather than an orphan input. Focus is touched here and nowhere else, and never
       while this is not the current screen or while a curtain is over it. */
    addAmount.focus();
    addLoadRoster();
  }

  function addEntered() {
    /* Navigating here, and the hashchange listener below is the only caller. Every
       such visit starts a fresh entry: the roster is re-read, the picker and the
       people list are rebuilt, the mode returns to Equally and both fields are
       cleared. So a person who taps Feed halfway through loses what they had typed;
       the alternative is a draft that outlives a navigation, which is state, which
       this app keeps nowhere.

       Nothing is kept between visits, and a curtain coming down is not a visit: that
       path is addResumed() below, and what a resume keeps and what it rebuilds from a
       fresh read is written there. */
    if (!ledgerIsUp() || window.location.hash !== ADD_ROUTE) {
      return;
    }
    addCleared();
    addOpened();
  }

  function addResumed() {
    /* A curtain coming down on a screen the person never left, and showApp() is the
       only caller. The hash did not move, so this is not a visit, and for the person
       who typed it nothing is thrown away: the amount, the description and the chosen
       split mode are all still there. That is what makes the offline notice's standing
       promise, "nothing you have recorded is lost", true through signing back in as
       well as through the refusal that raised the curtain.

       What a resume does not keep is what the roster read rebuilds: the ticks, the
       typed shares and a payer picked by hand all go, because addLoadRoster() empties
       the picker and the people rows before it sends. That is deliberate. Rebuilding
       from a fresh read is what keeps the "(you)" marker and the default payer true
       for whoever is signed in now, and on a shared ledger the payer field decides
       who is owed money: a stale "(you)" is a worse failure than a re-ticking. The
       mode is kept for the same reason turned around, since returning Exact to
       Equally would silently turn "these three uneven shares" into "split this
       evenly", which is a wrong ledger entry one tap away. */
    if (!ledgerIsUp() || window.location.hash !== ADD_ROUTE) {
      return;
    }
    /* Kept for the person who typed it and for nobody else. A flat shares phones, and
       the commonest way this curtain goes up is a 401 on save, where nobody signs out:
       Sam types an expense, takes the 401, hands the phone to Ali, and Ali signs in.
       Without this, Sam's amount and description are still on screen, and the picker
       the roster read rebuilds has helpfully named Ali as the payer of them, so one
       tap on Save records Sam's expense against Ali. Asking who is coming back is the
       direct question. "Did a sign out succeed", which the sign out handler below
       answers, is a proxy for it that misses this path entirely, and this path is the
       one this screen exists to survive. */
    if (addActingId() !== addDraftMember) {
      addCleared();
    }
    addOpened();
  }

  addForm.addEventListener('submit', addSubmitted);

  /* Re-issues the read and returns to the in-flight state while it runs, and leaves
     the typed amount and description exactly where they are: a retry is not a fresh
     entry. */
  addRosterRetry.addEventListener('click', function () {
    addLoadRoster();
  });

  /* One listener per radio, each naming its own mode, so nothing here scans the three
     to discover which is checked and nothing relies on an event bubbling out of a
     container. */
  addModeEqual.addEventListener('change', function () {
    addSetMode('equal');
  });
  addModeSome.addEventListener('change', function () {
    addSetMode('some');
  });
  addModeExact.addEventListener('change', function () {
    addSetMode('exact');
  });

  /* This block listens for its own route rather than editing render(), which both
     sibling branches also need. Registered after the router's listener, so the router
     renders the screen first and this moves focus on afterwards. */
  window.addEventListener('hashchange', addEntered);


  /* --- The gate ---------------------------------------------------------- */

  var gate = document.getElementById('gate');
  var notice = document.getElementById('notice');
  var frame = document.querySelector('.content');
  var tabbar = document.querySelector('.tabbar');
  var signOut = document.getElementById('sign-out');
  var gateForm = document.getElementById('gate-form');
  var gateEmail = document.getElementById('gate-email');
  var gatePassword = document.getElementById('gate-password');
  var gateSubmit = document.getElementById('gate-submit');
  var gateTitle = document.getElementById('gate-title');
  var gateError = document.getElementById('gate-error');
  var gateMode = document.getElementById('gate-mode');
  var noticeUnlinked = document.getElementById('notice-unlinked');
  var noticeOffline = document.getElementById('notice-offline');
  var noticeNotKept = document.getElementById('notice-not-kept');
  var noticeProblem = document.getElementById('notice-problem');
  var creating = false;
  /* What show() last applied, and nothing else ever assigns it. Undefined until the
     first call, which reads as "not the app frame" and is right: nothing has been
     drawn yet. The preamble's helper reads it back. */
  var showing;

  function show(which) {
    /* One of 'app', 'gate' or 'notice'. The hash is never touched: signing in
       returns the user to the screen they were already on.

       Which one it applied is recorded, because whether the app frame is up is a
       decision this file makes and the preamble's helper should read it back as a
       decision. Deriving it from .content.hidden would work today and would be this file
       re-reading the markup it had just written. */
    showing = which;
    gate.hidden = which !== 'gate';
    notice.hidden = which !== 'notice';
    if (frame) {
      frame.hidden = which !== 'app';
    }
    if (tabbar) {
      tabbar.hidden = which !== 'app';
    }
  }

  function showGate(message) {
    gateError.textContent = message || '';
    gateError.hidden = !message;
    signOut.hidden = true;
    show('gate');
    gateTitle.focus();
  }

  function showNotice(which, message) {
    /* The one function that hides all four paragraphs and shows one, so exactly one
       of them is ever visible. It is also the only thing that ever calls
       show('notice'), which is what makes that true: nothing resets these four flags
       when the gate or the app frame replaces the curtain, so the paragraph that was
       up stays flagged underneath a hidden #notice. That is invisible and harmless
       only for as long as every route back to a raised #notice comes through here and
       sets all four again. Raise the curtain from anywhere else and two paragraphs
       show at once. #notice-problem is the only one whose text is written
       here, and it is cleared whenever it is not the paragraph being shown, so a
       sentence from an earlier failure is never left sitting behind a later one.
       The sentence goes in as text and no markup is ever parsed, so a message
       holding < renders as that character rather than as the start of a tag. */
    noticeUnlinked.hidden = which !== 'unlinked';
    noticeOffline.hidden = which !== 'offline';
    noticeNotKept.hidden = which !== 'not-kept';
    noticeProblem.hidden = which !== 'problem';
    noticeProblem.textContent = which === 'problem' ? message : '';
    show('notice');
    document.getElementById('notice-title').focus();
  }

  function showApp() {
    signOut.hidden = false;
    /* Before the three calls, never after: each of them asks the preamble's helper,
       which asks what this just applied. */
    show('app');
    /* The feed and the balances screens hold nothing typed, so entry and resume are
       the same act for them, and re-reading is right because their figures may be
       stale after the interruption. The add screen resumes rather than being entered:
       the hash never moved, so this is not a visit, and what was typed stays. */
    loadFeed();
    balancesEntered();
    addResumed();
  }

  function setMode(toCreating) {
    creating = toCreating;
    gateTitle.textContent = creating ? 'Create an account' : 'Sign in';
    gateSubmit.textContent = creating ? 'Create account' : 'Sign in';
    gateMode.textContent = creating
      ? 'I already have an account'
      : 'Create an account';
    /* So a password manager offers to save a new secret rather than to fill an
       old one. */
    gatePassword.setAttribute(
      'autocomplete',
      creating ? 'new-password' : 'current-password'
    );
  }

  function refresh() {
    return api.session().then(
      function (view) {
        if (view && view.member) {
          showApp();
        } else {
          signOut.hidden = false;
          showNotice('unlinked');
        }
      },
      function () {
        /* Already reported through one of the three handlers below. */
      }
    );
  }

  function submitted(event) {
    event.preventDefault();
    var email = gateEmail.value.trim();
    var password = gatePassword.value;
    gateError.hidden = true;
    gateSubmit.disabled = true;
    var started = creating
      ? api
          .signUp(email, email, password)
          .then(function () {
            return api.signIn(email, password);
          })
      : api.signIn(email, password);
    started
      .then(function () {
        gatePassword.value = '';
        setMode(false);
        return refresh();
      })
      .catch(function (error) {
        if (!error || (error.kind !== 'signed-out' && error.kind !== 'refused')) {
          /* Every other kind has already pulled a curtain over the whole frame, and
             the gate deliberately is not up, so writing on it here would drag it back
             over that notice. Which kind it is, is api.js's decision: this screen
             reads the answer and never a status code. */
          return;
        }
        /* Everything else is something the person can act on, a wrong password most
           of all. The 401 handler has just re-shown the gate with whatever api.js
           decided was worth reading, so this runs after it and is what they actually
           read.

           say and not message, which is what every other screen prints: they differ
           only where api.js decided the server's sentence describes a situation the
           person is not in, and printing it there anyway would be this screen
           overruling the one place that gets to decide. The fallback is the gate's
           own, for a refusal whose body carried nothing at all. */
        gateError.textContent = error.say || 'That did not work.';
        gateError.hidden = false;
        show('gate');
      })
      .then(function () {
        gateSubmit.disabled = false;
      });
  }

  function wire() {
    api.onUnauthenticated(function (error) {
      /* Whatever api.js decided is worth reading, which is the server's own sentence
         for a session that died and nothing at all for a first visit. This screen
         prints what it is handed and writes no sentence of its own. */
      showGate(error.say);
    });
    api.onNotLinked(function () {
      signOut.hidden = false;
      showNotice('unlinked');
    });
    api.onOffline(function (error) {
      /* Never the sign-in gate: prompting for a password on a page that cannot
         send it is how a person types their password into nothing, repeatedly.

         Which of the three paragraphs goes up is read from kind, in this one place.
         No status code is read here, and none may be: api.js is the only file that
         classifies a response. */
      if (error.kind === 'sign-in-not-kept') {
        showNotice('not-kept');
      } else if (error.kind !== 'offline' && error.say) {
        showNotice('problem', error.say);
      } else {
        /* Nothing came back, or what came back carried nothing to read. The standing
           sentence says more than a blank curtain would. */
        showNotice('offline');
      }
    });
    gateForm.addEventListener('submit', submitted);
    gateMode.addEventListener('click', function () {
      setMode(!creating);
      gateEmail.focus();
    });
    signOut.addEventListener('click', function () {
      api.signOut().then(
        function () {
          setMode(false);
          /* A visit that really ended is the strongest signal there is that the next
             person at this phone is not the previous one, and a flat shares phones.
             Without this, Sam types an expense, signs out, and Ali signs in to find
             Sam's amount and description sitting in the form with Ali named as the
             payer. Whatever route is current: the draft belongs to the person who
             typed it, not to the screen. A sign out the server refused clears
             nothing, because that visit did not end. */
          addCleared();
          showGate('');
        },
        function () {}
      );
    });
    setMode(false);
    refresh();
  }

  /* The document loads one script, and it is this one. The client is a second
     file rather than inlined text, so it stays independently readable and cacheable
     and the network chokepoint is one file a reviewer can open. This file never
     names the network API itself: that is api.js's whole job. */
  var client = document.createElement('script');
  client.src = 'api.js';
  client.onload = function () {
    api = window.SplitwiseApi;
    wire();
  };
  client.onerror = function () {
    showNotice('offline');
  };
  document.head.appendChild(client);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function (error) {
        console.warn(
          'Splitwise Lite: the service worker did not register, so the app will ' +
            'not open offline. Everything else still works.',
          error
        );
      });
    });
  }

  /* --- The balances screen ------------------------------------------------

     Who owes who, in the fewest payments. Both lists are read from the API on every
     entry to the route and rendered from strings the server already formatted.
     Nothing derived is kept: balances are folded out of the event log on every read
     and never stored, and a figure held over from a previous visit is the spec's
     "authoritative while being wrong" failure in miniature.

     This region fills one section and reaches past it for nothing. It registers none
     of the three global failure handlers: a 401, a 403 member_not_linked and a
     request that got no answer are the client's, and their three screens are task
     9a's, reused unchanged. What is left over, a 404 or a body that will not parse,
     is this screen's own one-line failure message.

     Task 13 made a transfer row a disclosure. It opens on the pairwise debts that
     payment absorbed, from both ends, and each of those debts opens in turn on the
     expenses and confirmed settlements behind it. That second read is the one lazy
     thing here: one request per debt row, on its first expansion and never before.
     A transfer whose payload carries no usable provenance is drawn exactly as task
     12 drew it, inert, because nothing may look tappable before the data is
     there. */

  var BALANCES_ROUTE = '#/balances';
  /* A member id is an opaque string and means nothing to a flatmate, so no id is
     ever rendered. A row whose member is missing from the roster still renders under
     this name: hiding money because a name is missing is the worse failure. */
  var UNKNOWN_MEMBER = 'Unknown member';
  /* The acting member is marked, never renamed to "You". Two flatmates read this
     list off one phone, and a row that means different things depending on who is
     holding the phone is worse than a list of names. */
  var ACTING_SUFFIX = ' (you)';

  /* The three sentences a debt's own status line can hold, and never anything else.
     They are composed here rather than shipped in index.html because they belong to
     a row, and a per-row sentence cannot live in markup; task 9b's harness pins what
     is rendered, which is a stronger check than a substring in a source file. */
  var BALANCES_WAITING = 'Looking up the expenses behind this.';
  /* One sentence for every one of the six kinds api.js classifies. The screen reads
     no status, no code and no kind, and never error.say: the only kind that carries
     a server sentence here is a refusal, and the sentence this route composes for
     its own 400 names a member id, which this screen may never show as text. */
  var BALANCES_FAILED = 'Those expenses could not be listed just now.';
  /* An empty list of entries is a valid answer and not a failure: the ledger can
     move between the balances read and this request. */
  var BALANCES_NOTHING = 'Nothing is recorded behind this debt.';

  /* Task 14's sentences, composed here for the same reason the three above are: they
     belong to a row, and a per-row sentence cannot live in markup. The fixed prose
     the whole screen shows once is in index.html, where a Python test pins it. */
  var BALANCES_MARK = 'Mark as paid';
  var BALANCES_RECORDING = 'Recording this payment.';
  /* One sentence for every one of api.js's six kinds, and never error.say. Every
     refusal this endpoint can produce names a member id, describes a body the person
     did not type, or describes a claim they cannot see from here, and a member id may
     never be rendered as visible text on this screen. Imprecise when the true answer
     is that another device got there first, and never wrong in the dangerous
     direction: it never claims something was recorded that was not, and leaving the
     screen and returning shows the truth from the server. */
  var BALANCES_NOT_RECORDED = 'That was not recorded.';
  /* Shown instead of a button on a payment somebody has already claimed, whoever is
     holding the phone. This is the up-front guard against a second claim, which is
     what makes the server's 409 a race guard rather than the normal path. */
  var BALANCES_AWAITING = 'Marked as paid, and not confirmed yet.';

  /* Every detail region needs an id for its button's aria-controls. It comes from a
     sequence number and never from the two member ids: task 12 decided the renderer
     does not assume a pair appears at most once, and two rows naming one pair must
     not produce two elements carrying one id. Never reset, so an id cannot be handed
     out twice while an older node is still in the document. */
  var balancesRegions = 0;

  var netList = document.getElementById('balances-net');
  var transferList = document.getElementById('balances-transfers');
  var currencyLine = document.getElementById('balances-currency');
  var currencyCode = document.getElementById('balances-currency-code');
  var balancesBusy = document.getElementById('balances-busy');
  var balancesError = document.getElementById('balances-error');
  var balancesNone = document.getElementById('balances-none');
  var balancesEmptyRoster = document.getElementById('balances-empty-roster');
  var drillHint = document.getElementById('balances-drill-hint');
  /* One wrapper and the list inside it. The wrapper carries the hidden flag, so the
     heading, the note and the list are shown together or not at all. */
  var pendingBlock = document.getElementById('balances-pending-block');
  var pendingList = document.getElementById('balances-pending');

  /* Which attempt is allowed to draw. Bumped whenever one starts, so an answer from
     a visit the user has already left is discarded rather than drawn over the newer
     one. A sequence number, not a cache: nothing derived survives a navigation. */
  var balancesAttempt = 0;

  function balancesMessage(shown) {
    /* At most one of the four is ever visible, so the screen never says two things
       at once. Every fixed sentence lives in index.html; this only toggles hidden. */
    balancesBusy.hidden = shown !== 'busy';
    balancesError.hidden = shown !== 'error';
    balancesNone.hidden = shown !== 'none';
    balancesEmptyRoster.hidden = shown !== 'empty-roster';
  }

  function balancesEmpty(list) {
    while (list.firstChild) {
      list.removeChild(list.firstChild);
    }
    list.hidden = true;
  }

  function balancesClear() {
    balancesEmpty(netList);
    balancesEmpty(transferList);
    currencyLine.hidden = true;
    currencyCode.textContent = '';
    /* So neither an open drill-down nor the hint that rows can be opened can survive
       a refresh or sit beside a failure message. */
    drillHint.hidden = true;
    /* And so no claim from a previous visit sits beside "These figures could not be
       worked out just now.", or survives into a read that no longer carries it. */
    balancesEmpty(pendingList);
    pendingBlock.hidden = true;
  }

  function balancesRegionId() {
    balancesRegions += 1;
    return 'balances-detail-' + balancesRegions;
  }

  function balancesText(tag, className, value) {
    /* This region's own three line builder rather than feedText. A date spelling is
       a product rule that must not be duplicated, which is why feedDate is called
       across the region boundary; a three line element builder is not, and keeping
       the boundary is what makes a merge with another screen's branch trivial. */
    var node = document.createElement(tag);
    node.className = className;
    node.textContent = value;
    return node;
  }

  function balancesFigure(amount) {
    /* The amount is a string the server formatted and it goes in exactly as it
       arrived: nothing rounded, no separator added or removed, no symbol prepended.
       It gets its own element only so that it can be kept whole when a row wraps. */
    var figure = document.createElement('span');
    figure.className = 'balances-figure';
    figure.textContent = amount;
    return figure;
  }

  function balancesActingId() {
    /* Matched on member_id against the session view the client already holds, so
       marking the acting member costs no extra round trip. A missing session view,
       or one whose member is null because nobody has linked the account, marks
       nothing and breaks nothing else on the screen. */
    var view = api.cachedSession();
    if (view && view.member && view.member.id) {
      return view.member.id;
    }
    return null;
  }

  function balancesName(memberId, names, actingId) {
    var name = Object.prototype.hasOwnProperty.call(names, memberId)
      ? names[memberId]
      : UNKNOWN_MEMBER;
    if (actingId && memberId === actingId) {
      return name + ACTING_SUFFIX;
    }
    return name;
  }

  function balancesNetRow(entry, names, actingId) {
    var row = document.createElement('li');
    row.className = 'balances-row';
    var line = document.createElement('span');
    line.className = 'balances-line';
    /* Every server string reaches the DOM as text, so a display name holding a
       `<`, an `&` or a quote renders as those characters and is never markup. */
    line.appendChild(
      document.createTextNode(balancesName(entry.member_id, names, actingId))
    );
    /* The verb comes from `direction` and from nothing else. `amount` is always the
       non-negative magnitude and the sign is carried separately for exactly this
       reason, so the screen never compares an amount against a zero, measures it or
       converts it to a number. */
    if (entry.direction === 'owes') {
      line.appendChild(document.createTextNode(' owes '));
      line.appendChild(balancesFigure(entry.amount));
    } else if (entry.direction === 'owed') {
      line.appendChild(document.createTextNode(' is owed '));
      line.appendChild(balancesFigure(entry.amount));
    } else if (entry.direction === 'settled') {
      /* No amount at all. A zero beside a name is a figure a reader has to
         interpret; "is settled up" is the answer they came for. The payload still
         carries the magnitude, and the screen still ignores it. */
      line.appendChild(document.createTextNode(' is settled up'));
    } else {
      /* A direction nobody expected still shows the name and the figure, with no
         verb. One odd row must not blank the screen. */
      line.appendChild(document.createTextNode(' '));
      line.appendChild(balancesFigure(entry.amount));
    }
    row.appendChild(line);
    return row;
  }

  function balancesIsText(value) {
    return typeof value === 'string';
  }

  function balancesAbsorbed(row) {
    /* "Usable provenance", exactly and nothing looser: every field a debt row
       renders is a string, and the flag that decides that row's wording is present.
       A row built from a missing field would print a blank or an "undefined" beside
       real money, which is the authoritative-while-wrong failure in miniature. */
    return (
      row !== null &&
      typeof row === 'object' &&
      balancesIsText(row.debtor_id) &&
      balancesIsText(row.creditor_id) &&
      balancesIsText(row.amount) &&
      balancesIsText(row.debt_total) &&
      Object.prototype.hasOwnProperty.call(row, 'covers_whole_debt')
    );
  }

  function balancesAbsorbedList(rows) {
    if (!Array.isArray(rows) || rows.length === 0) {
      return false;
    }
    for (var index = 0; index < rows.length; index += 1) {
      if (!balancesAbsorbed(rows[index])) {
        return false;
      }
    }
    return true;
  }

  function balancesOpenable(transfer) {
    /* Both ends or neither. A payment raises two questions with different answers,
       "why am I paying at all, and why this much" and "why them, when I have never
       bought anything with them"; payer_debts answers the first and only
       receiver_credits can answer the second. A row that could answer only half of
       it stays inert rather than answering half of it. */
    return (
      transfer !== null &&
      typeof transfer === 'object' &&
      balancesAbsorbedList(transfer.payer_debts) &&
      balancesAbsorbedList(transfer.receiver_credits)
    );
  }

  function balancesAnyOpenable(transfers) {
    for (var index = 0; index < transfers.length; index += 1) {
      if (balancesOpenable(transfers[index])) {
        return true;
      }
    }
    return false;
  }

  function balancesShape(transfer) {
    /* Decided from the ids alone. No amount is compared, measured, parsed or
       converted to choose what a payment says: two figures that happen to be equal
       say nothing about whether a payment is direct, and the front end does no money
       arithmetic at any level of this screen. */
    var payer = transfer.payer_debts;
    var credits = transfer.receiver_credits;
    if (
      payer.length === 1 &&
      credits.length === 1 &&
      payer[0].debtor_id === credits[0].debtor_id &&
      payer[0].creditor_id === credits[0].creditor_id
    ) {
      /* One debt straight between the two people, which task 5's "direct debt first"
         rule guarantees. Two labelled lists holding the same single row read as a
         bug, so this shape collapses to one list under one sentence. */
      return 'direct';
    }
    for (var index = 0; index < payer.length; index += 1) {
      if (payer[index].creditor_id === transfer.to_member_id) {
        return 'mixed';
      }
    }
    /* No debt at all between the payer and the receiver: the case this whole task
       exists for, and the one that has to say so in words. */
    return 'through';
  }

  function balancesEffectLine(entry, debtorName, creditorName) {
    /* Which way an entry moved this debt, in words, taken from the server's own
       effect and from nothing else. No sign, colour or minus carries it:
       format_amount produces no minus and web.py sends magnitudes. */
    if (entry.kind === 'expense') {
      if (entry.effect === 'adds') {
        return 'Adds to this debt: ' + creditorName + ' paid, and ' + debtorName +
          ' shared';
      }
      if (entry.effect === 'reduces') {
        return 'Takes off this debt: ' + debtorName + ' paid, and ' + creditorName +
          ' shared';
      }
    } else if (entry.kind === 'settlement') {
      if (entry.effect === 'reduces') {
        return 'Takes off this debt: ' + debtorName + ' paid ' + creditorName;
      }
      if (entry.effect === 'adds') {
        return 'Adds to this debt: ' + creditorName + ' paid ' + debtorName;
      }
    }
    /* A kind or an effect nobody expected still shows the entry and its date, with
       no sentence claiming which way it moved the debt. One odd entry must not blank
       the list, and inventing a direction for it would be worse than saying
       nothing. */
    return null;
  }

  function balancesEntryRow(entry, debtorName, creditorName) {
    var item = document.createElement('li');
    item.className = 'balances-entry';

    var first = document.createElement('span');
    first.className = 'balances-entry-line';
    var described;
    if (entry.kind === 'settlement') {
      /* A settlement always carries an empty description on the wire, because
         SettlementEvent has none and balances.py refuses to mix a sentence this repo
         wrote into a list of what people actually recorded. Naming it is this
         screen's job, and kind decides that before the description is looked at. */
      described = 'A settlement';
    } else {
      described = String(entry.description).trim();
      if (described === '') {
        /* The same literal the feed uses, and never a summary invented from the
           other fields. */
        described = 'No description';
      }
    }
    first.appendChild(balancesText('span', 'balances-entry-description', described));
    first.appendChild(balancesFigure(entry.amount));
    item.appendChild(first);

    var effect = balancesEffectLine(entry, debtorName, creditorName);
    if (effect !== null) {
      item.appendChild(balancesText('span', 'balances-entry-effect', effect));
    }

    /* feedDate rather than a second parser: one ledger has one date spelling. The
       raw instant survives in the markup even though the visible text is a day. */
    var stamp = balancesText(
      'time',
      'balances-entry-date',
      feedDate(entry.created_at)
    );
    stamp.setAttribute('datetime', entry.created_at);
    item.appendChild(stamp);
    return item;
  }

  function balancesValidEntry(entry) {
    return (
      entry !== null &&
      typeof entry === 'object' &&
      balancesIsText(entry.kind) &&
      balancesIsText(entry.effect) &&
      balancesIsText(entry.id) &&
      balancesIsText(entry.description) &&
      balancesIsText(entry.created_at) &&
      balancesIsText(entry.amount)
    );
  }

  function balancesValidDebt(payload) {
    /* A 200 that is not the documented shape takes the failure path and never the
       empty one: "nothing is recorded behind this debt" is a claim about the ledger,
       and a payload this screen could not read is no evidence for it. */
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.entries)) {
      return false;
    }
    for (var index = 0; index < payload.entries.length; index += 1) {
      if (!balancesValidEntry(payload.entries[index])) {
        return false;
      }
    }
    return true;
  }

  function balancesDebtRow(row, names, actingId) {
    var item = document.createElement('li');
    item.className = 'balances-debt';
    var debtorName = balancesName(row.debtor_id, names, actingId);
    var creditorName = balancesName(row.creditor_id, names, actingId);

    var region = document.createElement('div');
    region.className = 'balances-debt-detail';
    region.id = balancesRegionId();
    region.hidden = true;

    var status = document.createElement('p');
    status.className = 'balances-entry-status';
    status.setAttribute('role', 'status');
    region.appendChild(status);

    /* The entry list is the status line's sibling and never its child, so a reader
       hearing the live region hears one sentence rather than every arriving entry.
       It stays hidden until there is something in it: an empty region is never
       shown. */
    var list = document.createElement('ul');
    list.className = 'balances-entries';
    list.hidden = true;
    region.appendChild(list);

    var indicator = balancesText('span', 'balances-indicator', '+');
    indicator.setAttribute('aria-hidden', 'true');

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'balances-debt-button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', region.id);

    var line = document.createElement('span');
    line.className = 'balances-line';
    line.appendChild(
      document.createTextNode(debtorName + ' owes ' + creditorName + ' ')
    );
    line.appendChild(balancesFigure(row.amount));
    if (row.covers_whole_debt !== true) {
      /* One strict equality and nothing else. The clause states two figures the
         server sent and claims nothing of its own; dropping it claims the payment
         clears the whole debt, which a garbled flag has not earned. The whole total
         is on the row because one debt can be split across two payments, and both
         halves read wrongly alone, and a reader who saw two portions and no whole
         would add them up into a debt that does not exist. */
      line.appendChild(document.createTextNode(' of '));
      line.appendChild(balancesFigure(row.debt_total));
    }
    button.appendChild(line);
    button.appendChild(indicator);

    /* Both live in this row's own closure, so an answer to a request this row made
       is written into this row and nowhere else, even when the list has been rebuilt
       underneath it and this node is no longer in the document. Not a cache: the
       whole list is rebuilt on every entry to the route, nothing is held in a module
       variable between visits and nothing reaches storage of any kind. */
    var answered = false;
    var asking = false;

    button.addEventListener('click', function () {
      /* The same question the feed and the add retries ask, through the same shared
         helper rather than a fourth copy of it. Behind a curtain nothing toggles,
         nothing is asked and nothing is written. */
      if (!ledgerIsUp()) {
        return;
      }
      var open = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', open ? 'false' : 'true');
      region.hidden = open;
      indicator.textContent = open ? '+' : '-';
      if (open || answered || asking) {
        /* A row that answered keeps its entries in its own DOM and asks nothing
           further. A row whose request failed kept nothing, so re-expanding it asks
           again rather than showing an old sentence about a live ledger. */
        return;
      }
      asking = true;
      /* The reveal comes first, then aria-busy, then the sentence, and only then the
         request: a live region whose text changed while it was hidden announces
         nothing in several screen readers. */
      region.setAttribute('aria-busy', 'true');
      status.textContent = BALANCES_WAITING;
      /* The one request this task makes, on the first expansion of this row and
         never before. Not on entering the route, not when the payment above it
         opens, not for a row nobody opened: that would multiply this screen's two
         reads by the size of the plan to answer a question nobody asked. */
      api.debt(row.debtor_id, row.creditor_id).then(
        function (payload) {
          asking = false;
          region.removeAttribute('aria-busy');
          if (!balancesValidDebt(payload)) {
            status.textContent = BALANCES_FAILED;
            return;
          }
          answered = true;
          if (payload.entries.length === 0) {
            status.textContent = BALANCES_NOTHING;
            return;
          }
          /* In the order the server sent them, newest first, and nothing here sorts
             or reverses: all ordering on this screen is the server's. The payload's
             own top-level amount and direction are read by nothing, because these
             are two reads of a ledger that may have moved in between, and splicing a
             fresher pair total into a row built from an older read would make one
             row disagree with itself. */
          for (var index = 0; index < payload.entries.length; index += 1) {
            list.appendChild(
              balancesEntryRow(payload.entries[index], debtorName, creditorName)
            );
          }
          list.hidden = false;
          status.textContent = '';
          status.hidden = true;
        },
        function () {
          asking = false;
          region.removeAttribute('aria-busy');
          /* One sentence, for every one of the six kinds. Five of them put a curtain
             over the frame this row sits under, which is api.js's doing and not this
             screen's; writing into a row nobody can see is harmless and keeps this
             one path. A drill-down that failed is one row's failure, so
             #balances-error stays hidden and the payment above stays open. */
          status.textContent = BALANCES_FAILED;
        }
      );
    });

    item.appendChild(button);
    item.appendChild(region);
    return item;
  }

  function balancesDebtListNode(rows, names, actingId) {
    /* Every absorbed debt, in the order the array arrived. Nothing is truncated,
       capped, hidden behind a "show more" or reduced to the largest few: a debt left
       off the list is a cent of a real payment left unexplained. A transfer being
       larger than every single debt it absorbs is routine, and nothing here presents
       that as odd. */
    var list = document.createElement('ul');
    list.className = 'balances-debt-list';
    for (var index = 0; index < rows.length; index += 1) {
      list.appendChild(balancesDebtRow(rows[index], names, actingId));
    }
    return list;
  }

  function balancesTransferDetail(transfer, names, actingId) {
    var detail = document.createElement('div');
    detail.className = 'balances-transfer-detail';
    detail.id = balancesRegionId();
    /* Built eagerly and hidden, exactly as feedDetail is. Opening toggles hidden and
       nothing else, which keeps the handler two lines, costs no request, and puts
       every live region in the document before it is ever revealed, which is what a
       live region needs. Only the request behind a debt is lazy. */
    detail.hidden = true;

    var payer = balancesName(transfer.from_member_id, names, actingId);
    var receiver = balancesName(transfer.to_member_id, names, actingId);
    var shape = balancesShape(transfer);

    if (shape === 'direct') {
      detail.appendChild(balancesText(
        'p',
        'balances-shape-note',
        'This payment settles what ' + payer + ' owes ' + receiver + ' directly.'
      ));
      detail.appendChild(balancesDebtListNode(transfer.payer_debts, names, actingId));
      return detail;
    }
    if (shape === 'through') {
      detail.appendChild(balancesText(
        'p',
        'balances-shape-note',
        payer + ' and ' + receiver + ' have not shared an expense. These are the ' +
          'debts on each side of this payment.'
      ));
    }
    /* Both ends, each under a label naming whose end it is. A drill-down that
       renders payer_debts and stops is wrong in exactly the case this task exists
       for: it never answers "why them". */
    detail.appendChild(
      balancesText('p', 'balances-debt-label', 'What ' + payer + ' owes')
    );
    detail.appendChild(balancesDebtListNode(transfer.payer_debts, names, actingId));
    detail.appendChild(
      balancesText('p', 'balances-debt-label', 'What ' + receiver + ' is owed')
    );
    detail.appendChild(
      balancesDebtListNode(transfer.receiver_credits, names, actingId)
    );
    /* Each list independently accounts for the whole payment, so a reader seeing
       10.50 under one label and 10.50 under the other can conclude they owe 21.00.
       The screen states that they are one payment seen twice; it does not compute
       it, and it adds neither list up. */
    detail.appendChild(balancesText(
      'p',
      'balances-shape-note',
      'The same payment seen from each end. These are not two payments.'
    ));
    return detail;
  }

  function balancesValidPending(view) {
    /* Exactly the fields a pending row renders, every one of them a string, and the
       state by one strict equality against 'pending'. Strict, because task 15 widens
       this list with decided settlements, and a looser test would let this screen
       label a rejected claim as awaiting somebody. A row that fails is left out and
       the rest of the list still renders: one unreadable row must not hide a real
       claim. */
    return (
      view !== null &&
      typeof view === 'object' &&
      balancesIsText(view.id) &&
      balancesIsText(view.from_member_id) &&
      balancesIsText(view.to_member_id) &&
      balancesIsText(view.amount) &&
      balancesIsText(view.created_at) &&
      view.state === 'pending'
    );
  }

  function balancesPendingRow(view, names, actingId) {
    /* The one function that takes one pending view and returns one row. Two children,
       a line and a date, so task 15 can append its confirm and reject controls as a
       third without unpicking either, exactly as this task appended a third to a
       transfer row. */
    var row = document.createElement('li');
    row.className = 'balances-pending';
    /* Attributes only, never rendered as text. No settlement id and no member id is
       ever visible on this screen, in any state; task 15 finds the claim to answer
       through these three. */
    row.setAttribute('data-settlement', view.id);
    row.setAttribute('data-from', view.from_member_id);
    row.setAttribute('data-to', view.to_member_id);

    /* The same sentence on every phone, differing only in where ` (you)` falls, which
       is task 12's rule: a row that means different things depending on who is
       holding the phone is worse than a list of names. */
    var line = document.createElement('span');
    line.className = 'balances-pending-line';
    line.appendChild(
      document.createTextNode(
        balancesName(view.from_member_id, names, actingId) + ' marked '
      )
    );
    line.appendChild(balancesFigure(view.amount));
    line.appendChild(
      document.createTextNode(
        ' as paid to ' + balancesName(view.to_member_id, names, actingId) + '.'
      )
    );
    row.appendChild(line);

    /* feedDate rather than a second parser: one ledger has one date spelling, and
       nothing here derives anything from it. How long a claim has been waiting is
       task 16's signal, not this screen's. */
    var stamp = balancesText(
      'time',
      'balances-pending-date',
      feedDate(view.created_at)
    );
    stamp.setAttribute('datetime', view.created_at);
    row.appendChild(stamp);
    return row;
  }

  function balancesPendingAdd(view, names, actingId) {
    /* The one place anything is put into this list, so the row a read draws and the
       row a fresh 201 appends cannot drift apart. Revealing the block here is what
       makes "shown only when at least one row was rendered" true by construction. */
    if (!balancesValidPending(view)) {
      return false;
    }
    pendingList.appendChild(balancesPendingRow(view, names, actingId));
    pendingList.hidden = false;
    pendingBlock.hidden = false;
    return true;
  }

  function balancesPendingFill(rows, names, actingId) {
    /* In the order the array arrived, which the server sends oldest first: the claim
       that has been waiting longest is the one that needs chasing. Nothing here
       sorts, reverses or filters by anything but readability, and an absent or
       non-array `pending` is an older server, which is a screen without the block
       rather than a broken one. */
    if (!Array.isArray(rows)) {
      return;
    }
    for (var index = 0; index < rows.length; index += 1) {
      balancesPendingAdd(rows[index], names, actingId);
    }
  }

  function balancesActionRegion(transfer, names, actingId) {
    /* The third child of an openable transfer row, present in exactly two cases and
       absent otherwise, so a row nobody can act on is byte for byte what task 13
       rendered. Appended rather than inserted, so childNodes[0] is still the
       disclosure button and childNodes[1] is still its region, visual order still
       equals DOM order, and the control that records money comes after the
       explanation of the payment rather than before it. */
    if (transfer.awaiting_confirmation === true) {
      /* Whoever is acting, the payer included: a payment already claimed says so
         instead of offering to claim it again. */
      var claimed = document.createElement('div');
      claimed.className = 'balances-action';
      claimed.appendChild(
        balancesText('span', 'balances-awaiting', BALANCES_AWAITING)
      );
      return claimed;
    }
    if (!actingId || transfer.from_member_id !== actingId) {
      /* Nobody is offered a control they could not use, and an account nobody has
         linked has no acting id at all, so no row matches. */
      return null;
    }

    var region = document.createElement('div');
    region.className = 'balances-action';
    var payer = balancesName(transfer.from_member_id, names, actingId);
    var receiver = balancesName(transfer.to_member_id, names, actingId);

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'balances-mark-button';
    button.appendChild(document.createTextNode(BALANCES_MARK));
    /* The visible label first, then the payment, so somebody listing the buttons on a
       screen with three payments hears three different names and the visible label is
       contained in the accessible one. The receiver here is never the acting member,
       because this control is only offered to the payer. */
    button.setAttribute(
      'aria-label',
      BALANCES_MARK + ': ' + payer + ' pays ' + receiver + ' ' + transfer.amount
    );

    /* In the document from the start and never hidden, because a live region whose
       text changed while it was hidden announces nothing in several screen readers.
       It ships empty and its rule gives it no height, so it takes no space until
       there is something to say. */
    var status = document.createElement('p');
    status.className = 'balances-action-status';
    status.setAttribute('role', 'status');
    status.textContent = '';

    region.appendChild(button);
    region.appendChild(status);

    /* Both live in this row's own closure, so two payable rows on one screen each
       have their own, and marking one changes nothing about the other. The flag is
       the real double-submission guard and `disabled` is set beside it for the
       browser: a handler dispatched straight at the listener never consults the
       attribute, so a guard living only there would be asserted nowhere. */
    var asking = false;
    var recorded = false;

    button.addEventListener('click', function () {
      /* The same question the feed retry, the add retry and both disclosure handlers
         ask, through the same shared helper rather than a fifth copy of it. Behind a
         curtain nothing is asked, nothing is disabled and nothing is written. */
      if (!ledgerIsUp()) {
        return;
      }
      if (asking || recorded) {
        return;
      }
      button.disabled = true;
      asking = true;
      /* Task 12's sequence number, captured before the request. Without it an answer
         arriving after the user left and came back would append a row to a list the
         second read has already filled from the server, duplicating the claim. The
         status line below needs no such guard: it writes into this row's own DOM. */
      var attempt = balancesAttempt;
      /* Written before the request goes out, so the announcement is already on screen
         at the moment the call is made rather than after it comes back. */
      region.setAttribute('aria-busy', 'true');
      status.textContent = BALANCES_RECORDING;
      api.addSettlement(transfer.to_member_id, transfer.amount).then(
        function (payload) {
          region.removeAttribute('aria-busy');
          recorded = true;
          /* Disabled rather than removed, and the row is never re-rendered: removing
             or disabling the element that has focus moves focus to the body, and this
             screen calls focus() nowhere. Disabling is unavoidable, because a
             live-looking control that records nothing is worse; removing on top of it
             buys nothing. */
          button.disabled = true;
          status.textContent =
            'Marked as paid. It is not counted until ' + receiver + ' confirms.';
          /* Nothing is re-read. A second GET would snap every open drill-down shut
             and destroy this live region mid-announcement, and the one row it would
             add is the row appended here. */
          if (attempt === balancesAttempt && payload) {
            balancesPendingAdd(payload.settlement, names, actingId);
          }
        },
        function () {
          region.removeAttribute('aria-busy');
          asking = false;
          /* Nothing was kept, so pressing again sends a fresh request. */
          button.disabled = false;
          /* One sentence, for every one of the six kinds, into this row and nowhere
             else: #balances-error stays hidden, the net list is untouched, the
             pending block is untouched and an open drill-down stays open. */
          status.textContent = BALANCES_NOT_RECORDED;
        }
      );
    });
    return region;
  }

  function balancesTransferRow(transfer, names, actingId) {
    /* Still the one function that takes one transfer and returns one row, so the
       drill-down is a change here and not a restructuring of the list. */
    var row = document.createElement('li');
    /* The two ids say which transfer a row belongs to without anyone parsing its
       text. Attributes only, never rendered as text, and task 14 still finds them. */
    row.setAttribute('data-from', transfer.from_member_id);
    row.setAttribute('data-to', transfer.to_member_id);
    var openable = balancesOpenable(transfer);
    /* The extra class is what lets a transfer row stack its two children without
       .balances-row's own display being edited, which the net list still uses. */
    row.className = openable ? 'balances-row balances-transfer' : 'balances-row';

    /* Byte for byte what task 12 rendered. The payer is named first: they are the
       one who acts on the row, and task 14 hangs "mark as paid" off it. */
    var sentence = balancesName(transfer.from_member_id, names, actingId) +
      ' pays ' + balancesName(transfer.to_member_id, names, actingId) + ' ';

    if (!openable) {
      /* Exactly as task 12 drew it: one inert span, no button, no aria-expanded, no
         detail region, no indicator and no pointer cursor. The honest fallback
         against an older server or a partial payload, because nothing may look
         tappable before the data behind it is there. */
      var line = document.createElement('span');
      line.className = 'balances-line';
      line.appendChild(document.createTextNode(sentence));
      line.appendChild(balancesFigure(transfer.amount));
      row.appendChild(line);
      return row;
    }

    var detail = balancesTransferDetail(transfer, names, actingId);
    var indicator = balancesText('span', 'balances-indicator', '+');
    /* aria-expanded on the button already says the same thing to a reader, and
       twice is noise. Open and closed are told apart by this character as well as by
       the region itself, and never by colour alone. */
    indicator.setAttribute('aria-hidden', 'true');

    /* A real button, so Enter and Space work with no key handler, the focus order is
       right with nothing written to put it there, and no role is needed. Not an
       anchor, which would put
       an entry in the history; not a details element, whose open state and styling
       differ across the browsers this ships to. */
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'balances-transfer-button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', detail.id);

    var text = document.createElement('span');
    text.className = 'balances-line';
    text.appendChild(document.createTextNode(sentence));
    text.appendChild(balancesFigure(transfer.amount));
    button.appendChild(text);
    button.appendChild(indicator);

    button.addEventListener('click', function () {
      if (!ledgerIsUp()) {
        return;
      }
      /* More than one payment may be open at once, and more than one debt inside
         one payment: collapsing somebody else's row to open yours is surprising, and
         single-open would be a piece of state the next render has to preserve.
         Nothing here changes the hash, pushes a history entry, scrolls anything or
         re-renders another row. */
      var open = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', open ? 'false' : 'true');
      detail.hidden = open;
      indicator.textContent = open ? '+' : '-';
    });

    /* The region is a sibling of the button rather than its child, which is what let
       task 14 append a third child here without unpicking either of the first two. */
    row.appendChild(button);
    row.appendChild(detail);
    /* Task 14's third child, when there is one. An inert row returned above and never
       reaches this, so a transfer whose payload cannot explain itself gets no button
       and no awaiting line even when the acting member is its payer: a screen that
       cannot explain a payment has no business offering to record it, and task 13's
       one-span row is not amended. The claim is not lost in that case, because the
       pending block above is built from `pending` and not from these rows. */
    var action = balancesActionRegion(transfer, names, actingId);
    if (action !== null) {
      row.appendChild(action);
    }
    return row;
  }

  function balancesFill(list, entries, build, names, actingId) {
    /* Rendered in the order the array arrived and in no other: `net` is roster order
       and `transfers` is (from_member_id, to_member_id) order, both fixed in the
       domain layer. Nothing is sorted, reversed, filtered, merged or deduplicated,
       so a pair the server sent twice would render twice. */
    for (var index = 0; index < entries.length; index += 1) {
      list.appendChild(build(entries[index], names, actingId));
    }
    list.hidden = entries.length === 0;
  }

  function balancesRender(roster, figures) {
    /* The balances payload carries ids only, so the roster supplies every name. */
    var names = {};
    var members = (roster && roster.members) || [];
    for (var index = 0; index < members.length; index += 1) {
      names[members[index].id] = members[index].display_name;
    }
    var actingId = balancesActingId();
    var net = (figures && figures.net) || [];
    var transfers = (figures && figures.transfers) || [];

    balancesClear();

    if (net.length === 0) {
      /* Reachable through a half-finished setup_group.py run. A screen showing two
         empty lists in that state reads as a bug, so neither list is shown. */
      balancesMessage('empty-roster');
      return;
    }

    /* net_for is total by design, so a group that has recorded nothing still returns
       one entry per member, every one of them settled. That is what stops a fresh
       flat opening this screen and seeing a blank page. */
    balancesFill(netList, net, balancesNetRow, names, actingId);
    /* Named once, above the list, and taken from the payload rather than hard-coded
       here. Shown only once there is at least one row to apply it to. */
    currencyCode.textContent = figures.currency;
    currencyLine.hidden = false;

    /* Rendered independently of the transfer list, and never suppressed by any of the
       four fixed messages: a group with nothing left to settle and a claim nobody has
       confirmed is showing two true things at once, and hiding either would be the
       screen deciding one of them does not count. */
    balancesPendingFill(figures.pending, names, actingId);

    balancesFill(transferList, transfers, balancesTransferRow, names, actingId);
    /* Shown only when at least one rendered row is a control that really opens. An
       instruction to open something inert is worse than silence, and a transfer with
       no usable provenance is exactly that. */
    drillHint.hidden = !balancesAnyOpenable(transfers);
    /* An empty transfer list is a stated answer, not an absence. The sentence is
       true of a group that has never spent anything and true of one that has spent
       and settled every penny, which matters, because this screen cannot tell those
       two apart: the payload is identical for both, and task 16 owns the real
       incompleteness signal. Do not add a special case here to separate them. */
    balancesMessage(transfers.length === 0 ? 'none' : '');
  }

  function balancesLoad() {
    balancesAttempt += 1;
    var attempt = balancesAttempt;
    /* Cleared first, so nothing from the last visit is on screen while this one is
       in flight. No spinner, no animation and no greyed skeleton row: a skeleton on
       a money screen reads as broken. */
    balancesClear();
    balancesMessage('busy');
    /* Both go out together and the screen draws only when both have answered. */
    Promise.all([api.members(), api.balances()]).then(
      function (answers) {
        if (attempt !== balancesAttempt) {
          /* The user left and came back. A newer attempt owns the screen, and a late
             answer must never be drawn over it. */
          return;
        }
        balancesMessage('');
        balancesRender(answers[0], answers[1]);
      },
      function () {
        if (attempt !== balancesAttempt) {
          return;
        }
        /* Unconditional. The three global handlers replace the whole app frame, so
           this may run while the screen is hidden, which is fine: re-entering the
           app reads again and overwrites it. Stale figures are never left behind
           after a failed refresh. */
        balancesClear();
        balancesMessage('error');
      }
    );
  }

  function balancesEntered() {
    /* Called on every entry to the balances route, and once more from showApp when a
       curtain comes down on this screen, so that signing in while already on it does
       not leave it blank. This screen holds nothing typed, so those two are the same
       act for it and both read again: nothing is kept between visits, and figures
       held over an interruption would be stale. No other route reads them, there is
       no polling and there is no automatic retry. Tapping Balances while already on
       Balances changes no hash, so no hashchange fires and nothing happens, which is
       task 8's no-op rule.

       Two guards: somebody is signed in and looking at the ledger rather than at a
       curtain, and this screen's route is the current one. The helper in the
       preamble carries the first one and says why. */
    if (!ledgerIsUp() || window.location.hash !== BALANCES_ROUTE) {
      return;
    }
    balancesLoad();
  }

  window.addEventListener('hashchange', balancesEntered);
})();

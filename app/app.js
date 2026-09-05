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

    if (changed && moveFocus) {
      /* Focus the heading of the screen that just appeared, so a screen reader
         announces the new view. The heading carries tabindex="-1" for this. */
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
      /* Every allocation, including a 0.00, rendered as the API spelled it. Never
         dropped, never blanked and never dashed out. */
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
    /* Three guards before anything happens: the client has loaded, this screen's
       route is the current one, and no load is already running. app.js loads api.js
       asynchronously, so a hashchange can arrive before api is assigned. A load while
       a load is running is skipped rather than queued, so repeated tab taps cannot
       stack requests. */
    if (!api || window.location.hash !== FEED_ROUTE || feedBusy) {
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
  var creating = false;

  function show(which) {
    /* One of 'app', 'gate' or 'notice'. The hash is never touched: signing in
       returns the user to the screen they were already on. */
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

  function showNotice(which) {
    noticeUnlinked.hidden = which !== 'unlinked';
    noticeOffline.hidden = which !== 'offline';
    show('notice');
    document.getElementById('notice-title').focus();
  }

  function showApp() {
    signOut.hidden = false;
    show('app');
    loadFeed();
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
        if (!error || error.status === 0 || error.status >= 500) {
          /* No answer came back at all. The offline notice is already up and the
             gate deliberately is not, so there is nothing to say here. */
          return;
        }
        /* Everything else is something the person can act on, a wrong password most
           of all. The 401 handler has just re-shown the gate with a blank message,
           so this runs after it and is what they actually read. */
        gateError.textContent = error.message || 'That did not work.';
        gateError.hidden = false;
        show('gate');
      })
      .then(function () {
        gateSubmit.disabled = false;
      });
  }

  function wire() {
    api.onUnauthenticated(function () {
      showGate('');
    });
    api.onNotLinked(function () {
      signOut.hidden = false;
      showNotice('unlinked');
    });
    api.onOffline(function () {
      /* Never the sign-in gate: prompting for a password on a page that cannot
         send it is how a person types their password into nothing, repeatedly. */
      showNotice('offline');
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
})();

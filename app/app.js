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
    balancesEntered();
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

     Nothing here is tappable. Task 13 turns a transfer row into a drill-down by
     changing one function, and until it does, an affordance that does nothing is
     worse than none. */

  var BALANCES_ROUTE = '#/balances';
  /* A member id is an opaque string and means nothing to a flatmate, so no id is
     ever rendered. A row whose member is missing from the roster still renders under
     this name: hiding money because a name is missing is the worse failure. */
  var UNKNOWN_MEMBER = 'Unknown member';
  /* The acting member is marked, never renamed to "You". Two flatmates read this
     list off one phone, and a row that means different things depending on who is
     holding the phone is worse than a list of names. */
  var ACTING_SUFFIX = ' (you)';

  var netList = document.getElementById('balances-net');
  var transferList = document.getElementById('balances-transfers');
  var currencyLine = document.getElementById('balances-currency');
  var currencyCode = document.getElementById('balances-currency-code');
  var balancesBusy = document.getElementById('balances-busy');
  var balancesError = document.getElementById('balances-error');
  var balancesNone = document.getElementById('balances-none');
  var balancesEmptyRoster = document.getElementById('balances-empty-roster');

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

  function balancesTransferRow(transfer, names, actingId) {
    /* The one function task 13 changes. It takes one transfer and returns one row,
       so the drill-down is a change here and not a restructuring of the list. */
    var row = document.createElement('li');
    row.className = 'balances-row';
    /* For task 13: the two ids say which transfer a row belongs to without anyone
       parsing its text. Attributes only, never rendered as text. */
    row.setAttribute('data-from', transfer.from_member_id);
    row.setAttribute('data-to', transfer.to_member_id);
    /* The sentence sits inside exactly one child element, so task 13 can replace
       that child with a button and append a detail region as its sibling without
       touching the code that builds the list. The payer is named first: they are
       the one who acts on the row, and task 14 hangs "mark as paid" off it. */
    var line = document.createElement('span');
    line.className = 'balances-line';
    line.appendChild(
      document.createTextNode(
        balancesName(transfer.from_member_id, names, actingId) +
          ' pays ' +
          balancesName(transfer.to_member_id, names, actingId) +
          ' '
      )
    );
    line.appendChild(balancesFigure(transfer.amount));
    row.appendChild(line);
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

    balancesFill(transferList, transfers, balancesTransferRow, names, actingId);
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
    /* Called on every entry to the balances route, and once more from showApp so
       that signing in while already on this screen does not leave it blank. Every
       entry reads again: nothing is kept between visits. No other route reads the
       figures, there is no polling and there is no automatic retry. Tapping Balances
       while already on Balances changes no hash, so no hashchange fires and nothing
       happens, which is task 8's no-op rule. */
    if (window.location.hash !== BALANCES_ROUTE) {
      return;
    }
    if (!api) {
      /* The client has not loaded yet, so there is nothing to ask. Its onerror
         already shows the offline notice. */
      return;
    }
    balancesLoad();
  }

  window.addEventListener('hashchange', balancesEntered);
})();

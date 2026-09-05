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

/* Splitwise Lite API client: the only file in app/ that talks to the back end.

   Everything the shell knows about the network lives here. app.js and every screen
   task after it call these functions and never build a URL, never set a header and
   never read a cookie: one network chokepoint, so there is one answer to a 401 and
   one place to change when the contract does.

   Three failure paths, and they are deliberately different screens:

   * 401, any request. The cached session view is dropped and onUnauthenticated fires,
     and the boot code shows the sign-in gate. No retry, no redirect, no loop.
   * 403 with code member_not_linked. onNotLinked fires and the boot code shows
     "nobody has linked you to a member yet", because retyping a password would not
     fix it.
   * A network failure, meaning the request never got an answer at all, or the server
     could not produce one. onOffline fires and the gate is never shown: prompting for
     a password on a page that cannot send it is how a person ends up typing their
     password into nothing, repeatedly.

   Money crosses the wire as a formatted string and is passed straight through. This
   file does no formatting, no cent arithmetic and no split maths, and it must not
   start: the back end is the only place that knows what an amount is.

   It writes no cookie and keeps nothing in browser storage. The session cookie is
   HttpOnly and unreadable here by design; the CSRF cookie is read at request time,
   never cached, so a token rotated by signing in is picked up on the very next
   request. A copy of server state kept in the browser is how a signed-out page keeps
   showing a ledger. */

(function () {
  'use strict';

  var BASE = '/api';
  var CSRF_COOKIE = 'sl_csrf';
  var CSRF_HEADER = 'X-CSRF-Token';
  var UNSAFE = { POST: true, PUT: true, PATCH: true, DELETE: true };

  /* The last session view a request returned, so a screen can ask who is acting
     without a second round trip. Dropped on a 401 and on sign-out, never persisted:
     it is a copy of server state, not a store. */
  var cached = null;

  var handlers = {
    unauthenticated: function () {},
    notLinked: function () {},
    offline: function () {}
  };

  function readCookie(name) {
    /* Read at request time rather than cached in a variable, so the token the
       server rotated on the last response is the one this request carries. */
    var parts = String(document.cookie || '').split(';');
    for (var index = 0; index < parts.length; index += 1) {
      var pair = parts[index];
      var split = pair.indexOf('=');
      if (split === -1) {
        continue;
      }
      if (pair.slice(0, split).trim() === name) {
        return decodeURIComponent(pair.slice(split + 1));
      }
    }
    return null;
  }

  function ApiError(status, code, message) {
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.message = message;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function request(method, path, body) {
    var options = {
      method: method,
      /* Same-origin, so the cookies go with the request and no cross-origin
         request can ever be made from here. */
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    };
    if (UNSAFE[method]) {
      options.headers['Content-Type'] = 'application/json';
      var token = readCookie(CSRF_COOKIE);
      if (token) {
        options.headers[CSRF_HEADER] = token;
      }
      options.body = JSON.stringify(body || {});
    }

    return fetch(BASE + path, options).then(
      function (response) {
        if (response.status === 204) {
          return null;
        }
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (payload) {
            if (response.ok) {
              return payload;
            }
            var error = payload && payload.error ? payload.error : {};
            return Promise.reject(
              new ApiError(response.status, error.code || '', error.message || '')
            );
          });
      },
      function (networkFailure) {
        /* The request never got an answer. Never the sign-in gate. */
        return Promise.reject(new ApiError(0, 'offline', String(networkFailure)));
      }
    );
  }

  function announce(error) {
    if (error.status === 401) {
      cached = null;
      handlers.unauthenticated(error);
    } else if (error.status === 403 && error.code === 'member_not_linked') {
      handlers.notLinked(error);
    } else if (error.status === 0 || error.status >= 500) {
      /* Offline, or the server could not answer. One message covers both, because
         from the page they are the same situation: no answer came back. */
      handlers.offline(error);
    }
    return Promise.reject(error);
  }

  function call(method, path, body) {
    return request(method, path, body).catch(announce);
  }

  window.SplitwiseApi = {
    ApiError: ApiError,

    onUnauthenticated: function (handler) {
      handlers.unauthenticated = handler;
    },
    onNotLinked: function (handler) {
      handlers.notLinked = handler;
    },
    onOffline: function (handler) {
      handlers.offline = handler;
    },

    /* The session view: who is signed in, which group, and which member they act
       as. member is null until an operator has linked the account. */
    session: function () {
      return call('GET', '/session').then(function (view) {
        cached = view;
        return view;
      });
    },

    /* What the last session call returned, or null. A copy, never a store. */
    cachedSession: function () {
      return cached;
    },

    signUp: function (email, displayName, password) {
      return call('POST', '/signup', {
        email: email,
        display_name: displayName,
        password: password
      });
    },

    signIn: function (email, password) {
      return call('POST', '/session', { email: email, password: password }).then(
        function (view) {
          cached = view;
          return view;
        }
      );
    },

    signOut: function () {
      return call('DELETE', '/session').then(function () {
        cached = null;
        return null;
      });
    },

    /* The roster, in the order the group stores it. Ids and display names only. */
    members: function () {
      return call('GET', '/members');
    },

    /* The feed, newest first, each entry carrying its own allocations. */
    expenses: function () {
      return call('GET', '/expenses');
    },

    /* One expense. amount is a string, and split is one of the three shapes the
       resolver takes: equal, weight or exact. */
    addExpense: function (expense) {
      return call('POST', '/expenses', expense);
    },

    /* Net positions for every member, plus the suggested transfers. */
    balances: function () {
      return call('GET', '/balances');
    }
  };
})();

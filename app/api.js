/* Splitwise Lite API client: the only file in app/ that talks to the back end.

   Everything the shell knows about the network lives here. app.js and every screen
   task after it call these functions and never build a URL, never set a header and
   never read a cookie: one network chokepoint, so there is one answer to a 401 and
   one place to change when the contract does.

   THE ERROR CONTRACT. web.py decides what every refusal is; this file is the one
   place that decides what a refusal means to the person holding the phone. The
   screens print what they are handed and classify nothing. A screen may branch on
   kind. No screen may branch on status or on code.

   Six kinds, three handlers, two fields. Every failed request is given a kind before
   any handler runs, and every one of them ends in exactly one of two places: a
   curtain over the whole frame, or a rejection the screen that asked for it reports.

     kind              what it means                        handler    say
     offline           no answer came back at all           onOffline  ''
     signed-out        signing in is what fixes it          onUnauth-  message, or ''
                                                            enticated  for the code
                                                                       not_authenticated
     sign-in-not-kept  the server took the sign-in and      onOffline  ''
                       then refused the next request
     not-linked        signed in, no member row             onNotLinked ''
     unavailable       it answered, and this app cannot     onOffline  message
                       go on
     refused           it refused this one request and      none, see  message
                       said why                             below

   say is, on every path, either exactly error.message or exactly ''. There is no
   third possibility, and a string literal here that could become one is the drift
   this contract exists to remove: two sentences for one situation drift the moment
   either one is edited. This file chooses whether to speak. It never chooses the
   words. '' means there is nothing here worth reading, either because the body
   carried no message or because the message describes a situation the person is not
   in.

   error.message is the server's sentence character for character, and '' when no body
   carried one, a rejected fetch included. This file composes no prose at all: not a
   prefix, not a fallback, and not a rendering of whatever object fetch rejected with.
   That is what makes say's two possibilities two rather than three.

   The screens own three sentences between them, and none of them is here. Two are
   standing copy on the notice curtain in app/index.html, for the two situations the
   server has no sentence to offer: nothing came back at all, and a sign-in the server
   accepted whose very next request it then refused. The third is app/app.js's last
   resort on the gate, for a refusal whose body carried nothing to show; that is not a
   situation with a sentence of its own, it is what the gate says when there is
   nothing to say.

   not_authenticated is the only 401 code whose sentence is suppressed, because it
   means there was no cookie at all, which is every first visit, and "this endpoint
   needs a signed-in session" is written for a client rather than for a flatmate. The
   gate already says what it is for. session_invalid and authentication_failed both
   say something the person needs.

   The classification, read top to bottom against web.py's error table. The last two
   rows are the default and are reached by anything the rows above did not claim,
   which is the whole point: a classifier that recognises a few cases and silently
   drops the rest is not a classifier.

     0     offline, or a response this client may not read      -> offline
     401   not_authenticated, session_invalid,                  -> signed-out, or
           authentication_failed                                   sign-in-not-kept
                                                                   while armed
     403   member_not_linked                                    -> not-linked
     403   csrf_failed, not_the_receiver, or any other code      -> refused
     400   malformed_request, invalid_email, invalid_password,  -> refused
           invalid_amount, invalid_currency, currency_mismatch,
           invalid_split, invalid_record, amount_too_large
     404   record_not_found, not_found                          -> refused
     405   method_not_allowed                                   -> refused
     409   email_already_registered, duplicate_record,          -> refused
           constraint_violated, group_mismatch,
           member_already_linked, user_already_linked,
           settlement_already_pending, settlement_already_decided
     413   request_too_large                                    -> refused
     429   too_many_attempts                                    -> refused
     500   internal_error                                       -> unavailable
     503   no_group_configured, ambiguous_group                 -> unavailable
     any other status at or above 500, or a status that is      -> unavailable
     not a readable number
     any other status below 500                                 -> refused

   An unreadable status is never refused and never raises the gate: if the client
   cannot tell the request was refused, offering a password box is how a person ends
   up typing their password into nothing, repeatedly. A 500 and a rejected fetch stay
   two different kinds for the same reason they are two different things: one is an
   answer this app produced and logged and it carries a sentence, the other is no
   answer at all.

   A refused is the caller's to report, because it names something about the one
   request that was made: raising a curtain over the whole frame for a 409 on signup
   would take the gate's own message away. Two requests have no caller that reports
   anything, because app.js discards both rejections by design, so a refused answering
   either of those two calls onOffline as well: GET /session, whose rejection
   refresh() discards on the grounds that a handler has already spoken, and
   DELETE /session, whose rejection the sign out button discards.

   Nothing here retries, re-sends, redirects or loops. announce() fires once per
   failed request and does not deduplicate, debounce or coalesce: two failures in
   flight fire twice, and when they are two different kinds the last handler to run
   owns the screen. This file does not arbitrate between them.

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

  /* The two requests whose refusal nobody else would ever report, because app.js
     discards both rejections by design. A refused answering either is escalated to
     the offline handler, which now prints what the server said rather than claiming
     the network is down. */
  var ESCALATED = { 'GET /session': true, 'DELETE /session': true };

  /* The one request whose own 401 is always a wrong password rather than a session
     that did not stick. */
  var SIGN_IN = 'POST /session';

  /* One shot, and it holds nothing about the session: armed by a 200 from
     POST /session, disarmed by the first response after it that is not a 401 and by
     signing out. Never persisted, and never in browser storage. */
  var armed = false;

  function noted(status) {
    /* Every answer this client gets passes through here. A 401 while armed is the
       sign-in that did not stick; anything else means the round trip after the
       sign-in worked, so the question is settled. */
    if (status !== 401) {
      armed = false;
    }
  }

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
    /* What the server said. code stays exactly what it sent; kind is what this
       client decided it means, and it is set by announce() before any handler runs. */
    this.code = code;
    this.message = message;
    this.kind = '';
    this.say = '';
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
        noted(response.status);
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
      function () {
        /* The request never got an answer, so no body carried a message and the
           message is '' exactly as it is for any other empty body. Never the sign-in
           gate.

           The rejection fetch hands back says "TypeError: Failed to fetch", and this
           used to be composed into message. It was diagnostics rather than anything a
           person reads, say kept it off the screen, and it made this file the author
           of the one message it promises never to write. */
        noted(0);
        return Promise.reject(new ApiError(0, 'offline', ''));
      }
    );
  }

  /* The classification table in the header, as a ladder read top to bottom. It ends
     in a default arm rather than falling off the end: everything the server can
     answer with gets a kind, including the statuses nobody anticipated. */
  function classify(error, route) {
    var status = error.status;
    if (typeof status !== 'number' || !isFinite(status)) {
      /* Unreadable. Never refused and never the gate: if the client cannot tell the
         request was refused, a password box is where the loop starts. */
      return 'unavailable';
    }
    if (status === 0) {
      return 'offline';
    }
    if (status === 401) {
      return armed && route !== SIGN_IN ? 'sign-in-not-kept' : 'signed-out';
    }
    if (status === 403 && error.code === 'member_not_linked') {
      return 'not-linked';
    }
    if (status >= 500) {
      return 'unavailable';
    }
    return 'refused';
  }

  /* Whether the server sent anything worth putting in front of the person. The
     answer decides between error.message and '', and there is no third answer. */
  function speaks(kind, code) {
    if (kind === 'offline' || kind === 'sign-in-not-kept' || kind === 'not-linked') {
      /* Nothing came back, or what came back describes a different situation from
         the one the person is in. */
      return false;
    }
    return !(kind === 'signed-out' && code === 'not_authenticated');
  }

  function announce(error, route) {
    var kind = classify(error, route);
    error.kind = kind;
    error.say = speaks(kind, error.code) ? error.message : '';

    /* Both kinds mean the server no longer agrees this client is signed in, and the
       copy goes before any handler runs, so a handler that reads cachedSession()
       cannot see a stale one. */
    if (kind === 'signed-out' || kind === 'sign-in-not-kept') {
      cached = null;
    }

    try {
      if (kind === 'signed-out') {
        handlers.unauthenticated(error);
      } else if (kind === 'not-linked') {
        handlers.notLinked(error);
      } else if (
        kind === 'offline' ||
        kind === 'unavailable' ||
        kind === 'sign-in-not-kept'
      ) {
        /* No usable answer, and never the sign-in gate: prompting for a password on
           a page that cannot send it is how a person types their password into
           nothing, repeatedly. */
        handlers.offline(error);
      } else if (kind === 'refused' && ESCALATED[route]) {
        handlers.offline(error);
      }
      /* Every other refused is the caller's own to report, on the screen that asked
         for it, in the server's words. */
    } catch (screenBug) {
      /* A handler is a screen's code and a screen can have a bug in it. That must
         not change what the caller is rejected with, and must not leave a caller
         waiting forever on a promise nobody settles. */
    }
    return Promise.reject(error);
  }

  function call(method, path, body) {
    var route = method + ' ' + path;
    return request(method, path, body).catch(function (error) {
      return announce(error, route);
    });
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
          /* The server took these credentials. If the very next request comes back a
             401 then the session did not survive one round trip, which is what a
             browser that will not keep the cookie looks like, and signing in again
             cannot fix it. */
          armed = true;
          return view;
        }
      );
    },

    signOut: function () {
      return call('DELETE', '/session').then(function () {
        cached = null;
        /* Nothing about a session outlives signing out. The answer to this request
           has already disarmed the check, since it was not a 401; saying it here as
           well keeps the rule where a reader goes looking for it. */
        armed = false;
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
    },

    /* What one pairwise debt is made of: the expenses and confirmed settlements
       behind what debtorId owes creditorId, each carrying a server-computed effect of
       adds or reduces. Both ids are encoded, because a member id is whatever the
       roster an operator wrote says it is, and one carrying a space or a percent sign
       still has to reach the right pair. A refusal here is a refusal like any other,
       and so is the caller's own to report: it names one pair, and a curtain over the
       whole frame would take that screen's own message away. */
    debt: function (debtorId, creditorId) {
      return call(
        'GET',
        '/debts/' +
          encodeURIComponent(debtorId) +
          '/' +
          encodeURIComponent(creditorId)
      );
    },

    /* Record that whoever is signed in has paid toMemberId. The payer is never sent:
       the server takes it from the session, which is what stops one member recording
       a payment as coming from another, and the two keys below are the whole body.
       amount is the string the person is recording, passed through untouched, since
       nothing in this file parses, formats or compares money. A refusal here is a
       refusal like any other and so is the caller's own to report: it belongs to one
       row of one screen, and a curtain over the whole frame would take that row's own
       message away. */
    addSettlement: function (toMemberId, amount) {
      return call('POST', '/settlements', {
        to_member_id: toMemberId,
        amount: amount
      });
    },

    /* Answer one claimed payment: decision is 'confirmed' or 'rejected' and is the
       whole body. The decider is never sent, for the same reason the payer never is:
       the server takes it from the session, which is what stops one person both
       claiming and confirming a payment. The id is encoded, because a settlement id is
       whatever the server minted and a path segment is a path segment. A refusal here
       is a refusal like any other and so is the caller's own to report: it belongs to
       one row of one screen, and a curtain over the whole frame would take that row's
       own message away. */
    decideSettlement: function (settlementId, decision) {
      return call(
        'POST',
        '/settlements/' + encodeURIComponent(settlementId) + '/decision',
        { decision: decision }
      );
    }
  };
})();

/* The Lineup accounts: sign in, profile, "going", who's going, connect requests.
   The database enforces every privacy rule; this file is just the buttons. */
(function () {
  var CFG = {
    url: "https://pwthxugduzlcceedxqwk.supabase.co",
    key: "sb_publishable_Xx5NcuHzeKpRc_D9l8eSOQ_t_sGck7r", // public by design
    states: null, // null = "Going" is live on every US in-person event. Or list states, e.g. ["NJ","NY"].
    maxRequests: 5
  };
  var ROLES = ["Student", "IT Support / Help Desk", "SOC / Analyst", "GRC / Audit", "Security Engineer", "Pentest / Red Team",
    "Cloud / DevOps", "Network Engineer", "Software / AI Engineer", "Data / ML", "Manager / Leader", "Recruiter", "Founder", "Other"];
  var STATES = {AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",CO:"Colorado",CT:"Connecticut",DE:"Delaware",DC:"District of Columbia",FL:"Florida",GA:"Georgia",HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",IA:"Iowa",KS:"Kansas",KY:"Kentucky",LA:"Louisiana",ME:"Maine",MD:"Maryland",MA:"Massachusetts",MI:"Michigan",MN:"Minnesota",MS:"Mississippi",MO:"Missouri",MT:"Montana",NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",TN:"Tennessee",TX:"Texas",UT:"Utah",VT:"Vermont",VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming"};
  var EXP = ["Student", "0-2 years", "3-5 years", "6-10 years", "10+ years"];
  var DAY = 864e5;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === "text") n.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function css() {
    if (document.getElementById("acct-css")) return;
    var s = el("style", { id: "acct-css" });
    s.textContent = ".acct{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:18px;margin:0 0 26px}" +
      ".acct h3{margin:0 0 6px;font-size:1rem}.acct p{color:var(--soft);margin:0 0 12px;font-size:.92rem}" +
      ".acct label{display:block;font-size:.85rem;color:var(--soft);margin:10px 0 4px}" +
      ".acct input[type=text],.acct input[type=email],.acct select,.acct textarea{width:100%;padding:.6rem .7rem;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit}" +
      ".acct .chk{display:flex;gap:8px;align-items:flex-start;color:var(--soft);font-size:.88rem;margin:10px 0}" +
      ".acct .row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}" +
      ".acct .row small{color:var(--dim);display:block}.acct .btn{cursor:pointer;background:transparent;color:var(--ink);font:inherit;font-size:.85rem}" +
      ".acct .btn--solid{background:var(--acc);color:#17120a}.acct .link{background:none;border:0;color:var(--dim);cursor:pointer;font-size:.78rem;text-decoration:underline;padding:0 0 0 8px}" +
      ".acct .msg{color:var(--acc);font-size:.88rem;margin-top:10px}.acct .count{font:500 .85rem 'Geist Mono',monospace;color:var(--soft)}";
    document.head.appendChild(s);
  }
  function loadLib(cb) {
    if (window.supabase && window.supabase.createClient) return cb();
    var s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2";
    s.onload = cb;
    document.head.appendChild(s);
  }
  var sb, user, profile;
  function boot(cb) {
    loadLib(function () {
      sb = window.supabase.createClient(CFG.url, CFG.key, { auth: { persistSession: true, detectSessionInUrl: true } });
      sb.auth.getSession().then(function (r) {
        user = r.data.session ? r.data.session.user : null;
        if (!user) return cb();
        sb.from("profiles").select("*").eq("id", user.id).maybeSingle().then(function (p) { profile = p.data; cb(); });
      });
    });
  }
  function nice(err) {
    var m = (err && err.message) || "Something went wrong. Try again.";
    return m.replace(/^.*?exception:?\s*/i, "");
  }
  function gdates(d) {
    if (isNaN(d)) return "";
    var z = function (x) { return x.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, ""); };
    return z(d) + "/" + z(new Date(+d + 2 * 36e5));
  }
  function fmt(d) { return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); }

  /* ---------------- event page: going + who's going ---------------- */
  function eventBox(box) {
    var id = box.dataset.event, start = new Date(box.dataset.start), st = box.dataset.state;
    if (CFG.states && CFG.states.indexOf(st) < 0) return; // not live in this state yet
    css();
    var card = el("div", { class: "acct" });
    box.appendChild(card);
    var opens = new Date(start - 7 * DAY), closes = new Date(+start + DAY), now = new Date();
    var windowOpen = now >= opens && now <= closes;

    function render() {
      card.innerHTML = "";
      sb.rpc("going_counts", { ids: [id] }).then(function (r) {
        var n = (r.data && r.data[0]) ? r.data[0].going : 0;
        card.appendChild(el("div", { class: "count", text: n + (n == 1 ? " person" : " people") + " from The Lineup going" }));
        if (!user) {
          card.appendChild(el("p", { text: "Sign in to say you're going and see who else from the community will be there." }));
          card.appendChild(el("a", { class: "btn btn--solid", href: "/account/?next=" + encodeURIComponent(location.pathname), text: "Sign in" }));
          return;
        }
        if (!profile) {
          card.appendChild(el("p", { text: "Finish your profile first (name and role, takes 20 seconds)." }));
          card.appendChild(el("a", { class: "btn btn--solid", href: "/account/?next=" + encodeURIComponent(location.pathname), text: "Finish profile" }));
          return;
        }
        sb.from("rsvps").select("event_id").eq("event_id", id).eq("user_id", user.id).then(function (g) {
          var going = g.data && g.data.length > 0;
          var msg = el("div", { class: "msg" });
          var b = el("button", { class: "btn" + (going ? "" : " btn--solid"), text: going ? "You're going · undo" : "I'm going" , onclick: function () {
            b.disabled = true;
            var q = going ? sb.from("rsvps").delete().eq("event_id", id).eq("user_id", user.id)
                          : sb.from("rsvps").insert({ event_id: id, user_id: user.id });
            q.then(function (res) { if (res.error) { msg.textContent = /foreign key/i.test(res.error.message) ? "This event isn't synced yet. Try again tomorrow." : nice(res.error); b.disabled = false; } else render(); });
          } });
          card.appendChild(el("div", { style: "margin:12px 0" }, [b]));
          card.appendChild(msg);
          if (going) {
            var cal = document.querySelector('a[href^="/e/"]');
            card.appendChild(el("p", { style: "margin:0 0 12px" }, ["Put it on your calendar so you actually go: ",
              el("a", { href: "/e/" + id + ".ics", text: "Apple / Outlook" }), " · ",
              el("a", { href: "https://calendar.google.com/calendar/render?action=TEMPLATE&text=" + encodeURIComponent(document.querySelector("h1").textContent) +
                "&dates=" + gdates(start) + "&details=" + encodeURIComponent(location.href), target: "_blank", rel: "noopener", text: "Google" })]));
            attendees();
          }
        });
      });
    }
    function attendees() {
      sb.rpc("attendees", { e: id }).then(function (r) {
        var list = r.data || [];
        card.appendChild(el("h3", { text: "Who's going" }));
        card.appendChild(el("p", { text: windowOpen ? "Want to link up? Send a connect request. Emails are only shared if you both say yes. Max " + CFG.maxRequests + " requests per event."
          : now < opens ? "Connect requests open " + fmt(opens) + " (a week before). Until then you can see who's going." : "Connect requests for this event are closed." }));
        if (!list.length) card.appendChild(el("p", { text: "Nobody else yet. Share the page with a friend." }));
        list.forEach(function (a) {
          var right = el("div");
          var st = a.connect_status;
          if (st) right.appendChild(el("span", { class: "count", text: st.indexOf("accepted") === 0 ? "Connected" : st.indexOf("declined") === 0 ? "—" : st.indexOf(":sent") > 0 ? "Requested" : "Wants to connect · see Account" }));
          else if (windowOpen) right.appendChild(el("button", { class: "btn", text: "Connect", onclick: function (ev) {
            var btn = ev.target; btn.disabled = true;
            sb.from("connections").insert({ event_id: id, from_user: user.id, to_user: a.user_id }).then(function (res) {
              if (res.error) { btn.disabled = false; alertRow(row, nice(res.error)); } else { btn.replaceWith(el("span", { class: "count", text: "Requested" })); }
            });
          } }));
          right.appendChild(el("button", { class: "link", text: "Block", onclick: function () {
            if (!confirm("Block " + a.first_name + "? You'll stop seeing each other.")) return;
            sb.from("blocks").insert({ blocker: user.id, blocked: a.user_id }).then(function () { render(); });
          } }));
          right.appendChild(el("button", { class: "link", text: "Report", onclick: function () { report(a.user_id, id); } }));
          var row = el("div", { class: "row" }, [el("div", {}, [el("b", { text: a.first_name + " " + a.last_initial + "." }), el("small", { text: a.role + " · " + a.experience })]), right]);
          card.appendChild(row);
        });
      });
    }
    function alertRow(row, t) { row.appendChild(el("div", { class: "msg", text: t })); }
    render();
  }

  function report(uid, eventId) {
    var why = prompt("What happened? This goes privately to The Lineup.");
    if (!why || why.trim().length < 3) return;
    sb.from("reports").insert({ reporter: user.id, reported: uid, event_id: eventId || null, reason: why.trim().slice(0, 1000) })
      .then(function (r) { alert(r.error ? nice(r.error) : "Thanks. We'll look into it."); });
  }

  /* ---------------- account page ---------------- */
  function accountPage(root) {
    css();
    var next = new URLSearchParams(location.search).get("next");
    if (next && !/^\/[^\/]/.test(next)) next = null; // local paths only
    root.innerHTML = "";
    if (!user) return signIn(root, next);
    if (!profile) return profileForm(root, next, true);
    if (next) { location.replace(next); return; }
    var card = el("div", { class: "acct" });
    card.appendChild(el("h3", { text: "Hey " + profile.first_name }));
    card.appendChild(el("p", { text: "Others going to the same event see: " + profile.first_name + " " + profile.last_name.charAt(0) + ". · " + profile.role + " · " + profile.experience + ". Never your email." }));
    if (!profile.home_state) card.appendChild(el("p", { style: "color:var(--acc)", text: "Add your home state (Edit profile) to get the Monday lineup for your area." }));
    card.appendChild(el("a", { class: "btn btn--solid", href: "/", style: "margin-right:8px", text: "← Back to events" }));
    card.appendChild(el("button", { class: "btn", text: "Edit profile", onclick: function () { root.innerHTML = ""; profileForm(root, null, false); } }));
    card.appendChild(el("button", { class: "btn", style: "margin-left:8px", text: "Sign out", onclick: function () { sb.auth.signOut().then(function () { location.reload(); }); } }));
    root.appendChild(card);
    inbox(root);
    connections(root);
  }

  function signIn(root, next) {
    var card = el("div", { class: "acct" });
    var email = el("input", { type: "email", autocomplete: "email", placeholder: "you@email.com" });
    var adult = el("input", { type: "checkbox" }), terms = el("input", { type: "checkbox" });
    var msg = el("div", { class: "msg" });
    var b = el("button", { class: "btn btn--solid", text: "Email me a sign-in link", onclick: function () {
      if (!/^\S+@\S+\.\S+$/.test(email.value)) return (msg.textContent = "Enter a real email.");
      if (!adult.checked || !terms.checked) return (msg.textContent = "Check both boxes to continue.");
      b.disabled = true;
      var back = location.origin + "/account/" + (next ? "?next=" + encodeURIComponent(next) : "");
      sb.auth.signInWithOtp({ email: email.value.trim(), options: { emailRedirectTo: back } }).then(function (r) {
        b.disabled = false;
        msg.textContent = r.error ? nice(r.error) : "Check your inbox for a link from Supabase Auth. It can take a minute (check spam too).";
      });
    } });
    [el("h3", { text: "Sign in or sign up" }),
     el("p", { text: "No password. We email you a link. Accounts let you say you're going to an event and connect with others going." }),
     el("label", { text: "Email" }), email,
     el("label", { class: "chk" }, [adult, " I'm 18 or older."]),
     el("label", { class: "chk" }, [terms, el("span", {}, ["I agree to the ", el("a", { href: "/terms/", text: "terms" }), " and ", el("a", { href: "/privacy/", text: "privacy policy" }), "."])]),
     b, msg].forEach(function (n) { card.appendChild(n); });
    root.appendChild(card);
  }

  function profileForm(root, next, isNew) {
    var p = profile || {};
    var card = el("div", { class: "acct" });
    function sel(opts, val) { var s = el("select"); opts.forEach(function (o) { var op = el("option", { text: o }); op.value = o; if (o === val) op.selected = true; s.appendChild(op); }); return s; }
    var fn = el("input", { type: "text", maxlength: "40", value: p.first_name || "", autocomplete: "given-name" });
    var ln = el("input", { type: "text", maxlength: "60", value: p.last_name || "", autocomplete: "family-name" });
    var role = sel(ROLES, p.role), exp = sel(EXP, p.experience);
    var co = el("input", { type: "text", maxlength: "80", value: p.company || "", placeholder: "Optional" });
    var show = el("input", { type: "checkbox" }); show.checked = !!p.show_company;
    var home = el("select"); home.appendChild(el("option", { value: "", text: "Outside the US / skip" }));
    Object.keys(STATES).sort(function (a, b) { return STATES[a].localeCompare(STATES[b]); }).forEach(function (k) {
      var o = el("option", { value: k, text: STATES[k] }); if (k === p.home_state) o.selected = true; home.appendChild(o); });
    var dig = el("input", { type: "checkbox" }); dig.checked = p.weekly_digest !== false;
    var ntf = el("input", { type: "checkbox" }); ntf.checked = p.notify !== false;
    var msg = el("div", { class: "msg" });
    var b = el("button", { class: "btn btn--solid", text: isNew ? "Save and continue" : "Save", onclick: function () {
      if (!fn.value.trim() || !ln.value.trim()) return (msg.textContent = "First and last name are required.");
      b.disabled = true;
      sb.from("profiles").upsert({ id: user.id, first_name: fn.value.trim(), last_name: ln.value.trim(), role: role.value, experience: exp.value,
        company: co.value.trim() || null, show_company: show.checked && !!co.value.trim(), is_adult: true,
        home_state: home.value || null, weekly_digest: dig.checked, notify: ntf.checked }).then(function (r) {
        b.disabled = false;
        if (r.error) return (msg.textContent = nice(r.error));
        location.href = next || "/account/";
      });
    } });
    [el("h3", { text: isNew ? "Finish your profile" : "Edit profile" }),
     el("p", { text: "Only people going to the same event see your first name, last initial, role and experience. Your full last name and email are only shared after you both accept a connect request." }),
     el("label", { text: "First name" }), fn, el("label", { text: "Last name" }), ln,
     el("label", { text: "Role" }), role, el("label", { text: "Experience" }), exp,
     el("label", { text: "Company" }), co,
     el("label", { class: "chk" }, [show, " Show my company to people I connect with (off by default)."]),
     el("label", { text: "Home state" }), home,
     el("label", { class: "chk" }, [dig, " Email me the Monday lineup for my state (one email a week)."]),
     el("label", { class: "chk" }, [ntf, " Email me when someone wants to connect, or accepts."]),
     b, msg].forEach(function (n) { card.appendChild(n); });
    root.appendChild(card);
  }

  function inbox(root) {
    sb.rpc("my_requests").then(function (r) {
      var list = r.data || [];
      var card = el("div", { class: "acct" }, [el("h3", { text: "Connect requests" + (list.length ? " (" + list.length + ")" : "") })]);
      if (!list.length) card.appendChild(el("p", { text: "None right now. Requests open a week before events you're going to." }));
      list.forEach(function (q) {
        function answer(s) { sb.from("connections").update({ status: s }).eq("id", q.id).then(function (x) { if (x.error) alert(nice(x.error)); accountPage(root); }); }
        card.appendChild(el("div", { class: "row" }, [
          el("div", {}, [el("b", { text: q.first_name + " " + q.last_initial + ". wants to connect" }),
            el("small", { text: q.role + " · " + q.experience + " · going to " + q.event_title + " (" + fmt(new Date(q.starts_at)) + ")" })]),
          el("div", {}, [el("button", { class: "btn btn--solid", text: "Accept", onclick: function () { answer("accepted"); } }),
            el("button", { class: "btn", style: "margin-left:6px", text: "Decline", onclick: function () { answer("declined"); } })])
        ]));
      });
      root.insertBefore(card, root.children[1] || null);
    });
  }

  function connections(root) {
    sb.rpc("my_connections").then(function (r) {
      var list = r.data || [];
      var card = el("div", { class: "acct" }, [el("h3", { text: "Your connections" }),
        el("p", { text: "Both of you said yes, so you can see each other's email. Say hi before the event." })]);
      if (!list.length) card.appendChild(el("p", { text: "No connections yet." }));
      list.forEach(function (c) {
        card.appendChild(el("div", { class: "row" }, [
          el("div", {}, [el("b", { text: c.first_name + " " + c.last_name }), el("small", { text: c.role + (c.company ? " at " + c.company : "") + " · met via " + c.event_title })]),
          el("a", { class: "btn", href: "mailto:" + c.email + "?subject=" + encodeURIComponent("Hey from The Lineup: " + c.event_title), text: c.email })
        ]));
      });
      root.appendChild(card);
      danger(root, true);
    });
  }

  function danger(root, real) {
    if (!real) return;
    var card = el("div", { class: "acct" }, [el("h3", { text: "Delete account" }),
      el("p", { text: "Deletes your profile, going list and connections for good." }),
      el("button", { class: "btn", text: "Delete my account", onclick: function () {
        if (prompt("Type DELETE to confirm") !== "DELETE") return;
        sb.rpc("delete_me").then(function (r) { if (r.error) return alert(nice(r.error)); sb.auth.signOut().then(function () { location.href = "/"; }); });
      } })]);
    root.appendChild(card);
  }

  /* ---------------- header link ---------------- */
  function headerLink() {
    var label = user ? (profile ? profile.first_name : "Finish profile") : "Sign in";
    var bar = document.querySelector('.bar__link[href="/account/"]');
    if (bar) { bar.textContent = label; return; }
    var top = document.querySelector(".top");
    if (!top || document.getElementById("acct-link")) return;
    var a = el("a", { id: "acct-link", href: "/account/", text: label,
      style: "float:right;font-size:.85rem;color:var(--soft);text-decoration:none;margin-top:-50px" });
    top.parentNode.insertBefore(a, top.nextSibling);
  }
  function hasSession() {
    try { for (var i = 0; i < localStorage.length; i++) if (/^sb-.*-auth-token$/.test(localStorage.key(i))) return true; } catch (e) {}
    return /access_token=|code=/.test(location.hash + location.search);
  }

  var box = document.getElementById("going"), acct = document.getElementById("account");
  // Pages with nothing account-related (like the homepage) only load the login library if you're signed in.
  if (!box && !acct && !document.getElementById("unsub") && !hasSession()) return;
  var unsub = document.getElementById("unsub");
  if (unsub) {
    loadLib(function () {
      sb = window.supabase.createClient(CFG.url, CFG.key);
      var q = new URLSearchParams(location.search), t = q.get("t"), what = q.get("w") || "all";
      if (!/^[0-9a-f-]{36}$/i.test(t || "")) { unsub.textContent = "That unsubscribe link looks broken. Change your emails from your account page."; return; }
      sb.rpc("unsubscribe", { token: t, what: what }).then(function (r) {
        unsub.textContent = r.error || !r.data ? "Couldn't find that subscription. Change your emails from your account page."
          : what === "digest" ? "Done. No more Monday emails. Connect emails still come." : "Done. You won't get emails from The Lineup anymore.";
      });
    });
    return;
  }
  boot(function () {
    if (acct) accountPage(acct);
    if (box) eventBox(box);
    headerLink();
  });
})();

/* ============ Telegram Downloader — JS (fetch + SSE) ============ */
(function () {
  "use strict";

  var selectedChat = null;
  var messagesCache = [];
  var pending = {};   // برای پاسخ‌های ناهمگام با id
  var seq = 0;

  function $(id) { return document.getElementById(id); }

  // ---------- API (fetch) ----------
  function callAPI(method, body) {
    return fetch("/api/" + method, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json(); });
  }

  // ---------- ناوبری ----------
  var PAGE_SUB = {
    login: "با شمارهٔ موبایل وارد شوید تا همهٔ چت‌ها، گروه‌ها و کانال‌ها را ببینید.",
    chats: "با کلیک روی هر چت آن را انتخاب کنید؛ با دوبار کلیک دانلودش شروع می‌شود.",
    download: "همهٔ پیام‌ها از اول تا آخر، مرتب و بدون تکراری دانلود می‌شوند.",
    android: "از خروجی، یک پروژهٔ اپ اندروید ساخته می‌شود.",
    log: "همهٔ رویدادها به‌صورت زنده اینجا ثبت می‌شوند."
  };
  var PAGE_TITLE = {
    login: "ورود به تلگرام",
    chats: "چت‌ها و گروه‌ها",
    download: "دانلود و خروجی",
    android: "ساخت اپ اندروید",
    log: "لاگ برنامه"
  };

  function showPage(name) {
    ["login", "chats", "download", "android", "log"].forEach(function (p) {
      $("page-" + p).classList.toggle("hidden", p !== name);
    });
    document.querySelectorAll(".nav-item").forEach(function (b) {
      b.classList.toggle("active", b.dataset.page === name);
    });
    $("pageTitle").textContent = PAGE_TITLE[name];
    $("pageSub").textContent = PAGE_SUB[name];
    setStatus("");
    if (name === "chats" && !messagesCache.length) loadChats();
    if (name === "android") refreshAndroid();
  }

  function setStatus(msg, kind) {
    var el = $("topStatus");
    el.textContent = msg || "";
    el.className = "top-status" + (kind ? " " + kind : "");
  }

  function setMsg(id, text, isErr) {
    var el = $(id);
    if (!el) return;
    el.textContent = text || "";
    el.className = "msg" + (isErr ? " err" : "");
  }

  document.querySelectorAll(".nav-item").forEach(function (b) {
    b.addEventListener("click", function () { showPage(b.dataset.page); });
  });

  // ---------- ورود ----------
  $("sendCodeBtn").addEventListener("click", function () {
    var phone = $("phone").value.trim();
    var ph = $("proxy_host").value.trim();
    var pp = $("proxy_port").value.trim();
    if (!phone) { setMsg("loginMsg", "شمارهٔ موبایل را وارد کنید (مثلاً 09929184925).", true); return; }
    this.disabled = true;
    setMsg("loginMsg", "در حال ارسال کد…");
    callAPI("config", { api_id: "", api_hash: "", phone: phone, proxy_host: ph, proxy_port: pp })
      .then(function () { return callAPI("send_code", { phone: phone }); })
      .then(function (r) {
        if (!r.ok) throw new Error(r.error);
        $("loginStep2").classList.remove("hidden");
        $("sendCodeBtn").disabled = false;
        setMsg("loginMsg", "کد ارسال شد ✅ — کد را وارد و «ورود» را بزنید.");
      })
      .catch(function (e) {
        $("sendCodeBtn").disabled = false;
        var m = e.message || "خطا";
        if (m.indexOf("FloodWait") !== -1) m = "تلگرام محدودیت موقت گذاشته — چند دقیقه صبر و دوباره تلاش کنید.";
        if (m.indexOf("PHONE_NUMBER_INVALID") !== -1) m = "شمارهٔ موبایل درست نیست (مثلاً 09929184925).";
        setMsg("loginMsg", "❌ " + m, true);
      });
  });

  $("loginBtn").addEventListener("click", function () {
    var phone = $("phone").value.trim();
    var code = $("code").value.trim();
    var password = $("password").value;
    this.disabled = true;
    setMsg("loginMsg", "در حال ورود…");
    callAPI("login", { phone: phone, code: code, password: password })
      .then(function (r) { if (!r.ok) throw new Error(r.error); })
      .catch(function (e) {
        $("loginBtn").disabled = false;
        setMsg("loginMsg", "❌ " + e.message, true);
      });
  });

  // ---------- چت‌ها ----------
  function loadChats() {
    $("refreshChats").disabled = true;
    setStatus("در حال دریافت چت‌ها…");
    callAPI("list_chats", {}).then(function (r) {
      if (!r.ok) { setStatus("❌ " + r.error, "err"); $("refreshChats").disabled = false; return; }
    });
  }
  $("refreshChats").addEventListener("click", loadChats);

  $("chatSearch").addEventListener("input", function () {
    var q = this.value.trim().toLowerCase();
    document.querySelectorAll(".chat-row").forEach(function (r) {
      r.style.display = (!q || r.dataset.title.toLowerCase().indexOf(q) !== -1) ? "" : "none";
    });
  });

  var TYPE_ICON = { user: "👤", group: "👥", channel: "📢", unknown: "💬" };
  var TYPE_COLOR = { user: "#1e88e5", group: "#43a047", channel: "#e53935", unknown: "#8a98a5" };
  var TYPE_NAME = { user: "گفتگوی خصوصی", group: "گروه", channel: "کانال", unknown: "چت" };

  function renderChats(list) {
    messagesCache = list;
    var box = $("chatList");
    box.innerHTML = "";
    $("refreshChats").disabled = false;
    if (!list.length) { box.innerHTML = '<div class="empty">هنوز چتی پیدا نشد.</div>'; return; }
    list.forEach(function (d) {
      var row = document.createElement("div");
      row.className = "chat-row";
      row.dataset.title = d.title;
      row.dataset.id = d.id;

      var icon = document.createElement("div");
      icon.className = "chat-icon";
      icon.textContent = TYPE_ICON[d.type] || "💬";
      icon.style.background = (TYPE_COLOR[d.type] || "#8a98a5") + "3d";

      var meta = document.createElement("div");
      meta.className = "chat-meta";
      var n = document.createElement("div"); n.className = "chat-name"; n.textContent = d.title;
      var sub = document.createElement("div"); sub.className = "chat-sub";
      sub.textContent = TYPE_NAME[d.type] || "چت";
      if (d.unread) sub.textContent += "  ·  " + d.unread + " جدید";
      meta.appendChild(n); meta.appendChild(sub);

      row.appendChild(icon); row.appendChild(meta);
      if (d.unread) {
        var b = document.createElement("div"); b.className = "chat-unread"; b.textContent = d.unread;
        row.appendChild(b);
      }
      row.addEventListener("click", function () {
        selectedChat = d;
        document.querySelectorAll(".chat-row.selected").forEach(function (x) { x.classList.remove("selected"); });
        row.classList.add("selected");
        $("dlChatLabel").textContent = "چت انتخاب‌شده: " + d.title + "  (" + (TYPE_NAME[d.type] || d.type) + ")";
      });
      row.addEventListener("dblclick", function () {
        selectedChat = d;
        $("dlChatLabel").textContent = "چت انتخاب‌شده: " + d.title + "  (" + (TYPE_NAME[d.type] || d.type) + ")";
        showPage("download");
      });
      box.appendChild(row);
    });
    setStatus(list.length + " چت دریافت شد ✅", "ok");
  }

  // ---------- دانلود ----------
  $("dlDirBtn").addEventListener("click", function () {
    callAPI("choose_dir", {}).then(function (r) { if (r.ok && r.result) $("dlDir").value = r.result; });
  });
  $("dlOpen").addEventListener("click", function () { callAPI("open_account_dir", {}); });

  $("dlStart").addEventListener("click", function () {
    if (!selectedChat) { setMsg("dlMsg", "اول از صفحهٔ «چت‌ها» یک چت را انتخاب کنید.", true); return; }
    var opts = { media: $("dlMedia").checked, text: $("dlText").checked };
    $("dlStart").disabled = true; $("dlStop").disabled = false;
    setMsg("dlMsg", "دانلود شروع شد…");
    callAPI("start_download", { chat: selectedChat, options: opts, dir: $("dlDir").value })
      .then(function (r) {
        if (!r.ok) { $("dlStart").disabled = false; setMsg("dlMsg", "❌ " + r.error, true); }
      });
  });
  $("dlStop").addEventListener("click", function () {
    callAPI("stop_download", {});
    $("dlStop").disabled = true;
    setMsg("dlMsg", "در حال توقف…");
  });
  $("dlExport").addEventListener("click", function () {
    this.disabled = true;
    setMsg("dlMsg", "در حال ساخت خروجی HTML…");
    callAPI("make_export", {});
  });

  // ---------- اندروید ----------
  function refreshAndroid() {
    callAPI("android_info", {}).then(function (r) {
      $("anSrc").textContent = r.ok && r.result ? "خروجی: " + r.result : "خروجی: هنوز خروجی‌ای ساخته نشده.";
    });
  }
  $("anBuild").addEventListener("click", function () {
    if (!selectedChat) { setMsg("anMsg", "از صفحهٔ «چت‌ها» یک چت را انتخاب کنید.", true); return; }
    this.disabled = true;
    setMsg("anMsg", "در حال ساخت پروژهٔ اندروید…");
    // فقط همین چت انتخاب‌شده داخل اپ می‌رود + نام اپ هم عنوان چت است
    callAPI("build_android", { chat: { id: selectedChat.id, title: selectedChat.title } });
  });
  $("anOpen").addEventListener("click", function () { callAPI("open_android_out", {}); });

  // ---------- لاگ ----------
  $("logClear").addEventListener("click", function () { $("logView").textContent = ""; });

  // ---------- رویدادهای زنده (SSE) ----------
  function onEvent(evt) {
    if (evt.type === "status") { setStatus(evt.text, evt.kind); return; }
    if (evt.type === "dl_status") { setMsg("dlMsg", evt.text, false); return; }
    if (evt.type === "dl_progress") {
      var p1 = evt.progress;
      if (p1 && p1.label) { $("msgBar").style.width = (p1.pct || 0) + "%"; $("msgBarLabel").textContent = p1.label; }
      if (evt.filePct !== undefined) { $("fileBar").style.width = evt.filePct + "%"; $("fileBarLabel").textContent = evt.fileLabel || ""; }
      return;
    }
    if (evt.type === "dl_done") {
      $("dlStart").disabled = false; $("dlStop").disabled = true; $("dlExport").disabled = false;
      setMsg("dlMsg", evt.text, evt.isErr);
      return;
    }
    if (evt.type === "login_check") { showPage(evt.ok ? "chats" : "login"); if (!evt.ok) setStatus("برای ادامه وارد شوید."); return; }
    if (evt.type === "login_ok") { $("loginBtn").disabled = false; setMsg("loginMsg", "خوش آمدید " + evt.name + " ✅"); showPage("chats"); return; }
    if (evt.type === "login_fail") {
      $("loginBtn").disabled = false;
      if (evt.err === "2FA") setMsg("loginMsg", "این حساب رمز دومرحله‌ای دارد — رمز را وارد کنید.");
      else setMsg("loginMsg", "❌ " + evt.err, true);
      return;
    }
    if (evt.type === "chats_loaded") { renderChats(JSON.parse(evt.chats)); return; }
    if (evt.type === "android_ok") { $("anBuild").disabled = false; setMsg("anMsg", "✅ پروژه ساخته شد: " + evt.project); return; }
    if (evt.type === "android_fail") { $("anBuild").disabled = false; setMsg("anMsg", "❌ " + evt.error, true); return; }
    if (evt.type === "log") { var v = $("logView"); v.textContent += evt.text + "\n"; v.scrollTop = v.scrollHeight; return; }
  }

  function connectSSE() {
    var es = new EventSource("/api/events");
    es.onmessage = function (msg) {
      try { onEvent(JSON.parse(msg.data)); } catch (e) {}
    };
    es.onerror = function () { /* خودکار دوباره وصل می‌شود */ };
  }

  // ---------- شروع ----------
  function start() {
    // پر کردن فیلدها از تنظیمات ذخیره‌شده
    fetch("/api/config").then(function (r) { return r.json(); }).then(function (r) {
      if (!r.ok) return;
      var c = r.result;
      if (c.phone) $("phone").value = c.phone;
      if (c.proxy_host) $("proxy_host").value = c.proxy_host;
      if (c.proxy_port) $("proxy_port").value = c.proxy_port;
      if (c.export_root) $("dlDir").value = c.export_root;
    }).catch(function () {});

    connectSSE();
    // بررسی نشست قبلی — نتیجه با رویداد login_check می‌آید
    callAPI("logged_in", {});
  }

  document.addEventListener("DOMContentLoaded", start);
})();
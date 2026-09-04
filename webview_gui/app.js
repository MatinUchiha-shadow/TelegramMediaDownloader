/* ===== Telegram Media Downloader — JS ===== */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };

  // هر بار در لحظهٔ فراخوانی، bridge را مستقیم می‌خوانیم (pywebview گاهی
  // `window.pywebview.api` را بعد از لود کامل صفحه متصل می‌کند؛ کش کردن آن در
  // ابتدای اسکریپت باعث می‌شود متدها «در دسترس نباشند»).
  function currentApi() {
    return (typeof window !== "undefined" && window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
  }

  // صدا زدن یک متد از backend. pywebview همهٔ فراخوانی‌ها را به‌صورت
  // Promise برمی‌گرداند، پس خروجی همیشه قابل await/`.then` است.
  function callPy(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    return new Promise(function (resolve, reject) {
      var tries = 0;
      function attempt() {
        var a = currentApi();
        if (a && typeof a[method] === "function") {
          try {
            var r = a[method].apply(a, args);
            resolve(Promise.resolve(r));
          } catch (e) {
            reject(e);
          }
          return;
        }
        tries++;
        if (tries >= 20) {
          reject(new Error("پایتون در دسترس نیست"));
        } else {
          setTimeout(attempt, 250);
        }
      }
      attempt();
    });
  }

  function setStatus(t) { $("status").textContent = t; }
  function setMsg(t, isErr) {
    $("loginMsg").textContent = t || "";
    $("loginMsg").className = "msg" + (isErr ? " err" : "");
  }

  // ---------- ناوبری و صفحه‌بندی ----------
  var loggedIn = false;
  var PAGES = {
    browse: "Browse",
    chats: "My Chats",
    downloads: "Downloads",
    api: "API",
    logs: "Logs",
  };

  var logTimer = null;
  function loadLogs() {
    var el = $("logView");
    var msgEl = $("logsMsg");
    if (msgEl) { msgEl.textContent = "Loading…"; msgEl.className = "msg"; }
    callPy("get_logs", 300).then(function (res) {
      if (!el) return;
      if (!res || typeof res !== "object") { if (msgEl) { msgEl.textContent = "Unexpected response."; msgEl.className = "msg err"; } return; }
      if (res.error) { if (msgEl) { msgEl.textContent = "❌ " + res.error; msgEl.className = "msg err"; } return; }
      var lines = res.lines || [];
      if (msgEl) msgEl.textContent = "";
      el.textContent = lines.join("\n") || "No logs yet.";
      el.scrollTop = el.scrollHeight;
    }).catch(function (e) {
      if (msgEl) { msgEl.textContent = "❌ " + (e.message || "Error"); msgEl.className = "msg err"; }
    });
  }

  function showPage(name) {
    document.querySelectorAll(".nav-item[data-page]").forEach(function (x) { x.classList.remove("active"); });
    var navBtn = document.querySelector('.nav-item[data-page="' + name + '"]');
    if (navBtn) navBtn.classList.add("active");
    $("pageTitle").textContent = PAGES[name] || name;
    $("pageBrowse").style.display = (name === "browse") ? "" : "none";
    $("pageChats").style.display = (name === "chats") ? "" : "none";
    $("pageLogs").style.display = (name === "logs") ? "" : "none";
    if (logTimer) { clearInterval(logTimer); logTimer = null; }
    if (name === "chats") {
      if (!loggedIn) {
        setStatus("Not logged in — go to Browse and log in first.");
      } else {
        loadChats();
      }
    }
    if (name === "logs") {
      loadLogs();
      logTimer = setInterval(loadLogs, 2000);
    }
  }

  document.querySelectorAll(".nav-item[data-page]").forEach(function (b) {
    b.addEventListener("click", function () { showPage(b.dataset.page); });
  });

  // ---------- ورود ----------
  var codeSent = false;

  function setLoginStep(sent) {
    codeSent = sent;
    $("sendCodeBtn").style.display = sent ? "none" : "";
    $("verifyBtn").style.display = sent ? "" : "none";
    $("code").disabled = !sent;
    $("password").disabled = !sent;
    $("loginHelper").textContent = sent
      ? "Enter the code you received, then press Verify."
      : "Enter your phone number to log in";
  }

  function setLoggedInState(on) {
    loggedIn = on;
    if (on) {
      $("loginCard").style.display = "none";
      setMsg("Logged in ✅");
      setStatus("Logged in — open My Chats to see your chats.");
    } else {
      $("loginCard").style.display = "";
      setLoginStep(false);
    }
  }

  $("sendCodeBtn").addEventListener("click", function () {
    var phone = $("phone").value.trim();
    if (!phone) { setMsg("Enter your phone number first.", true); return; }
    var btn = $("sendCodeBtn");
    btn.disabled = true;
    setMsg("Sending code…");
    callPy("set_phone", phone).then(function () {
      return callPy("send_code", phone);
    }).then(function (res) {
      btn.disabled = false;
      if (res && typeof res === "object" && res.error) {
        throw new Error(res.error);
      }
      setLoginStep(true);
      setMsg("Code sent ✅ — enter it and press Verify.");
      setStatus("Code sent — waiting for code…");
    }).catch(function (e) {
      btn.disabled = false;
      setMsg(e.message || "Error", true);
      setStatus("Failed to send code");
    });
  });

  function doLogin() {
    var phone = $("phone").value.trim();
    var code = $("code").value.trim();
    var password = $("password").value;
    if (!phone) { setMsg("Enter your phone number first.", true); return; }
    if (!code) { setMsg("Enter the code you received.", true); return; }
    var btn = $("verifyBtn");
    btn.disabled = true;
    setMsg("Logging in…");
    callPy("login", phone, code, password).then(function (res) {
      btn.disabled = false;
      if (res && typeof res === "object" && res.error) {
        var m = res.error;
        if (String(m).indexOf("2FA") !== -1 || String(m).indexOf("password") !== -1) {
          $("password").disabled = false;
          setMsg("This account has 2FA — enter your password above, then Verify.", true);
        } else if (String(m).indexOf("FloodWait") !== -1) {
          setMsg("Telegram rate-limit — wait a bit and retry.", true);
        } else {
          setMsg(m, true);
        }
        return;
      }
      setLoggedInState(true);
      setStatus("Logged in — open My Chats to see your chats.");
    }).catch(function (e) {
      btn.disabled = false;
      setMsg(e.message || "Error", true);
    });
  }

  $("verifyBtn").addEventListener("click", doLogin);
  $("code").addEventListener("keydown", function (e) { if (e.key === "Enter") doLogin(); });
  $("password").addEventListener("keydown", function (e) { if (e.key === "Enter") doLogin(); });

  // ---------- My Chats ----------
  var chatCache = null;

  function loadChats() {
    var listEl = $("chatList");
    var msgEl = $("chatsMsg");
    msgEl.textContent = "Loading chats…";
    msgEl.className = "msg";
    callPy("get_dialogs").then(function (res) {
      if (!res || typeof res !== "object") { msgEl.textContent = "Unexpected response."; msgEl.className = "msg err"; return; }
      if (res.error) {
        msgEl.textContent = "❌ " + res.error;
        msgEl.className = "msg err";
        return;
      }
      var dialogs = res.dialogs || [];
      chatCache = dialogs;
      listEl.innerHTML = "";
      if (!dialogs.length) {
        msgEl.textContent = "No chats found.";
        msgEl.className = "msg";
        return;
      }
      msgEl.textContent = "";
      dialogs.forEach(function (d) {
        var item = document.createElement("div");
        item.className = "chat-item";
        var icon = d.type === "channel" ? "📢" : (d.type === "group" ? "👥" : "👤");
        var unread = d.unread ? ' <span class="s">' + d.unread + " new</span>" : "";
        var dl = document.createElement("button");
        dl.className = "btn ghost chat-dl";
        dl.textContent = "📱 Android";
        dl.title = "دانلود کامل (متن + عکس/ویدیو/فایل)";
        dl.addEventListener("click", function (ev) {
          ev.stopPropagation();
          buildAndroid(d, true);
        });
        var dlTxt = document.createElement("button");
        dlTxt.className = "btn ghost chat-dl";
        dlTxt.textContent = "📱 متن فقط";
        dlTxt.title = "فقط متن/پیام‌ها (سریع، بدون فایل) — برای اینترنت کند";
        dlTxt.addEventListener("click", function (ev) {
          ev.stopPropagation();
          buildAndroid(d, false);
        });
        item.appendChild(document.createTextNode(""));
        item.innerHTML = '<span class="t">' + icon + "&nbsp; " + escapeHtml(d.title) + "</span>" + unread;
        item.appendChild(dlTxt);
        item.appendChild(dl);
        item.title = "id: " + d.id + " — type: " + d.type;
        item.addEventListener("click", function () {
          setStatus("Selected: " + d.title);
          $("channel").value = String(d.title);
          showPage("browse");
        });
        listEl.appendChild(item);
      });
      setStatus(res.self_name ? "Logged in as " + res.self_name : "Chats loaded");
    }).catch(function (e) {
      msgEl.textContent = "❌ " + (e.message || "Error");
      msgEl.className = "msg err";
    });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  $("refreshChatsBtn").addEventListener("click", function () {
    if (!loggedIn) { setStatus("Not logged in yet."); return; }
    loadChats();
  });

  $("refreshLogsBtn").addEventListener("click", function () { loadLogs(); });

  // ساخت اپ اندروید برای یک چت: دانلود کامل → خروجی → پروژهٔ اندروید
  // دانلود در پس‌زمینه شروع می‌شود و هر ۲ ثانیه پیشرفت خوانده می‌شود که
  // برنامه «گیر کرده» به نظر نرسد.
  var buildTimer = null;
  // نمونه‌های پیشرفت برای تخمین زمان باقی‌مانده (ETA) — پنجره ۶۰ ثانیه اخیر
  var etaSamples = [];
  function fmtEta(sec) {
    if (sec < 45) return "کمتر از یک دقیقه";
    var m = Math.round(sec / 60);
    if (m < 60) return "≈ " + m + " دقیقه";
    var h = Math.floor(m / 60), mm = m % 60;
    return "≈ " + h + " ساعت" + (mm ? " و " + mm + " دقیقه" : "");
  }
  function updateEta(p) {
    var now = Date.now();
    if (p.state !== "downloading" || !p.total) {
      if (p.state === "done" || p.state === "error") etaSamples = [];
      return "";
    }
    var last = etaSamples[etaSamples.length - 1];
    if (last && p.done < last.done) etaSamples = []; // شروع دانلود جدید
    etaSamples.push({ t: now, done: p.done });
    while (etaSamples.length > 30) etaSamples.shift(); // حداکثر ~۶۰ ثانیه
    if (etaSamples.length < 3) return "⏳ در حال محاسبه زمان باقی‌مانده…";
    var f = etaSamples[0], l = etaSamples[etaSamples.length - 1];
    var dt = (l.t - f.t) / 1000;
    if (dt < 5) return "⏳ در حال محاسبه زمان باقی‌مانده…";
    var rate = (l.done - f.done) / dt;
    if (!(rate > 0)) return "⏳ در حال محاسبه زمان باقی‌مانده…";
    var rem = Math.max(0, Math.round((p.total - l.done) / rate));
    return "⏱ " + fmtEta(rem) + " مانده";
  }
  function buildAndroid(d, includeMedia) {
    var msgEl = $("chatsMsg");
    msgEl.className = "msg";
    etaSamples = []; // ریست تخمین برای ساخت جدید
    msgEl.textContent = "⏳ " + (includeMedia ? "Downloading all of " : "Downloading messages of ") + "\"" + d.title + "\"…";
    setStatus("Building Android app for " + d.title + " …");
    callPy("start_build", d.id, !!includeMedia).then(function (res) {
      if (res && res.error) {
        msgEl.textContent = "❌ " + res.error;
        msgEl.className = "msg err";
        setStatus("Failed");
        return;
      }
      // poll پیشرفت
      if (buildTimer) clearInterval(buildTimer);
      buildTimer = setInterval(function () {
        callPy("get_build_progress").then(function (p) {
          if (!p) return;
          if (p.state === "downloading") {
            var pct = p.total ? Math.round(p.done / p.total * 100) : 0;
            // حسب سرعت اینترنت‌ات فایل‌های بزرگ ممکن است طول بکشد؛ نشان می‌دهیم زنده است
            var spd = (p.mb != null) ? "\n⬇ " + p.mb + " مگابایت • " + p.rate + "MB/s" : "";
            var eta = updateEta(p);
            msgEl.textContent = "⏳ " + d.title + ": " + p.label + " — " + pct + "% (" + p.done + "/" + p.total + ")" + spd + (eta ? "\n" + eta : "") + "\n"
              + "این می‌تواند چند دقیقه طول بکشد — برنامه در حال کار است.";
          } else if (p.state === "building") {
            msgEl.textContent = "🔨 " + p.label + " (" + d.title + ")";
          } else if (p.state === "done") {
            clearInterval(buildTimer); buildTimer = null;
            callPy("get_build_result").then(function (r) {
              if (r && r.error) { msgEl.textContent = "❌ " + r.error; msgEl.className = "msg err"; return; }
              var st = (r && r.stats) || {};
              var lines = "✅ Android app built for \"" + d.title + "\": " + st.messages + " messages, " + st.media + " media.";
              if (r.apk) {
                lines += "\n📱 APK (قابل نصب مستقیم): " + r.apk;
              } else if (r.project_name) {
                lines += "\nName: " + r.project_name + "\nZIP: " + r.zip;
              }
              msgEl.textContent = lines;
              setStatus("Android app ready ✅");
            });
          } else if (p.state === "error") {
            clearInterval(buildTimer); buildTimer = null;
            callPy("get_build_result").then(function (r) {
              msgEl.textContent = "❌ " + ((r && r.error) || p.label || "Error");
              msgEl.className = "msg err";
              setStatus("Failed");
            });
          }
        }).catch(function () {});
      }, 2000);
    }).catch(function (e) {
      msgEl.textContent = "❌ " + (e.message || "Error");
      msgEl.className = "msg err";
      setStatus("Failed");
    });
  }

  // ---------- Channel ----------
  $("browseBtn").addEventListener("click", function () {
    var ch = $("channel").value.trim();
    if (!ch) { setStatus("Enter @username or link first."); return; }
    setStatus("Browsing " + ch + " …");
    callPy("browse_channel", ch).then(function (res) {
      if (res && res.error) setStatus("❌ " + res.error);
      else setStatus(res && res.dialogs ? "Found " + res.dialogs.length + " chats." : "Done.");
    }).catch(function (e) { setStatus("❌ " + e.message); });
  });

  $("exportBtn").addEventListener("click", function () {
    setStatus("Exporting…");
    callPy("export_all").then(function (res) {
      if (res && res.error) setStatus("❌ " + res.error);
      else setStatus("Export complete ✅");
    }).catch(function (e) { setStatus("❌ " + e.message); });
  });

  $("allBtn").addEventListener("click", function () {
    $("channel").value = "@" + ($("channel").value.replace(/\s+/g, "").replace(/^@/, ""));
    setStatus("All filter selected.");
  });

  $("openBtn").addEventListener("click", function () {
    setStatus("Opening folder…");
    callPy("open_folder").catch(function () {});
  });

  $("pathBtn").addEventListener("click", function () {
    callPy("choose_save_dir").then(function (p) { if (p) $("savePath").value = p; });
  });

  // ---------- تنظیمات / API ----------
  function loadSettings() {
    callPy("get_config").then(function (raw) {
      var c = (raw && typeof raw === "object") ? raw : {};
      $("apiId").value = c.api_id || "";
      $("apiHash").value = c.api_hash || "";
      $("proxyHost").value = c.proxy_host || "";
      $("proxyPort").value = c.proxy_port || "";
    }).catch(function () {});
  }

  $("settingsBtn").addEventListener("click", function () {
    var sc = $("settingsCard");
    var show = sc.style.display === "block";
    sc.style.display = show ? "none" : "block";
    if (!show) loadSettings();
    setStatus("Settings");
  });

  $("saveApiBtn").addEventListener("click", function () {
    $("apiMsg").textContent = "";
    $("apiMsg").className = "msg";
    callPy("set_api_config",
      $("apiId").value.trim(),
      $("apiHash").value.trim(),
      $("proxyHost").value.trim() || "127.0.0.1",
      $("proxyPort").value.trim() || "10808"
    ).then(function () {
      $("apiMsg").textContent = "Saved ✅";
      $("apiMsg").className = "msg";
      setStatus("Settings saved");
    }).catch(function (e) {
      $("apiMsg").textContent = e.message || "Error";
      $("apiMsg").className = "msg err";
    });
  });

  $("logoutBtn").addEventListener("click", function () {
    callPy("logout").then(function () {
      chatCache = null;
      setLoggedInState(false);
      setMsg("Logged out.");
      showPage("browse");
    }).catch(function () {});
  });

  // ---------- مقدار دهی اولیه: ورود خودکار ----------
  setStatus("Loading…");
  loadSettings();
  callPy("get_login_state").then(function (res) {
    if (res && res.logged_in) {
      setLoggedInState(true);
      setStatus("Welcome back — open My Chats to see your chats.");
      if ($("phone").value.trim() === "" && res.phone) $("phone").value = res.phone;
    } else {
      setStatus("Ready — enter your phone to log in.");
    }
  }).catch(function () {
    setStatus("Ready");
  });
})();
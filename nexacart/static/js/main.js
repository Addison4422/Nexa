/* =====================================================================
   NEXACART - front end behaviour
   Progressive enhancement only: every feature below keeps working
   without JavaScript, this file simply removes friction.
   The interface is translated, so no rule or label is hard coded here:
   the server sends stable identifiers (data-rule) and the wording that
   belongs to the active language (data-text-* / data-label-*).
   ===================================================================== */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    initThemeToggle();
    initDismissAlerts();
    initPasswordToggles();
    initPasswordMeter();
    initPasswordGenerator();
    initConfirmPassword();
    initFormGuards();
    initConfirmModal();
    initHeaderMenu();
    initRoleChange();
    initAddToCart();
    initCartControls();
    initFavorites();
  });

  /* ---------- favourite (heart) buttons ---------------------------- */
  function initFavorites() {
    document.querySelectorAll(".fav-btn").forEach(function (button) {
      button.addEventListener("click", function () {
        fetch(button.getAttribute("data-fav-url"), {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": (document.querySelector("meta[name=csrf-token]") || {}).content ||
                            (document.querySelector("input[name=csrf_token]") || {}).value || ""
          }
        }).then(function (r) { return r.json(); }).then(function (payload) {
          if (!payload || payload.ok === false) {
            window.alert(payload && payload.error ? payload.error : "error");
            return;
          }
          button.classList.toggle("is-fav", !!payload.favorite);
          button.classList.remove("fav-pulse");
          void button.offsetWidth; /* restart the animation */
          button.classList.add("fav-pulse");
          var label = payload.favorite
            ? button.getAttribute("data-label-remove")
            : button.getAttribute("data-label-add");
          if (label) {
            button.setAttribute("aria-label", label);
            button.setAttribute("title", label);
          }
          /* on the favourites page, removing takes the card away */
          if (!payload.favorite && button.hasAttribute("data-fav-page")) {
            var card = button.closest(".product-card");
            if (card) card.remove();
          }
        }).catch(function () { /* offline: ignore */ });
      });
    });
  }

  /* ---------- colour theme ---------------------------------------- */
  function initThemeToggle() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;

    button.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        var key = root.getAttribute("data-theme-key") || "nexacart-theme";
        localStorage.setItem(key, next);
      } catch (error) {
        /* storage unavailable - the choice simply is not remembered */
      }
      var label = next === "dark"
        ? button.getAttribute("data-label-light")
        : button.getAttribute("data-label-dark");
      if (label) {
        button.setAttribute("aria-label", label);
        button.setAttribute("title", label);
      }
    });
  }

  /* ---------- dismissible flash messages --------------------------- */
  function initDismissAlerts() {
    document.querySelectorAll("[data-dismiss-alert]").forEach(function (button) {
      button.addEventListener("click", function () {
        var alert = button.closest(".alert");
        if (alert) alert.remove();
      });
    });
  }

  /* ---------- show / hide password -------------------------------- */
  function initPasswordToggles() {
    document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
      button.addEventListener("click", function () {
        var field = document.getElementById(button.getAttribute("data-toggle-password"));
        if (!field) return;
        var hidden = field.type === "password";
        field.type = hidden ? "text" : "password";
        var label = hidden
          ? button.getAttribute("data-label-hide")
          : button.getAttribute("data-label-show");
        if (label) {
          button.setAttribute("aria-label", label);
          button.setAttribute("title", label);
        }
      });
    });
  }

  /* ---------- live password strength checklist --------------------- */
  /* The rule identifiers are stable in every language, the wording is not. */
  var RULES = {
    min_length: function (value, limits) { return value.length >= limits.min; },
    max_length: function (value, limits) { return value.length <= limits.max; },
    lowercase: function (value) { return /[a-z]/.test(value); },
    uppercase: function (value) { return /[A-Z]/.test(value); },
    digit: function (value) { return /[0-9]/.test(value); },
    symbol: function (value) { return /[^a-zA-Z0-9]/.test(value); }
  };

  function readLimits(scope) {
    var form = scope.closest("form") || scope;
    var min = parseInt(form.getAttribute("data-password-min"), 10);
    var max = parseInt(form.getAttribute("data-password-max"), 10);
    return {
      min: isNaN(min) ? 8 : min,
      max: isNaN(max) ? 128 : max
    };
  }

  function initPasswordMeter() {
    var lists = document.querySelectorAll("#password-rules");
    if (!lists.length) return;

    lists.forEach(function (list) {
      var form = list.closest("form");
      var passwordField = form && form.querySelector(
        'input[type="password"][name="password"], input[type="password"][name="new_password"]'
      );
      if (!passwordField) return;

      var limits = readLimits(list);

      passwordField.addEventListener("input", function () {
        var value = passwordField.value;
        list.querySelectorAll(".rule").forEach(function (item) {
          var key = item.getAttribute("data-rule");
          var test = RULES[key];
          var met = test ? test(value, limits) : false;
          item.classList.toggle("is-met", met);
          var mark = item.querySelector(".rule-mark");
          if (mark) mark.textContent = met ? "✓" : "×";
        });
      });
    });
  }

  /* ---------- password generator ---------------------------------- */
  function initPasswordGenerator() {
    document.querySelectorAll("[data-generate-password]").forEach(function (button) {
      button.addEventListener("click", function () {
        var form = button.closest("form");
        if (!form) return;
        var field = form.querySelector('input[name="password"], input[name="new_password"]');
        var confirmField = form.querySelector('input[name="confirm_password"]');
        if (!field) return;

        var alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*?";
        var value = "";
        for (var i = 0; i < 14; i += 1) {
          value += alphabet[Math.floor(Math.random() * alphabet.length)];
        }
        field.value = value;
        field.type = "text";
        field.dispatchEvent(new Event("input", { bubbles: true }));
        if (confirmField) {
          confirmField.value = value;
          confirmField.dispatchEvent(new Event("input", { bubbles: true }));
        }
        field.focus();
      });
    });
  }

  /* ---------- confirm password ------------------------------------ */
  function initConfirmPassword() {
    var status = document.querySelector("[data-match-status]");
    if (!status) return;

    var form = status.closest("form");
    var password = form.querySelector('input[name="password"], input[name="new_password"]');
    var confirm = form.querySelector('input[name="confirm_password"]');
    if (!password || !confirm) return;

    function compare() {
      if (!confirm.value) {
        status.textContent = status.getAttribute("data-text-empty") || "";
        status.classList.remove("is-ok", "is-bad");
        return;
      }
      var same = password.value === confirm.value;
      status.textContent = same
        ? (status.getAttribute("data-text-match") || "")
        : (status.getAttribute("data-text-mismatch") || "");
      status.classList.toggle("is-ok", same);
      status.classList.toggle("is-bad", !same);
    }

    password.addEventListener("input", compare);
    confirm.addEventListener("input", compare);
  }

  /* ---------- confirm destructive actions -------------------------- */
  function initFormGuards() {
    document.querySelectorAll("form[data-confirm], a[data-confirm]").forEach(function (element) {
      element.addEventListener(element.tagName === "FORM" ? "submit" : "click", function (event) {
        if (!window.confirm(element.getAttribute("data-confirm"))) {
          event.preventDefault();
        }
      });
    });
  }

  /* ---------- confirmation modal (sign out, delete, role change) --- */
  function initConfirmModal() {
    var modal = document.getElementById("confirm-modal");
    var form = document.getElementById("confirm-modal-form");
    var message = document.getElementById("confirm-modal-message");
    var closeButtons = document.querySelectorAll("[data-confirm-modal-close]");
    var trigger = null;

    function open() {
      if (!modal || !trigger) return;
      modal.classList.add("is-visible");
      modal.setAttribute("aria-hidden", "false");
      if (message) message.textContent = trigger.getAttribute("data-confirm") || "";
      var action = trigger.getAttribute("href") || trigger.getAttribute("data-action") || "";
      var method = trigger.getAttribute("data-method") || "post";
      if (form) {
        form.action = action;
        form.setAttribute("method", method);
      }
    }

    function close() {
      if (!modal) return;
      modal.classList.remove("is-visible");
      modal.setAttribute("aria-hidden", "true");
      trigger = null;
      if (message) message.textContent = "";
      if (form) form.action = "";
    }

    document.querySelectorAll("[data-confirm-modal]").forEach(function (button) {
      button.addEventListener("click", function () {
        trigger = button;
        open();
      });
    });

    closeButtons.forEach(function (button) {
      button.addEventListener("click", close);
    });

    modal.addEventListener("click", function (event) {
      if (event.target === modal.querySelector(".modal-overlay")) close();
    });
  }

  /* ---------- add-to-cart (catalogue & product page) --------------- */
  function initAddToCart() {
    document.querySelectorAll(".add-to-cart-form").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var button = form.querySelector('button[type="submit"]');
        var original = button.textContent;
        button.disabled = true;
        button.textContent = form.getAttribute("data-text-adding") || "...";
        fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" }
        }).then(function (r) { return r.json(); }).then(function (payload) {
          if (payload.ok) {
            var badge = document.querySelector(".cart-badge");
            if (badge) badge.textContent = payload.cart_count;
            button.textContent = form.getAttribute("data-text-added") || "OK";
            setTimeout(function () {
              button.textContent = original;
              button.disabled = false;
            }, 1200);
          } else {
            window.alert(payload.error || form.getAttribute("data-text-error") || "error");
            button.disabled = false;
            button.textContent = original;
          }
        }).catch(function () {
          window.alert(form.getAttribute("data-text-error") || "error");
          button.disabled = false;
          button.textContent = original;
        });
      });
    });
  }

  /* ---------- cart quantity / remove controls ---------------------- */
  function initCartControls() {
    var body = document.getElementById("cart-body");
    if (!body) return;
    var form = document.getElementById("cart-form");
    var csrf = form ? (form.querySelector('input[name="csrf_token"]') || {}).value || "" : "";
    var updateTpl = form ? form.getAttribute("data-update-template") : null;
    var removeTpl = form ? form.getAttribute("data-remove-template") : null;
    var subtotalEl = document.getElementById("cart-subtotal");
    var badge = document.querySelector(".cart-badge");

    function postJson(url, formData) {
      return fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRF-Token": csrf,
          "X-Requested-With": "XMLHttpRequest"
        },
        body: formData
      }).then(function (r) { return r.json(); }).then(function (payload) {
        if (!payload || payload.ok === false) {
          throw new Error((payload && payload.error) || "request failed");
        }
        return payload;
      });
    }

    function render(payload) {
      var cart = payload && payload.cart ? payload.cart : null;
      if (!cart || !updateTpl) { window.location.reload(); return; }
      body.innerHTML = "";
      var minusIcon = (document.querySelector(".tpl-minus") || {}).innerHTML || "";
      var plusIcon = (document.querySelector(".tpl-plus") || {}).innerHTML || "";
      var trashIcon = (document.querySelector(".tpl-trash") || {}).innerHTML || "";
      var totalQty = 0;
      cart.items.forEach(function (line) {
        var row = document.createElement("tr");
        row.setAttribute("data-cart-id", line.cart_id);
        var imageHtml = "";
        if (line.product.image_path) {
          var img = document.createElement("img");
          img.className = "product-thumb";
          img.alt = "";
          img.src = line.product.image_url;
          imageHtml = img.outerHTML;
        }
        var stockLabel = line.product.stock_quantity <= 0
          ? (form.getAttribute("data-label-out") || "")
          : (form.getAttribute("data-label-stock") || "").replace("{n}", line.product.stock_quantity);
        totalQty += line.quantity;
        row.innerHTML =
          '<td><div class="cell-user">' + imageHtml +
          '<div class="mini-main"><div class="mini-title"></div>' +
          '<div class="muted small"></div></div></div></td>' +
          '<td class="price-cell" style="text-align:end">' + line.price_display + '</td>' +
          '<td><div class="qty-control">' +
          '<button class="qty-btn qty-minus" type="button" data-cart-id="' + line.cart_id + '">' + minusIcon + '</button>' +
          '<input class="qty-input" type="number" min="1" max="' + line.product.stock_quantity +
          '" value="' + line.quantity + '" data-cart-id="' + line.cart_id + '">' +
          '<button class="qty-btn qty-plus" type="button" data-cart-id="' + line.cart_id + '">' + plusIcon + '</button>' +
          '</div></td>' +
          '<td class="subtotal-cell" style="text-align:end">' + line.subtotal_display + '</td>' +
          '<td class="cell-actions"><button class="btn btn-ghost btn-sm remove-item" type="button" data-cart-id="' + line.cart_id + '">' + trashIcon + '</button></td>';
        row.querySelector(".mini-title").textContent = line.product.name;
        row.querySelector(".muted.small").textContent = stockLabel;
        body.appendChild(row);
      });
      if (subtotalEl) subtotalEl.textContent = cart.subtotal_display;
      if (badge) badge.textContent = totalQty;
    }

    function cartId(el) { return el.getAttribute("data-cart-id"); }

    body.addEventListener("click", function (event) {
      var plus = event.target.closest(".qty-plus");
      var minus = event.target.closest(".qty-minus");
      var remove = event.target.closest(".remove-item");
      if (!plus && !minus && !remove) return;
      var id = cartId(plus || minus || remove);
      if (remove) {
        postJson(removeTpl.replace("0", id), "").then(render).catch(function () { window.location.reload(); });
        return;
      }
      var row = body.querySelector('tr[data-cart-id="' + id + '"]');
      var input = row ? row.querySelector(".qty-input") : null;
      var current = input ? parseInt(input.value, 10) : 1;
      var quantity = plus ? current + 1 : current - 1;
      if (quantity < 1) {
        postJson(removeTpl.replace("0", id), "").then(render).catch(function () { window.location.reload(); });
        return;
      }
      postJson(updateTpl.replace("0", id), "quantity=" + encodeURIComponent(quantity))
        .then(render)
        .catch(function () { window.alert(form.getAttribute("data-text-error") || "error"); });
    });

    body.addEventListener("change", function (event) {
      if (!event.target.classList.contains("qty-input")) return;
      var id = cartId(event.target);
      var quantity = parseInt(event.target.value, 10) || 1;
      postJson(updateTpl.replace("0", id), "quantity=" + encodeURIComponent(quantity))
        .then(render)
        .catch(function () { window.alert(form.getAttribute("data-text-error") || "error"); window.location.reload(); });
    });
  }

  /* ---------- header dropdown menu (⋯) ------------------------------ */
  function initHeaderMenu() {
    var toggle = document.getElementById("menu-toggle");
    var menu = document.getElementById("header-menu");
    if (!toggle || !menu) return;
    function close() {
      menu.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    }
    toggle.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = !menu.hidden;
      menu.hidden = open;
      toggle.setAttribute("aria-expanded", String(!open));
    });
    document.addEventListener("click", function (event) {
      if (!menu.hidden && !menu.contains(event.target)) close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !menu.hidden) close();
    });
  }

  /* ---------- role change: password needed only for admin ---------- */
  function initRoleChange() {
    var select = document.getElementById("role");
    var field = document.getElementById("admin-password-field");
    var note = document.getElementById("role-change-note");
    if (!select || !field) return;
    function update() {
      var isAdminRole = select.value === "admin";
      field.hidden = !isAdminRole;
      var input = field.querySelector("input");
      if (input) input.required = isAdminRole;
      if (note) note.hidden = isAdminRole;
    }
    select.addEventListener("change", update);
    update();
  }

})();

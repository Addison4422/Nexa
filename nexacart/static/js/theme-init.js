/* NEXACART - theme bootstrap (loaded before first paint to avoid a flash) */
(function () {
  "use strict";
  var user = document.documentElement.getAttribute("data-user") || "guest";
  var key = "nexacart-theme:" + user;
  var theme = null;
  try {
    theme = localStorage.getItem(key) || localStorage.getItem("nexacart-theme");
    if (theme) {
      /* migrate the old shared key to the per-account key */
      localStorage.setItem(key, theme);
      localStorage.removeItem("nexacart-theme");
    } else {
      theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }
  } catch (error) {
    theme = "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
  /* main.js reads this so the toggle saves to the same per-account key */
  document.documentElement.setAttribute("data-theme-key", key);
})();

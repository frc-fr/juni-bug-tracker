"use strict";
// Runs before the first paint, in its own file because the CSP forbids inline scripts.
document.documentElement.dataset.theme = localStorage.getItem("theme")
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

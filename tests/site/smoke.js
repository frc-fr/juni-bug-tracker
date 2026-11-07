// Runs the page against the built data with a minimal DOM, to catch script errors.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const dist = process.argv[2];
const hash = process.argv[3] || "";
const elements = new Map();

class Element {
  constructor(id = "") {
    this.id = id; this.innerHTML = ""; this.textContent = ""; this.hidden = false; this.value = "";
    this.dataset = {}; this.attributes = {}; this.children = []; this.classList = { contains: () => false };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  querySelector() { return null; }
  select() {}
  remove() {}
}
const html = fs.readFileSync(path.join(dist, "index.html"), "utf8");
for (const [, id] of html.matchAll(/id="([^"]+)"/g)) elements.set(id, new Element(id));
const storage = {};
const context = {
  console, setTimeout, clearTimeout, URLSearchParams, Map, Set, Promise, Date, Intl,
  location: { hash, reload() {} },
  history: { replaceState(_, __, url) { context.location.hash = url; } },
  localStorage: { getItem: (k) => storage[k] || null, setItem: (k, v) => { storage[k] = v; } },
  navigator: { language: process.env.LANG_UI || "fr-FR" },
  matchMedia: () => ({ matches: false }),
  getSelection: () => ({ isCollapsed: true }),
  window: { addEventListener() {}, scrollY: 0 },
  document: {
    documentElement: { dataset: { theme: "light" } },
    getElementById: (id) => elements.get(id) || (elements.set(id, new Element(id)), elements.get(id)),
    querySelectorAll: () => [],
    createElement: () => new Element(),
    activeElement: null,
    body: new Element(),
  },
  fetch: async (url) => {
    const file = path.join(dist, url);
    return { ok: fs.existsSync(file), status: 404, json: async () => JSON.parse(fs.readFileSync(file, "utf8")) };
  },
};
context.globalThis = context;
vm.createContext(context);
let code = "";
for (const name of ["i18n.js", "logic.js", "app.js"]) code += fs.readFileSync(path.join(dist, name), "utf8") + "\n";
code += "\n;globalThis.__app = { state, update, render, versions: () => versions, bugs: () => bugs, options: () => combos.version.options };";
vm.runInContext(code, context);

const $ = (id) => elements.get(id);
setTimeout(() => {
  const app = context.__app;
  const report = (label) => {
    const results = $("results").innerHTML;
    console.log(`${label}: count=${JSON.stringify($("count").textContent)} chips=${($("chips").innerHTML.match(/<strong>[^<]*<\/strong><span>[^<]*/g) || []).join(" | ").replace(/<\/?strong>|<span>/g, "")}`);
    console.log(`   notices=${$("notices").innerHTML.replace(/<[^>]+>/g, " ").trim().slice(0, 300)}`);
    console.log(`   info=${$("version-info").innerHTML.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200)}`);
    console.log(`   first=${results.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 400)}`);
  };
  console.log("stats:", $("stats").textContent, "|", $("scope").textContent);
  if (process.env.SHOW_OPTIONS) {
    console.log("options:", app.options().map((o) => o.label).filter((l) => l.startsWith(process.env.SHOW_OPTIONS)).join(" / "));
  }
  report("default");
  for (const [label, change] of JSON.parse(process.argv[4] || "[]")) {
    app.update(change);
    report(label);
  }
}, 500);

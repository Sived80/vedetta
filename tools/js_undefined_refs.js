// Names used and never defined in the ES modules of the page: node --expose-internals tools/js_undefined_refs.js [JS_DIR]
// A module that uses a name of another module without importing it fails only when that line runs (a ReferenceError in the browser, not at load): this reads every module with the parser that Node itself carries
// (acorn, through --expose-internals: no library to install, development only) and reports each identifier that is neither imported, nor declared in an enclosing scope, nor a global of the page.
// Scopes are those of functions (every declaration of a function body counts for the whole function: an over-approximation that cannot hide a missing import).
const fs = require("fs");
const path = require("path");
let acorn;
try { acorn = require("internal/deps/acorn/acorn/dist/acorn"); } catch (e) { console.log("SKIPPED: the parser of Node is not reachable (run with --expose-internals)"); process.exit(0); }

const dir = process.argv[2] || path.join(__dirname, "..", "vedetta", "app", "frontend", "ha", "js");
const BROWSER = new Set(("window document location navigator localStorage sessionStorage history screen getComputedStyle requestAnimationFrame cancelAnimationFrame matchMedia EventSource WebSocket " +
  "Element HTMLElement Node Event CustomEvent KeyboardEvent MouseEvent PointerEvent ResizeObserver MutationObserver IntersectionObserver CSS FormData Blob FileReader XMLHttpRequest " +
  "alert confirm prompt scrollTo scrollY scrollX innerWidth innerHeight requestIdleCallback DOMParser Image Audio atob btoa TextDecoder TextEncoder crypto structuredClone queueMicrotask " +
  "visualViewport DOMException HTMLInputElement HTMLDialogElement NodeList").split(" "));
const GLOBALS = new Set([...Object.getOwnPropertyNames(globalThis), ...BROWSER, "undefined", "arguments"]);

function bindings(pattern, out) {
  if (!pattern) return;
  switch (pattern.type) {
    case "Identifier": out.add(pattern.name); break;
    case "ObjectPattern": pattern.properties.forEach((p) => bindings(p.type === "RestElement" ? p.argument : p.value, out)); break;
    case "ArrayPattern": pattern.elements.forEach((p) => bindings(p, out)); break;
    case "RestElement": bindings(pattern.argument, out); break;
    case "AssignmentPattern": bindings(pattern.left, out); break;
  }
}

// every name declared inside a function (or the module), without entering the functions nested in it
function declaredIn(node, out) {
  if (!node || typeof node.type !== "string") return;
  switch (node.type) {
    case "FunctionDeclaration": out.add(node.id.name); return;
    case "FunctionExpression": case "ArrowFunctionExpression": return;
    case "ClassDeclaration": out.add(node.id.name); break;
    case "VariableDeclaration": node.declarations.forEach((d) => bindings(d.id, out)); break;
    case "CatchClause": bindings(node.param, out); break;
    case "ImportDeclaration": node.specifiers.forEach((s) => out.add(s.local.name)); return;
  }
  for (const key of Object.keys(node)) {
    const v = node[key];
    if (Array.isArray(v)) v.forEach((x) => declaredIn(x, out)); else if (v && typeof v.type === "string") declaredIn(v, out);
  }
}

function check(file, code) {
  const ast = acorn.parse(code, { ecmaVersion: "latest", sourceType: "module", locations: true });
  const problems = [];
  const lines = code.split("\n");
  function visit(node, scopes, parent, key) {
    if (!node || typeof node.type !== "string") return;
    let inner = scopes;
    if (/^(Function|ArrowFunction)/.test(node.type)) {
      const names = new Set();
      node.params.forEach((p) => bindings(p, names));
      if (node.type === "FunctionExpression" && node.id) names.add(node.id.name);
      if (node.body.type === "BlockStatement") declaredIn(node.body, names); else declaredIn(node.body, names);
      inner = scopes.concat([names]);
    } else if (node.type === "ClassDeclaration" || node.type === "ClassExpression") {
      if (node.id) inner = scopes.concat([new Set([node.id.name])]);
    }
    if (node.type === "Identifier") {
      const isProperty = parent && ((parent.type === "MemberExpression" && key === "property" && !parent.computed) || (parent.type === "Property" && key === "key" && !parent.computed && !parent.shorthand) ||
        (parent.type === "MethodDefinition" && key === "key" && !parent.computed) || (parent.type === "PropertyDefinition" && key === "key" && !parent.computed) ||
        parent.type === "LabeledStatement" || parent.type === "BreakStatement" || parent.type === "ContinueStatement" || parent.type === "ImportSpecifier" ||
        parent.type === "ExportSpecifier" || (parent.type === "FunctionDeclaration" && key === "id") || (parent.type === "ClassDeclaration" && key === "id"));
      if (!isProperty && !inner.some((s) => s.has(node.name)) && !GLOBALS.has(node.name)) {
        problems.push({ name: node.name, line: node.loc.start.line, text: lines[node.loc.start.line - 1].trim().slice(0, 90) });
      }
      return;
    }
    for (const k of Object.keys(node)) {
      if (k === "loc" || k === "start" || k === "end") continue;
      const v = node[k];
      if (Array.isArray(v)) v.forEach((x) => visit(x, inner, node, k)); else if (v && typeof v.type === "string") visit(v, inner, node, k);
    }
  }
  const top = new Set();
  declaredIn(ast, top);
  visit(ast, [top], null, null);
  return problems;
}

let total = 0;
for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".js")).sort()) {
  const problems = check(f, fs.readFileSync(path.join(dir, f), "utf8"));
  for (const p of problems) console.log("%s:%d  %s is not defined   %s", f, p.line, p.name, p.text);
  total += problems.length;
}
console.log("names used and not defined: %d", total);
process.exit(total ? 1 : 0);

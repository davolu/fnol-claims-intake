// Frontend checks that need no browser: formatting helpers + API proxy invariants.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("proxy keeps the API token server-side", () => {
  const src = readFileSync(new URL("../app/api/[...path]/route.ts", import.meta.url), "utf8");
  assert.match(src, /process\.env\.APP_API_TOKEN/);
  assert.doesNotMatch(src, /NEXT_PUBLIC_/);
});

test("no client file reads secrets", () => {
  for (const f of ["../lib/api.ts", "../app/settings/page.tsx", "../app/claims/[id]/page.tsx"]) {
    const src = readFileSync(new URL(f, import.meta.url), "utf8");
    assert.doesNotMatch(src, /process\.env/);
  }
});

test("secret inputs are password fields", () => {
  const src = readFileSync(new URL("../app/settings/page.tsx", import.meta.url), "utf8");
  const n = (src.match(/type="password"/g) || []).length;
  assert.ok(n >= 2, `expected password inputs, found ${n}`);
});

test("stand-in banner is shown for mock integrations", () => {
  const src = readFileSync(new URL("../components/Shell.tsx", import.meta.url), "utf8");
  assert.match(src, /It is not Guidewire software/);
});

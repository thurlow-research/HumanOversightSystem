## Astro end-to-end test stack

This region adds Astro-framework browser/UI-layer end-to-end depth to PACK:node's HTTP-layer system-test guidance and CORE's generic targets — the exact gap PACK:node's `system-test` region defers to "the layered pack (e.g. astro)". Apply every item below **in addition to** PACK:node and CORE. Do not duplicate either here.

---

### Spec-derived test independence

Derive each end-to-end flow's expected outcome from the spec/design's stated user-facing behavior — the page states, navigation targets, and success/error conditions the technical design commits to — not by clicking through the current build and recording what happens. A Playwright test whose assertions were captured by observing today's running app is not a test; it certifies whatever the app currently does, regressions included, and stops failing the moment the bug it should have caught ships.

When you can see the diff or PR the flow implements, do not read the diff to decide what to assert — read the spec/design's stated flow first, write the expected page state/navigation/error condition from that, then check it against the diff.

---

### Test the built output, not only the dev server

Astro's dev server runs every route through SSR regardless of the route's configured rendering mode — a route with `prerender = true` (or a `static`/`hybrid`-output project) behaves identically to `server` output under `astro dev`. Running Playwright only against `astro dev` cannot catch a prerendering bug (stale build-time data served in production, a route that should have been SSR'd but wasn't) — that bug only manifests against `astro build && astro preview`:

```typescript
// playwright.config.ts
export default defineConfig({
  webServer: {
    command: "npm run build && npm run preview",
    port: 4321,
    reuseExistingServer: !process.env.CI,
  },
});
```

Run the full e2e suite against the built+previewed output in CI. A dev-server-only Playwright config is a coverage gap for every rendering-mode-dependent flow (see PACK:astro `code-reviewer`'s "Rendering-mode / data-access mismatches").

---

### Hydration timing

A `client:idle`/`client:visible`/`client:load` component is not interactive the instant its markup appears in the DOM — Playwright's default actionability checks (element visible, not disabled) do not wait for hydration to complete. Assert on a hydration-observable signal before interacting with an island:

```typescript
// wait for the island's own post-hydration state, not just DOM presence
await page.getByRole("button", { name: "Add to cart" }).click();
await expect(page.getByText("1 item")).toBeVisible(); // proves the click was handled, i.e. hydration had completed
```

For `client:visible` components below the fold, scroll the element into view before asserting interactivity — the directive does not hydrate until the component enters the viewport, and a test that never scrolls will hang or time out waiting for a handler that Astro has not yet attached.

---

### View transitions

For a flow the spec describes as persisting state across a `<ClientRouter />`/`<ViewTransitions />` navigation (an audio player continuing playback, a header not re-mounting), assert the persisted element's identity survives navigation — not just that the destination page eventually renders:

```typescript
const player = page.locator("[data-persist-id=audio-player]");
await player.evaluate((el) => el.setAttribute("data-test-marker", "before"));
await page.getByRole("link", { name: "Next track" }).click();
await expect(player).toHaveAttribute("data-test-marker", "before"); // same DOM node, not a re-mounted copy
```

A test that only checks the new page's content loaded will pass even if `transition:persist`/`transition:name` is missing or mismatched — the re-mount that bug produces still ends up showing the right content, just via a full remount instead of a persisted node.

---

### Cross-adapter flow coverage

For SSR endpoints (`src/pages/**.ts`) gated behind `export const prerender = false`, run at least one e2e test per endpoint against the actual configured adapter's preview/runtime (not only Vite's dev SSR) when the adapter changes request/response semantics the project depends on (edge-runtime API restrictions, cookie handling differences) — resolve the adapter from `astro.config.mjs` per PACK:astro `architect`/`technical-design`'s adapter-selection guidance, do not assume Node semantics apply uniformly across adapters.

---

### Coverage targets

Target one e2e test per user-facing flow the spec commits to (login, checkout, primary navigation), plus one per rendering-mode-sensitive route identified during review — this is a flow-coverage floor, not a line-coverage percentage; Playwright coverage instrumentation (`@vitest/coverage-istanbul` wired through `playwright.config.ts`) is optional and does not substitute for PACK:node's unit-level line-coverage floor.

---

### Test file layout

Organize e2e specs under `e2e/` or `tests/e2e/` (match the project's existing convention), separate from vitest's `test/unit/`/`test/system/` trees — Playwright and vitest use different config/discovery and should not share a root test directory. Name spec files `<flow>.spec.ts` after the user-facing flow under test (`checkout.spec.ts`, `view-transitions.spec.ts`), not after the route file it happens to exercise.

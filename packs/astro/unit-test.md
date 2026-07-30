## Astro component test depth

This region adds Astro-framework component-test tooling to PACK:node's JS/TS unit-test depth and CORE's generic targets. Apply every item below **in addition to** PACK:node and CORE. Do not duplicate either here.

---

### Spec-derived test independence

Derive each component test's expected rendered output from the component's documented contract — its typed `Props` interface, the content collection's Zod schema (`src/content/config.ts`), or the technical design's stated rendering-mode behavior — not by rendering the component once and copying today's output into the assertion. A snapshot or string match captured that way is not a test; it certifies whatever the component renders today, markup bugs included, and keeps passing after a regression that changes the output.

Where a component consumes a content-collection entry, validate the fixture against the collection's Zod schema before asserting on the rendered output — a fixture that does not itself satisfy the schema produces a test that passes for reasons unrelated to the component under test:

```typescript
import { experimental_AstroContainer as AstroContainer } from "astro/container";
import { blogSchema } from "../src/content/config";
import Card from "../src/components/Card.astro";

test("renders the post title as an h2", async () => {
  const fixture = blogSchema.parse({ title: "Hello", date: new Date("2026-01-01") });
  const container = await AstroContainer.create();
  const result = await container.renderToString(Card, { props: { post: fixture } });
  expect(result).toContain("<h2>Hello</h2>"); // asserted from the component's documented contract, not from a prior render
});
```

When you can see the diff that produced the component, do not read the diff to decide what to assert — read the `Props` interface / schema / design section first, write the expected markup or prop-flow from that, then check it against the diff.

---

### Astro Container API for component tests

Render `.astro` components in isolation with the Container API (`astro/container`) under vitest — this exercises the component's actual Astro compiler output (slot resolution, prop typing, conditional rendering) without a browser or a full page build:

```typescript
import { experimental_AstroContainer as AstroContainer } from "astro/container";
import Card from "../src/components/Card.astro";

test("renders a default slot", async () => {
  const container = await AstroContainer.create();
  const result = await container.renderToString(Card, {
    props: { title: "Hello" },
    slots: { default: "<p>Body</p>" },
  });
  expect(result).toContain("<p>Body</p>");
});
```

Resolve the Container API import path and export name (`experimental_AstroContainer` vs. the stabilized `AstroContainer`) from the project's installed `astro` version — do not assume the experimental name is current; check `node_modules/astro/package.json` or the project's existing test setup.

**Scope limit:** the Container API renders server-side output only — it does not execute `client:*` hydration, browser events, or framework-island reactivity (React/Vue/Svelte state changes after hydration). A component test asserting on post-hydration DOM state (a click handler firing, a `useState` update re-rendering) belongs in PACK:astro's `system-test` region (Playwright), not here. Do not write a Container API test that only proves the pre-hydration markup shipped and call it a test of the interactive behavior.

For a hydrated framework island's internal logic (a React/Vue/Svelte component's own state and event handlers, independent of Astro's hydration mechanism), test it directly with the framework's own component-test tool (`@testing-library/react`, `@vue/test-utils`, `@testing-library/svelte`) rather than through the Container API — the island's internal behavior is framework-owned, not Astro-owned.

---

### Frontmatter and prop validation

- A component whose frontmatter destructures `Astro.props` without a typed `Props` interface (or a runtime schema for props sourced from external data) is a coverage gap — write at least one test asserting the component's behavior when a prop is missing/malformed, not only the happy path.
- `Astro.slots.has("name")`/`Astro.slots.render("name")` branches must each have a corresponding test — an untested slot branch is exactly the kind of conditional-rendering path the Container API exists to make cheap to cover.

---

### Coverage targets

Target ≥ 80% line coverage on changed `.astro`/`.ts`/`.tsx` files, matching PACK:node's stack-neutral floor — the Container API's server-render path counts toward this the same as any vitest-covered module. Do not lower the floor for `.astro` files on the theory that "the compiler already validates the template" — compiler validation catches syntax errors, not logic/rendering-branch regressions.

---

### Test file layout

Co-locate or mirror per PACK:node's convention (`src/components/Card.astro` / `src/components/Card.test.ts`, or a mirrored `test/unit/components/` tree — match whichever the project already uses). Name Container API test files `<component>.test.ts`, not `.astro.test.ts` — the component under test is TypeScript-invoked even though its source is `.astro`.

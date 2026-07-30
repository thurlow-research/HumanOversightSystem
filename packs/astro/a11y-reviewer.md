## Astro accessibility depth

This region adds Astro-framework accessibility mechanics to the generic WCAG 2.1 AA checks in CORE. Apply every item below **in addition to** CORE. Do not duplicate CORE items here.

---

### Hydration timing and interactive-control availability

Astro's islands render server-side HTML immediately but the JS that makes a control interactive attaches only once its `client:*` directive's condition is met — this is an a11y-relevant gap, not just a performance one:

- A control that looks interactive in the server-rendered HTML (a button, a form) but has not yet hydrated (`client:idle`/`client:visible`) is focusable and may receive a click/keypress with no handler attached yet. For controls a keyboard or screen-reader user is likely to reach before hydration completes (anything above the fold, or reachable via a small number of Tab presses), prefer `client:load` or verify the component renders a `disabled`/inert state until hydrated — an apparently-active but non-functional control is a WCAG 4.1.2 (name, role, value must reflect actual state) violation.
- `client:only` components render nothing server-side (a blank region, or a fallback via a `<Fragment slot="fallback">`-style pattern) — verify a non-visual placeholder (e.g. a `role="status"` loading region) exists so screen readers announce that content is loading rather than encountering an unexplained gap in the page.

---

### View transitions and focus management

`<ClientRouter />`/`<ViewTransitions />` navigations do not reload the page, so the browser's default "focus moves to `<body>` on load" behavior does not occur — the application must manage focus explicitly, the same top a11y failure mode as any client-routed SPA:

- After a view-transition navigation, focus must move to a sensible location in the new page (typically the main heading or the top of the main content region) — verify the project either relies on Astro's default focus-reset behavior or explicitly moves focus via an `astro:after-swap` event listener. A navigation that leaves focus on a now-detached (or unrelated persisted) element is a WCAG 2.4.3 finding.
- Elements marked `transition:persist` remain in the DOM and keep their focus/scroll state across navigation — verify this is the intended behavior for that element (e.g. an audio player correctly keeping focus) and not an accidental focus trap where focus should have moved to new page content instead.
- Route announcements: a client-routed navigation must announce the new page to screen reader users (an `aria-live` region announcing the new page title, or reliance on the browser's native document-title-change announcement where supported) — verify one mechanism is in place; silent navigations are a WCAG 4.1.3 finding for SPA-style routing, and view transitions reintroduce the same requirement.

---

### `set:html` and semantic integrity

- Content injected via `set:html` bypasses Astro's templating entirely — verify the sanitized/trusted HTML source actually preserves semantic structure (heading levels, list markup, landmark roles) rather than producing div-soup. A markdown-to-HTML pipeline that drops heading semantics or list markup in favor of styled divs is an a11y finding independent of the XSS concern PACK:astro security-reviewer covers for the same construct.
- Verify heading hierarchy remains consistent when `set:html` content is embedded inside a page that has its own heading structure — injected content starting at `<h1>` inside a page whose surrounding content is already past `<h2>` is a WCAG 1.3.1 finding.

---

### Content collections and heading hierarchy

- Content collection entries (blog posts, docs pages) rendered via `<Content />` typically start their in-document headings at `<h2>` or lower (the page's own `<h1>` is the entry title, rendered separately by the layout) — verify the collection's authoring convention and the layout's heading levels agree; a mismatch produces skipped or duplicated heading levels across every entry in the collection, a systemic finding rather than a one-off.
- `getStaticPaths()`-generated dynamic routes must produce a unique, descriptive `<title>` and `<h1>` per generated page (from the collection entry's title field) — a shared/generic title across all generated pages from the same template is a finding (WCAG 2.4.2, and a broader usability issue for screen-reader users navigating by page title).

---

### Scoped `<style>` blocks and forced/hidden content

- Astro's style scoping does not exempt scoped rules from a11y-relevant CSS review — `display: none`/`visibility: hidden` used to hide content from sighted users while intending it to remain screen-reader-accessible must instead use the visually-hidden pattern (clip/absolute-position technique), not `display: none`, regardless of whether the rule lives in a scoped or global block.
- Verify focus-visible styling (`:focus-visible`) is present in scoped component styles for any custom interactive element — a component that removes the browser's default focus outline (`outline: none`) in a scoped `<style>` block without a replacement focus indicator is a WCAG 2.4.7 **blocking** finding, the same standard as any other stack.

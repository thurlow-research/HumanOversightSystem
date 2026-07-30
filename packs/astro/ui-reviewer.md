## Astro templating and design-system depth

This region adds Astro-template-specific design-conformance checks to the generic design-pack review in CORE. Apply every item below **in addition to** CORE. Do not duplicate CORE items here.

---

### Scoped styles and the design system's token sheet

Astro's `<style>` blocks are scoped per-component by default (a hashed attribute selector is injected) — this changes how design-system conformance is checked compared to a global-CSS stack:

- A component-scoped `<style>` block that hard-codes a color, spacing, or font value the design system already defines as a token is a **blocking** finding, identical to any other stack — scoping does not exempt a rule from token discipline. Reference the token via a CSS custom property (`var(--token-name)`) imported from the design system's global stylesheet, which remains unscoped and available inside scoped blocks.
- `is:global` inside a component's `<style>` block opts that block out of scoping — it must be reserved for genuine global concerns (importing the token sheet itself, a CSS reset, styling third-party markup the component doesn't own). An `is:global` block introducing component-specific styling defeats the isolation the design system's component contracts depend on — flag it and ask why scoping was bypassed.
- `class:list={[...]}` (Astro's conditional class helper) must resolve to documented component classes in every branch, the same standard applied to any framework's conditional class logic — a branch producing an undocumented ad-hoc class name is a finding.

---

### Framework-component islands and design-system boundary

When a hydrated React/Vue/Svelte island renders design-system components, the component contract must hold across the framework boundary:

- An island's internal styling (CSS modules, styled-components, a framework-specific pattern) must still consume the project's design tokens — not reintroduce a parallel token system inside the island. A hydrated component with its own hard-coded color palette diverging from the Astro-rendered surrounding page is a **blocking** finding.
- Islands that render a design-system component library (e.g. a shared component package used both in `.astro` files and inside islands) must render the identical markup/class structure in both contexts — a variant that only exists inside the island (different wrapper markup, different class names) fragments the design system.

---

### View transitions (`<ClientRouter />` / `<ViewTransitions />`)

- Elements intended to persist visually across a page navigation (a header, a persistent audio player, a sticky cart) require a matching `transition:name` (or `transition:persist`) present on the corresponding element on **both** the outgoing and incoming page. A mismatched name, or the attribute present on only one side, produces an unstyled flash/re-mount instead of the intended continuity — this is a design-conformance finding, not just a functional one, since the persistence is a stated part of the design.
- `transition:animate` customizations (a named animation, or `none` to disable the default fade/slide) must match what the design spec actually calls for — a default transition left in place where the design specifies a custom one (or vice versa) is a finding.
- View-transition-driven layout shifts (an element whose size/position differs meaningfully between the outgoing and incoming page) produce a visually jarring morph animation by default — verify the design accounted for this, or that `transition:name` is deliberately omitted on elements not meant to persist.

---

### Content collection rendering and typographic consistency

- Markdown/MDX content rendered via a content collection's `<Content />` component inherits the collection's prose styling from wherever that's defined (a global `.prose` class, a per-collection layout). Verify every collection entry route applies the same typographic treatment — a route that renders `<Content />` bare, without the project's prose wrapper class, is a finding.
- Custom MDX components (components substituted for standard HTML elements via the `components` prop passed to `<Content />`) must map to the design system's equivalent components (e.g. project's `<Callout>`, `<CodeBlock>`) rather than left as raw HTML — an MDX file rendering a raw `<pre><code>` instead of the design system's code-block component is a finding when the design system defines one.

---

### Slots and component composition

- Astro's named slots (`<slot name="..." />`) that receive design-system content (a card's header/body/footer regions) must be filled with markup that respects the parent component's layout contract — content passed into a slot that breaks the parent's expected structure (e.g. a slotted heading of the wrong level, breaking the card's internal spacing assumptions) is a finding traceable to the call site, not the component definition.
- A component with an unfilled required slot (the design system's contract states the slot is mandatory) rendering a visibly broken/empty region is a finding — verify a fallback (`<slot>fallback content</slot>`) exists for genuinely optional slots, and that required slots are enforced at the call site.

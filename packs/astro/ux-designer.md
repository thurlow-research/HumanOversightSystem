## Astro UX design depth

This region adds Astro-framework UX-design guidance to the stack-neutral CORE. Apply every item below **in addition to** the CORE role definition. Do not duplicate CORE items here.

---

### Rendering-mode UX consequences

The choice between static, server, and hybrid rendering is a UX decision, not purely an architectural one — the design pack must specify which routes are prerendered vs. server-rendered and why, because the two have different perceived-performance and freshness characteristics:

- Prerendered (static) routes serve instantly from a CDN with no server round-trip — the correct default for content-heavy, low-personalization pages. Specify these explicitly in the design.
- Server-rendered routes incur a per-request render (and, on a cold adapter, a cold-start latency). For any route the spec requires to be SSR (auth-gated, personalized, or reading request-time data), the design must specify a loading-state treatment if the adapter's cold-start or render latency is expected to be user-visible.
- A hybrid project mixing both must specify, per route, which mode applies — do not leave this to the coder to infer from what "seems dynamic." Ambiguity here produces exactly the rendering-mode/data-access mismatches PACK:astro code-reviewer flags after the fact.

---

### Island hydration and perceived interactivity

Design specs for interactive components must account for Astro's hydration timing, since a component's *visual* readiness and its *interactive* readiness are no longer the same moment:

- For every interactive component in the design, specify the acceptable hydration strategy (`client:load` for immediately-needed controls, `client:idle`/`client:visible` for everything else) as part of the component spec, not left to implementation. This directly determines whether a user can click a control the instant they see it — a UX property, not just a performance one.
- Where a component's server-rendered (pre-hydration) appearance and its hydrated appearance could visually differ (a skeleton state, a placeholder), specify both states explicitly — an unspecified pre-hydration appearance leads to layout shift or an unstyled-flash artifact once the coder discovers the gap.
- For `client:only` components (no SSR), specify the loading/fallback state shown before the client bundle downloads and hydrates — an unspecified gap here becomes a blank region in production.

---

### View transitions: continuity design

When the project uses `<ClientRouter />`/`<ViewTransitions />`, the design pack must specify per-element continuity intent, not leave it to whatever Astro's default cross-fade produces:

- Name which elements persist across navigation (headers, players, cart widgets) and require `transition:persist`/`transition:name` on those specifically — an unspecified default (everything cross-fades, nothing persists) may be the correct choice for some projects, but it must be a decision, not an accident.
- Specify the transition treatment for elements whose size or position changes meaningfully between two routes (a hero image different sizes on two pages) — the default morph animation on a large layout shift often reads as a bug, not a feature; the design should call out whether to disable the transition (`transition:animate="none"`) for such elements.
- Specify the focus-destination and route-announcement behavior for screen-reader users on navigation (see PACK:astro a11y-reviewer) as part of the interaction design, not an afterthought discovered during accessibility review.

---

### Content collections: authoring and empty states

- For every content collection the spec introduces (blog, docs, product catalog, changelog), the design must specify the empty-state UX (no entries yet), the loading/pending UX if entries can be revalidated at request time, and the list/detail page relationship (does a list page link to individually-routed detail pages, or is content shown inline).
- Specify the canonical prose/typographic treatment for rendered collection content (heading scale, code-block styling, image handling) once, referencing the project's design tokens — this becomes the pack's shared reference so every collection entry renders consistently, rather than each content type inventing its own presentation.

---

### Islands vs. full-page interactivity: the architectural UX call

For any feature requiring meaningful client-side interactivity (a multi-step form, a live-filtering interface, real-time updates), the design must state which model applies:

1. **Progressive-enhancement islands** — small, independently-hydrated interactive components embedded in an otherwise static/server-rendered page. The default for Astro projects; correct when interactivity is localized (a single form, a single widget) rather than spanning the whole page.
2. **A dedicated client-rendered island covering a whole page region** (`client:only`, a full SPA-like sub-app mounted into one large island) — required when the interactivity is too interconnected to decompose into independent islands (a complex dashboard with shared client-side state across many controls). State this explicitly in the design; defaulting to it without justification forfeits Astro's zero-JS-by-default advantage for content that didn't need it.

Record the choice per feature in the design, with the same explicitness the framework's HTMX-vs-SPA decision tree (PACK:django architect) requires for its own stack — Astro's island model has an equivalent decision point and deserves the same rigor.

---

### Notifying downstream reviewers after an Astro design change

After any design-pack change affecting Astro rendering, hydration, or transition behavior, write the round-trip notification artifact per the CORE contract. Include, in addition to CORE's required fields:

- For a new **hydration strategy decision:** the component name, the chosen `client:*` directive, and the reasoning (urgency, viewport position, browser-API dependency).
- For a new **rendering-mode decision:** the route(s) affected, the chosen mode (`static`/`server`/per-route `prerender`), and why.
- For a new **transition-persistence decision:** the element, the `transition:name`, and which routes it must match on.

Always notify `a11y-reviewer` when specifying view-transition focus behavior, and `code-reviewer`/`coder` when specifying a hydration-strategy or rendering-mode decision that constrains implementation.

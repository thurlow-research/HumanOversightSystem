## Django template and HTMX design-system depth

This region adds Django-template and HTMX-specific design-conformance checks to the generic design-pack review in CORE. Apply every item below **in addition to** the CORE checks. Do not duplicate CORE items here.

---

### Token application in Django templates

The Django template engine introduces several paths where tokens can be bypassed or mis-applied:

- Inline styles written directly in templates (`style="color: #…"` or `style="background: …"`) are a **blocking** token violation the same as in static CSS. The only acceptable inline form is `style="color: var(--token-name)"` — and only where the design pack documents a case that genuinely requires it (e.g. a dynamically computed hue value). Static color values always belong in a class.
- `{% static %}` is the correct way to reference the design-system CSS file. A template that references the token sheet via a hard-coded path (e.g. `href="/static/css/tokens.css"`) instead of `{% load static %}` + `{% static 'css/tokens.css' %}` is a code-quality finding (the token sheet may not load in all deployment configurations); flag it and move on — it is not a token violation per se.
- Conditional token application via `{% if %}` branches (e.g. `{% if condition %}class="badge-available"{% else %}class="badge-booked"{% endif %}`) must result in a valid, documented component class in every branch. A branch that produces a bare hex color or no class at all is a blocking finding.
- Template tag output (custom tags that render HTML snippets) must use the same token/class contract as hand-written templates. If a tag emits hard-coded colors, flag it on the tag's Python file, not just in the template.

---

### Django form widget rendering and design-system CSS classes

Django's form machinery renders widgets whose markup must conform to the design system's component contracts:

- Every form field must be wrapped in the design system's field container (typically a class like `.field` or equivalent documented in the design pack). The reliable Django pattern is a custom template (`FORM_RENDERER` pointing to a template set that wraps `{{ field }}` in `.field`), or manual per-field rendering in the template:
  ```html
  <div class="field">
    {{ field.label_tag }}
    {{ field }}
    {{ field.errors }}
  </div>
  ```
  A bare `{{ form.as_p }}` or `{{ form.as_table }}` that skips the design-system wrapper is a **blocking** finding if the design pack specifies a field container component.
- Widget CSS classes must be applied. The preferred mechanism is `Widget.attrs = {"class": "…"}` set in the form's `__init__` or via `widgets` in `Meta`. A template that overrides the widget's class with a hard-coded arbitrary name is a finding; the class must match the documented input component.
- Read-only or disabled fields rendered with `{% if %}` conditionals that swap the widget for plain text (e.g. `<span>{{ field.value }}</span>`) must still carry the correct typographic classes from the design pack. An unstyled span substituted for a field is a finding.
- `{{ field.errors }}` rendered inline must use the design system's error state presentation (typically an error class on the container, a styled `<ul>`, or an inline error token). A raw unstyled `{{ field.errors }}` rendered outside the `.field` wrapper is a finding.

---

### `{% include %}` partials and component template structure

The design system's components (cards, badges, modals, spot cards, etc.) are typically implemented as `{% include %}` partials. Check:

- The partial's HTML structure must match the documented component structure in the design pack — element nesting, required child elements, and required classes. A partial that flattens the structure (e.g. omits a required inner wrapper that the CSS depends on) will break layout even if the outer class is present; this is a **blocking** finding.
- Required child elements documented by the design pack must all be present in every render path. Where a partial uses `{% if %}` to conditionally omit a child (e.g. an optional badge, a metadata line), verify that the omission is explicitly permitted by the design pack. An omission not covered by the spec is a finding.
- `{% include %}` partials that accept a `with` context must receive all documented required context variables. A partial that silently degrades (renders empty or broken) when a required variable is absent is a finding — the design pack's component contract applies at every callsite.
- Partials must not be duplicated inline in a parent template as copy-pasted markup. If a design-system component exists as a partial, all callsites must use `{% include %}`. Diverged inline copies are a **blocking** finding because they will drift from the canonical component.

---

### HTMX partial responses and design-system conformance

HTMX replaces DOM fragments with server-rendered partials. Every HTMX partial response is a template in its own right and must satisfy the same design-system contract as a full-page template:

- An HTMX partial that renders a component (card, badge, form field, list item) must use the same component classes and structure as the equivalent full-page render. A "quick" inline render in the partial that skips the design system's wrapper is a **blocking** finding.
- `hx-swap="innerHTML"` responses that replace a container must produce well-formed component children — not raw text or unstyled elements that only look acceptable because the container provides context. The design pack's component contract applies to the fragment in isolation.
- `hx-swap="outerHTML"` responses that replace an entire component must reproduce the component's outer class and structure, not just its inner content. A response that returns only inner markup when the outer element is being replaced will break the component's layout.
- HTMX responses that render status or feedback (inline form errors, success banners, empty states) must use the design system's documented presentation for those states — not ad-hoc markup. An HTMX error response that returns a raw `<p>` instead of the design pack's error-state component is a finding.
- `hx-boost` (which rewrites `<a>` navigation into HTMX requests) should not cause full-page templates to be rendered into a sub-region. Verify that boosted pages return the full base template (or the correct `{% block %}` swap target), and that no design-system component is accidentally double-rendered or omitted.

---

### Django template inheritance and design-system layout regions

`{% extends %}` / `{% block %}` introduces structural layout contracts that the design system depends on:

- The base template defines layout regions (header, content, sidebar, footer, etc.) that the design pack treats as fixed zones. A child template that overrides a structural block (`{% block header %}`) to insert content not covered by the design pack's header contract is a finding.
- `{% block extra_css %}` and `{% block extra_js %}` are the correct extension points for per-page design additions. A child template that injects `<style>` or `<script>` tags outside these blocks is a finding — it bypasses the design system's loading order.
- A child template that extends the wrong base (e.g. a modal content page extending the full-page base, causing double-chrome) produces layout violations that are traceable to the template hierarchy. Flag the incorrect `{% extends %}` target and note what the design pack specifies.
- `{% block %}` override that completely replaces a region rather than extending it (`{{ block.super }}`) will discard design-system scaffolding in the parent block. Verify that discarding the parent block's content is intentional and documented; flag otherwise.

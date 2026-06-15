## Django UX design depth

This region adds Django-template and HTMX-specific UX-design guidance to the stack-neutral CORE. Apply every item below **in addition to** the CORE role definition. Do not duplicate CORE items here.

---

### Design token system in Django templates

The project's design pack (declared in `config.sh`) provides a CSS custom-property token stylesheet and a component class reference. When performing the initial audit or gap-filling:

- Verify the token stylesheet is loaded once in the base template (`{% block extra_css %}` or a `<link>` in `<head>`). Child templates that `{% extends %}` the base must not re-include it — flag duplicate `<link>` tags as a minor pack-conformance issue.
- Confirm that no inline styles or component-scoped `<style>` blocks hard-code hex values, pixel constants, or font names that are already defined as tokens. Every design-pack value must be referenced via `var(--token-name)`, never duplicated as a literal.
- When a coder or reviewer reports a missing token (a state color, a spacing unit, an icon size not in the pack), classify it by the normal additive/structural process. If additive, add it to the pack's token stylesheet in the correct section (color, spacing, typography, component) and document it in the pack's design reference. Follow the token-naming convention already established in the pack — semantic aliases (`--color-danger-text` over a raw hex name) so template authors reference meaning, not values.
- Contrast check: for any new color token used as text or icon on a background, compute the WCAG contrast ratio before committing it to the pack. Accept only AA-passing tokens (4.5:1 normal text, 3:1 large text and UI components). You can run:
  ```bash
  node -e "
  function lum(h){const c=parseInt(h,16);const r=((c>>16)&255)/255,g=((c>>8)&255)/255,b=(c&255)/255;
  return [r,g,b].map(v=>v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)).reduce((a,v,i)=>[.2126,.7152,.0722][i]*v+a,0);}
  const l1=lum('HEX1'),l2=lum('HEX2');
  console.log((Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05));"
  ```
  Substitute the two hex values (without `#`). Notify `a11y-reviewer` of any new color token with the computed ratio and the intended use case.

---

### Django form UX: widget rendering and error states

Django's form machinery has rendering gaps that affect UX consistency and accessibility. When auditing the design pack or filling gaps for form templates:

- **Label rendering:** `{{ field }}` alone renders only the widget, no label. The design pack must define a canonical form-field rendering pattern: at minimum `{{ field.label_tag }}` + `{{ field }}` + `{{ field.errors }}`. For compound widgets (`SplitDateTimeWidget`, formsets with `prefix`) confirm that `label_tag()` targets the correct `id_for_label` — document the expected id pattern in the pack.
- **Inline validation error UX:** the design pack must specify how `{{ field.errors }}` is styled — color, icon, proximity to the field, and (for HTMX forms) whether errors are swapped inline or refreshed via a full partial. Document this in the pack's error-state reference so every form template is consistent.
- **Non-field errors:** `{{ form.non_field_errors }}` must have a distinct visual treatment (typically an alert banner above the form, not inline beside a field). Specify the component class (e.g. `.alert-danger`) and placement rule in the pack.
- **Multi-step or wizard forms:** each step's design must be specified in the pack — progress indicator, back/continue button labeling, how partial completion is communicated. If the spec requires a multi-step form and the pack has no step-indicator component, that is an additive gap to fill.
- **Disabled and read-only fields:** the pack must define a visual treatment that clearly distinguishes disabled from enabled, and read-only from editable. Many projects omit this until a coder hits it; fill it proactively during the initial audit if the spec has any read-only field states.

---

### HTMX interaction patterns: design specification

HTMX serves HTML partials from the server and swaps them into the DOM. UX design for HTMX differs from SPA design in important ways that the design pack must address explicitly:

- **Partial as the UX unit:** each HTMX-driven interaction has a *request partial* (what the server returns on the action) and a *swap target* (where it lands). The design pack must enumerate, per interaction type, what the returned partial contains and which element it replaces. Underspecified partials lead to inconsistent UI — coders will improvise.
- **Loading and in-flight states:** `hx-indicator` shows a spinner during the request. The pack must define the spinner/loading-indicator component (the CSS class, the expected markup), the placement rule (inline near the trigger, vs. page-level overlay), and the threshold below which a loading indicator is omitted (e.g. sub-100ms actions). Without this, every developer makes a different choice.
- **Inline confirmation vs. redirect:** the pack must specify, for each action type, whether success is communicated by:
  - Replacing the trigger element with a confirmation partial (e.g. "Saved" badge swapped in place of a form).
  - A flash message injected into the messages container.
  - A full page navigation (302 redirect after POST).
  Mixing these unpredictably produces an incoherent UX. The pack should name the rule and apply it consistently — for example, "destructive actions (delete, cancel) redirect; edits show inline confirmation."
- **Progressive enhancement:** every HTMX-enhanced interaction must have a specified fallback for the non-JavaScript case if the spec requires it. If the spec does not require progressive enhancement, document the decision explicitly in the design pack so it is not silently assumed.
- **`HX-Trigger` response events:** when the server sends `HX-Trigger` headers to signal client-side events (e.g. close a modal, refresh a count badge), the design pack must name these events and the UI elements that respond to them. Without a canonical event vocabulary, event names diverge across templates.

---

### Component classes and the pack's HTML structure conventions

Django templates compose pages from `{% extends %}` + `{% block %}` inheritance and `{% include %}` partials. UX design decisions must account for this rendering model:

- **Block structure and component placement:** the base template's block structure (`{% block content %}`, `{% block sidebar %}`, `{% block header %}`) defines where components can land. If the spec introduces a new layout region (a persistent notification rail, a contextual help panel), the design pack must define the block or include hook — not leave it to the coder to invent.
- **Component naming convention:** component CSS classes must follow the convention already established in the pack (e.g. `.btn-primary`, `.badge-success`, `.card`, `.alert-warning`). When adding a new component, derive its name from the same pattern. Document the rule (when to use, when not to use, required wrapper markup, accepted modifier classes) in the pack's component reference.
- **`{% include %}` partials and self-containment:** a partial included by `{% include %}` must carry all the CSS classes it needs; it must not rely on a parent template's surrounding element for styling. When designing a new component intended for use as an include, specify in the pack that it is self-contained and document its expected context variables.
- **Form layout primitives:** if the project's design pack includes a grid or layout-primitive class set (e.g. `.field`, `.field-row`, `.form-group`), document which layout class wraps each `{{ field }}` rendering so form templates are consistent. An undocumented layout primitive is a recurring gap source during build.

---

### Server-driven interaction design: what to specify vs. leave to the server

In a Django + HTMX application the server controls both data and rendering. Several UX design decisions that SPAs make client-side must instead be specified in the design pack for server implementation:

- **Optimistic vs. server-confirmed UI:** Django/HTMX applications typically show server-confirmed results (the page updates only after the server responds). If any interaction uses optimistic UI (disabling a button and assuming success before the response), this must be called out explicitly in the pack, because it requires specific partial and error-recovery design.
- **Long-running actions:** if the spec includes operations that take more than a few seconds (exports, batch operations, async tasks), the design pack must specify the waiting-state UX: polling vs. WebSocket vs. redirect-after-task, the intermediate "in progress" component, and the completion/failure transition. Django's Celery + HTMX polling pattern (periodic `hx-get` on a task-status endpoint) has a distinct UX rhythm; specify it if it appears in the spec.
- **Empty states:** every list view and search result set has an empty state. The design pack must specify, per view type, the empty-state message, illustration (if any), and call-to-action. An absent empty state is a recurring startup-artifact gap — cover it in the initial audit proactively.
- **Pagination and "load more":** if the spec includes paginated lists, the pack must specify whether pagination is page-based (links that trigger a full HTMX swap of the list region) or infinite-scroll / "load more" (appending to the list via `hx-swap="beforeend"`). The two patterns have different DOM structure requirements — the pack must pick one per list type and document it.

---

### Notifying downstream reviewers after a Django pack extension

After any design pack change in a Django project, write the round-trip notification artifact per the CORE contract. For Django-specific additions, include:

- For a new **color token:** the token name, hex value, and the contrast ratio you verified.
- For a new **component class:** the exact CSS class name, its expected wrapper markup, and which template(s) should apply it.
- For a new **HTMX partial pattern:** the swap target selector, the trigger element, the expected partial structure, and the `HX-Trigger` event name if one is emitted.
- For a new **form error pattern:** the error container element, its `id` convention (so `aria-describedby` can reference it), and the component class applied.

Always notify `a11y-reviewer` when adding color tokens or new interactive-component patterns, and `ui-reviewer` when adding or modifying any component class that existing templates reference.

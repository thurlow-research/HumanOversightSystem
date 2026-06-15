## Django template and HTMX accessibility depth

This region adds Django-template and HTMX-specific accessibility mechanics to the generic WCAG 2.1 AA checks in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### Django form rendering and label association

Django's form machinery has several a11y failure modes that static grep and template reading expose:

- `{{ form }}` or `{{ form.as_p }}` / `{{ form.as_table }}` renders each field with `label_tag()` by default. When a field is rendered **manually** (field by field), the template must call `{{ field.label_tag }}` or emit an explicit `<label for="{{ field.id_for_label }}">` — using only `{{ field.label }}` emits bare text with no `for` binding, which breaks programmatic association (WCAG 1.3.1).
- Verify that `{{ field.id_for_label }}` matches the widget's rendered `id`. For compound widgets (e.g. `SplitDateTimeWidget`, inline formsets with `prefix`), the rendered id may differ from the default `id_{{ field.html_name }}` — confirm the `for` and `id` values agree.
- `placeholder` on a `<input>` is not a substitute for a label. A template that renders only `{{ field }}` without `{{ field.label_tag }}` (or an explicit `<label>`) is a blocking finding even if placeholder text appears.
- Hidden fields (`widget=HiddenInput`) do not need labels; skip those. Every other widget type does.

---

### Django form error message association

Django injects field errors into `{{ field.errors }}` and non-field errors into `{{ form.non_field_errors }}`. The a11y contract for errors:

- Error text must be **programmatically associated** with its input. The reliable pattern is `aria-describedby="{{ field.auto_id }}_error"` on the `<input>` and `id="{{ field.auto_id }}_error"` on the error container, or use a widget's `attrs` to inject `aria-describedby`. A floating error `<ul>` rendered near the field but with no programmatic link is a WCAG 1.3.1 finding.
- `{{ field.errors }}` renders an unordered list by default — that list must carry the `id` used in `aria-describedby`. If a project renders errors with a custom snippet (`{% for error in field.errors %}`), the container still needs the `id`.
- `{{ form.non_field_errors }}` rendered at the top of a form must carry `role="alert"` or be wrapped in a live region so screen readers announce it on submission without a page reload (a common HTMX scenario).

---

### Django messages framework

`django.contrib.messages` injects flash messages rendered in a base template (typically via `{% for message in messages %}`). Check:

- The messages container must carry `role="status"` (for informational/success) or `role="alert"` (for error/warning). An unstyled `<ul>` with no ARIA role is a finding.
- On pages that use HTMX (where the full page is not reloaded), messages injected into a partial via `{% messages %}` must arrive inside an `aria-live` region. If the base template wraps messages in a non-live container and HTMX only swaps the content area, screen readers will never announce the message — this is a blocking WCAG 4.1.3 finding.
- If messages are rendered in a toast or dismissible banner, the close/dismiss button must have an accessible name (`aria-label="Dismiss"` or visible text) and keyboard focus must return to a sensible location after dismissal (WCAG 2.4.3).

---

### HTMX partial swaps and focus management

HTMX replaces DOM fragments without a page load. Focus management is the top a11y failure mode in HTMX apps:

- After an `hx-swap` that replaces content the user was interacting with (e.g. a form submission that shows an inline confirmation, a tab panel swap, a search result update), the browser drops focus to `<body>` unless the application manages it explicitly. Verify one of:
  - The swapped-in content contains an element with `autofocus` (acceptable when the new content is the natural continuation of the task).
  - The response sets focus programmatically via a small script or HTMX's `hx-on::after-swap` hook.
  - The trigger element is still in the DOM and retains focus.
- `hx-swap="outerHTML"` on the trigger element itself removes that element from the DOM; focus is always lost. Check that the response injects a replacement element that receives focus or that `hx-on::after-swap` moves focus.
- `hx-swap="innerHTML"` on a container that contains the trigger: if the trigger is inside the swapped region it is also removed. Same finding.
- Tab-trapped modals or dialogs loaded via HTMX must implement the modal focus-trap pattern (focus on first focusable element inside; Tab/Shift-Tab cycle within; Escape closes and restores focus to the trigger).

---

### HTMX and `aria-live` regions for partial updates

When HTMX injects content that changes application state visibly, screen readers must be notified:

- Status messages, validation summaries, search result counts, and toast notifications injected by HTMX must arrive inside an `aria-live="polite"` region (or `aria-live="assertive"` for critical alerts). A div that appears in the DOM outside any live region is silent to screen readers.
- The `aria-live` container must be **present in the initial page load** (even if empty) — HTMX injecting content into a live region that itself was injected does not reliably trigger announcements in all browser/AT combinations.
- `aria-atomic="true"` is appropriate when the entire region message should be announced as a unit (e.g. "3 results found"); omit it when only the changed child should be announced (incremental list updates).

---

### `hx-indicator` and loading state accessibility

`hx-indicator` toggles a CSS class (`htmx-request`) on a spinner or loading element during the request. Check:

- The indicator element must have `aria-label` (e.g. `aria-label="Loading"`) and `role="status"` so screen readers announce it when it becomes visible (WCAG 4.1.3).
- If the indicator is a CSS-only spinner (`<div class="spinner">` with no text), it must carry `aria-label` — an empty animated div is invisible to assistive technology.
- The indicator should carry `aria-live="polite"` if the spinner text changes during the request lifecycle (e.g. "Loading..." → "Done"); otherwise a static `aria-label` is sufficient.

---

### Django template patterns for semantic HTML

Django template tags and filters interact with the DOM structure in ways that introduce semantic issues:

- `{% if %}` / `{% for %}` branches that conditionally render interactive elements (tabs, accordions, step indicators) must produce consistent heading hierarchy and landmark structure regardless of which branch renders. A heading level that skips from `<h2>` to `<h4>` inside a `{% if %}` block is a WCAG 1.3.1 finding.
- Template inheritance (`{% block %}` / `{% extends %}`) can produce orphaned `<section>` or `<article>` elements that lack headings — check that every sectioning element has an associated heading or `aria-labelledby`.
- `{% include %}` partial templates that render interactive components (dropdowns, date-pickers, custom selects) should carry their own ARIA roles and state attributes rather than relying on the parent template. Verify the included partial is self-contained from an ARIA perspective (roles, states, and properties are complete in the partial, not split across the parent and the include).
- Icon-only buttons rendered via a template tag (e.g. `{% icon "trash" %}`) that output `<button><svg>…</svg></button>` must include `aria-label` on the button or an `<svg title>` + `aria-labelledby` on the button. The template tag itself should enforce this; flag it as a medium finding if it does not.

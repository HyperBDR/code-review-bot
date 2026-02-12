---
name: vue-code-review
description: Performs code reviews for Vue.js (.vue, Vue-related JS/TS) following the official Vue.js Style Guide. Covers component design, template rules, Composition API / Options API best practices, and priority A/B/C/D rules. Use when reviewing Vue frontend code or when asked to check or improve Vue code quality.
compatibility: opencode
---

# Vue.js Code Review (Official Style Guide)

Perform systematic code reviews of Vue files (`.vue`, and Vue-related `.js`/`.ts`) following the [Vue.js Official Style Guide](https://vuejs.org/style-guide/).

## Review Philosophy

- **Priority order**: A (Essential) > B (Strongly Recommended) > C (Recommended) > D (Use with Caution). Flag A violations as [严重]; B/C as [建议] unless they cause real bugs.
- **Consistency**: Within a component and within the project matters. When the style guide allows options, prefer consistency with existing code unless there is a strong reason to change.
- **Context**: Consider whether the project uses Vue 3 Composition API, Options API, or both; and whether it uses `<script setup>` or explicit `setup()`. Review accordingly.

## Review Process

1. **Identify scope**: Review each changed `.vue` file and any changed JS/TS that contains Vue usage (components, composables, stores).
2. **Apply rules by priority**: Check Priority A first (must fix), then B/C (recommend), then D (caution).
3. **Template & script**: Check template syntax (directives, keys, component names) and script (props, emits, state, lifecycle).
4. **Output**: When invoked from git-review, report findings in the same format as the parent skill (审查总结 / 发现的问题 / 建议 / 结论), using Chinese for the final output.

## Priority A: Essential (Error Prevention)

Treat violations as **[严重]** unless the author has an explicit, documented exception.

### Component names (multi-word)

- Component names must be **multi-word** (e.g. `TodoItem`, `UserProfile`) except the root `App` component. Single-word names risk conflicting with current or future HTML elements.
- **Bad**: `Item`, `user`, `Header`
- **Good**: `TodoItem`, `UserCard`, `PageHeader`

### Component files

- Each component that is reused or complex enough to warrant it should be in its own file. File name should match the component name (e.g. `TodoItem.vue` for component `TodoItem`).

### Props definition

- Props must be defined with **detailed validation** (type and optionally `required`, `default`, `validator`). Avoid props that are only type-checked without description of contract.
- Prefer object form: `props: { status: { type: String, required: true }, count: { type: Number, default: 0 } }`.

### `v-for` and `key`

- **Always use `key`** with `v-for`. The key must be unique and stable (prefer an id, not array index when list can change).
- **Bad**: `<div v-for="item in items">`
- **Good**: `<div v-for="item in items" :key="item.id">`

### Avoid `v-if` / `v-for` on the same element

- Do not use `v-if` and `v-for` on the same element. Vue gives higher priority to `v-for`, so `v-if` runs per item and can be confusing or inefficient. Use a computed property or a wrapper element/template instead.

### Component scope styles

- Prefer **scoped** styles for component-specific CSS (`<style scoped>`) to avoid leaking styles. Use deep selectors only when intentionally styling child components.

### Private property names

- Do not use `$` or `_` as prefixes for private properties on the instance (e.g. `this._private`). They can conflict with Vue’s internal and built-in APIs. Use a naming convention that doesn’t clash (e.g. a module or closure for real privates).

## Priority B: Strongly Recommended

Treat as **[建议]** unless they directly cause bugs or major maintainability issues.

### Component files naming

- Base component names (e.g. presentational, single-instance): prefix like `BaseXxx`, `AppXxx`, or `VXxx` so they are clearly distinguished from feature components.

### Single-file component structure

- Order of blocks in `.vue`: `<script>`, `<template>`, `<style>`. Or: `<script setup>`, `<template>`, `<style>`.

### Component name in template (casing)

- In templates, use **kebab-case** for component names: `<user-profile />` not `<UserProfile />`. Improves consistency and avoids casing issues in the DOM.

### Self-closing components

- For components with no content, use self-closing form: `<TodoItem />` (or `<todo-item />` in kebab-case). Keeps template consistent.

### Props casing

- In templates, use **kebab-case** for prop names: `<todo-item :user-name="name" />`. In script, use camelCase in definitions and in JS.

### Directives shorthand

- Use `:` for `v-bind` and `@` for `v-on` when it improves readability: `:value="x"`, `@click="onClick"`.

## Priority C: Recommended

Suggest for consistency; mark as [建议] and allow override if the project has a consistent alternative.

### Component instance order (Options API)

- Order: `name` → `components` → `props` → `data` → `computed` → `watch` → lifecycle hooks → `methods`.

### Element attribute order

- Order: definition (`is`, `v-is`) → list rendering (`v-for`) → conditionals (`v-if`, `v-show`) → render modifiers (`v-pre`, `v-once`) → global awareness (`id`) → unique (`ref`, `key`) → slot (`v-slot`) → two-way binding (`v-model`) → events (`@`) → content → other attributes.

### Empty lines between blocks

- Add a single empty line between multi-line properties in the script (e.g. between `data`, `computed`, `methods` blocks) for readability.

### Single-file component top-level element

- Prefer a single top-level element in `<template>` (e.g. one root `<div>` or `<template>`) unless using fragments intentionally (Vue 3 supports multiple roots; still prefer one when it doesn’t hurt).

## Priority D: Use with Caution

Flag only when overuse or misuse could cause real maintenance or performance problems.

### `scoped` slot usage

- `scoped` slots are fine when needed; avoid deep nesting of scoped slots that make data flow hard to follow.

### Implicit parent-child communication

- Prefer **props down, events up**. Avoid `$parent` / `$children` and non-declarative refs for cross-component communication unless justified (e.g. focus management).

### Non-flux state (manual sync)

- Prefer Vuex/Pinia or a single source of truth instead of manually syncing state across components (e.g. `v-model` + custom sync). Flag when the change introduces fragile sync patterns.

## Composition API (Vue 3)

- Prefer `<script setup>` for new code when the project allows: clearer and less boilerplate.
- Use `defineProps` / `defineEmits` with type or runtime definitions; keep prop/emit contracts explicit.
- Prefer `computed` and `watch` for derived state and side effects; avoid imperative DOM or reactive mutations outside of lifecycle/composables.
- Composables: name with `use` prefix (e.g. `useUser`), return a single object or reactive refs; avoid mutating global state inside without clear intent.

## Options API

- Prefer `data` as a function returning an object (required in components).
- Lifecycle hooks: use correct names (`created`, `mounted`, etc.) and avoid mixing lifecycle logic with heavy business logic; extract to methods or composables when long.

## Template & accessibility

- Prefer semantic HTML where possible (e.g. `button` for actions, `label` + `input` association). Flag obvious a11y issues (e.g. clickable div without role/keyboard).

## Summary for Reviewer

- **Priority A**: Always report as [严重] with a short fix suggestion.
- **Priority B/C**: Report as [建议] with rationale; allow project consistency overrides.
- **Priority D**: Mention only when misuse is clear; avoid nitpicking rare, justified use.
- When invoked from **git-review**: output still follows the git-review format (审查总结、发现的问题、建议、结论), in Chinese. Vue-specific findings go under 发现的问题 or 建议 as appropriate.

---
rule_id: ui-library-governance-faros
principle: UI Library Governance
category: frontend, architecture, design-system
tags: [faros-ui, tailwind, radix-ui, component-governance, design-tokens, accessibility, eslint, maintainability]
severity: high
language: typescript, tsx, react
---

# Rule: All New Frontend Components Must Use the Faros UI Library

## Core Constraint

Every new product component **must import exclusively from `@/faros-ui`** for all visual primitives (buttons, dialogs, badges, cards, etc.). Raw HTML elements with inline styles or ad-hoc Tailwind colour utilities are prohibited outside the library layer itself. Design tokens (`tokens.ts`) are the single source of truth for all visual values — colours, spacing, radius, shadow, and typography must be defined there and referenced by name, never hard-coded at the component level.

---

## Negative Patterns — What to Avoid

### ❌ Anti-Pattern 1: Raw HTML elements with inline styles in product components
```tsx
// VIOLATION: raw <button>, one-off hex colours, no focus ring, no disabled state,
// no accessibility — will diverge from the design system immediately
export function LegacyWidget() {
  return (
    <div style={{ padding: '24px', background: '#fff', borderRadius: '8px',
                  border: '1px solid #e4e4e7', boxShadow: '0 1px 3px rgba(0,0,0,.1)' }}>
      <button
        style={{ background: '#7c3aed', color: '#fff', padding: '8px 16px',
                 borderRadius: '6px', fontSize: '14px', border: 'none' }}
        onClick={() => setOpen(true)}
      >
        Open
      </button>
    </div>
  );
}
// Problems:
// • #7c3aed is the brand colour duplicated in every component that needs a button
// • No focus ring, no disabled state, no loading state — all re-invented per callsite
// • borderRadius: '8px' is a magic number with no connection to the token system
// • A brand colour change requires hunting every file for '#7c3aed'
```

### ❌ Anti-Pattern 2: Hand-rolled modal with no accessibility
```tsx
// VIOLATION: roll-your-own modal skips the Radix UI accessibility layer entirely
{open && (
  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)' }}>
    <div style={{ background: '#fff', padding: '24px', borderRadius: '8px' }}>
      <h2>Title</h2>
      {/* No focus trap, no aria-*, no keyboard dismiss, no scroll lock */}
      <button onClick={() => setOpen(false)}>Close</button>
    </div>
  </div>
)}
// Problems:
// • No focus trap → keyboard users can tab behind the modal
// • No aria-modal, aria-labelledby → screen readers cannot identify this as a dialog
// • No Escape-key dismiss → standard UX expectation broken
// • Visual values duplicated again, disconnected from tokens
```

### ❌ Anti-Pattern 3: Raw primitive inside a library component bypassing its own token system
```tsx
// VIOLATION (inside faros-ui/Dialog.tsx): raw <button> with ad-hoc Tailwind
// colours instead of using the library's own Button or an IconButton variant
<RadixDialog.Close asChild>
  <button
    aria-label="Close dialog"
    className="absolute top-4 right-4 text-zinc-400 hover:text-zinc-700"  // ← ad-hoc
  >
    ✕
  </button>
</RadixDialog.Close>
// Problem: the library violates its own principle internally.
// Solution: extract an `icon` or `ghost` Button variant and use it here.
```

### ❌ Anti-Pattern 4: Visual values hard-coded in components instead of tokens
```tsx
// VIOLATION: recurring values not captured in tokens.ts
// These appear across Card.tsx, Dialog.tsx, and product components
className="bg-white shadow-sm border border-zinc-200"   // ← should be tokens
className="shadow-xl bg-black/50"                       // ← should be tokens
className="text-zinc-900 text-zinc-500 text-zinc-600"  // ← typography tokens missing

// When dark mode or a rebrand arrives, every file must be hunted individually.
// If tokens.ts had: colors.surface, shadow.card, shadow.overlay, colors.overlay,
// text.primary, text.secondary, text.muted — a single file edit propagates everywhere.
```

### ❌ Anti-Pattern 5: Incomplete token coverage creates maintenance blind spots
```tsx
// VIOLATION: tokens.ts covers colours, radius, spacing — but omits:
// | Hard-coded value      | Appears in              | Missing token         |
// | bg-white              | Card.tsx, Dialog.tsx    | colors.surface        |
// | shadow-sm / shadow-xl | Card.tsx, Dialog.tsx    | shadow.card / overlay |
// | border-zinc-200       | Card.tsx                | border.default        |
// | bg-black/50           | Dialog.tsx              | colors.overlay        |
// | text-zinc-900/500/600 | UserProfileCard.tsx     | text.primary etc.     |
```

---

## Positive Patterns — The Fix

### ✅ Pattern 1: Comprehensive design tokens as the single source of truth
```ts
// faros-ui/tokens.ts — ALL visual values defined once here
export const colors = {
  brand:        'bg-violet-600 text-white hover:bg-violet-700',
  brandOutline: 'border border-violet-600 text-violet-600 hover:bg-violet-50',
  destructive:  'bg-red-600 text-white hover:bg-red-700',
  neutral:      'bg-zinc-100 text-zinc-800 hover:bg-zinc-200',
  surface:      'bg-white',
  overlay:      'bg-black/50',
} as const;

export const shadow = {
  card:    'shadow-sm',
  overlay: 'shadow-xl',
} as const;

export const border = {
  default: 'border border-zinc-200',
} as const;

export const text = {
  primary:   'text-zinc-900',
  secondary: 'text-zinc-500',
  muted:     'text-zinc-600',
} as const;

export const radius  = { sm: 'rounded', md: 'rounded-md', full: 'rounded-full' } as const;
export const spacing = { buttonPadding: 'px-4 py-2', cardPadding: 'p-6' } as const;

// A rebrand or dark-mode rollout = edits to THIS FILE ONLY.
// All components inherit the change with zero per-component work.
```

### ✅ Pattern 2: Library components reference tokens, never hard-code values
```tsx
// faros-ui/Card.tsx — every visual decision traceable back to tokens.ts
import { colors, border, shadow, radius, spacing } from './tokens';

export function Card({ children, className = '' }: CardProps) {
  return (
    <div className={[
      colors.surface,          // ← not 'bg-white'
      border.default,          // ← not 'border border-zinc-200'
      shadow.card,             // ← not 'shadow-sm'
      radius.md,
      spacing.cardPadding,
      className,
    ].join(' ')}>
      {children}
    </div>
  );
}

// faros-ui/Dialog.tsx — close button uses an icon variant, not a raw element
import { Button } from './Button';  // icon variant, not a raw <button>

<RadixDialog.Close asChild>
  <Button variant="ghost" size="icon" aria-label="Close dialog">✕</Button>
</RadixDialog.Close>
```

### ✅ Pattern 3: Product components import exclusively from `@/faros-ui`
```tsx
// ✓ components/UserProfileCard.tsx
// Zero raw HTML styling, zero inline styles, zero ad-hoc colour utilities
import { Button, Dialog, Badge, Card } from '@/faros-ui';  // ONLY import path

export function UserProfileCard({ name, role, email, memberStatus }: UserProfileCardProps) {
  return (
    <Card className="flex flex-col gap-4 max-w-sm">

      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-zinc-900">{name}</h2>
          <p  className="text-sm text-zinc-500">{role}</p>
        </div>
        <Badge status={memberStatus} />   {/* ✓ token-driven status colour */}
      </div>

      <p className="text-sm text-zinc-600">{email}</p>

      <div className="flex gap-2">
        <Button variant="brand" onClick={() => console.log('Edit', name)}>
          Edit Profile
        </Button>

        <Dialog
          trigger={<Button variant="destructive">Deactivate</Button>}
          title="Deactivate Account"
        >
          <p className="text-sm text-zinc-600 mb-4">
            Are you sure you want to deactivate <strong>{name}</strong>?
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="neutral">Cancel</Button>
            <Button variant="destructive">Yes, Deactivate</Button>
          </div>
        </Dialog>
      </div>

    </Card>
  );
}
// If the brand colour changes: edit tokens.ts once → every Button instance updates.
// Accessible modal behaviour (focus trap, Escape dismiss, aria-*): free from Radix.
```

### ✅ Pattern 4: ESLint rule mechanically enforces the policy
```ts
// lint/no-raw-html-in-components.ts
// Prevents the principle from degrading under deadline pressure.
// Convention without enforcement erodes over time; this makes compliance guaranteed.

import { Rule } from 'eslint';

const GOVERNED_ELEMENTS = new Set(['button', 'input', 'select', 'textarea', 'dialog']);
const LIBRARY_PATH       = '@/faros-ui';
const EXEMPT_PATHS       = ['/faros-ui/', '__tests__', '.stories.'];  // library internals exempt

export const noRawHtmlInComponents: Rule.RuleModule = {
  meta: {
    type: 'problem',
    docs: {
      description: `Raw <button>, <input>, <dialog> etc. are prohibited in product ` +
                   `components. Use the Faros UI equivalent from '${LIBRARY_PATH}'.`,
    },
  },
  create(context) {
    const filePath = context.getFilename();
    const isExempt = EXEMPT_PATHS.some(p => filePath.includes(p));
    if (isExempt) return {};

    return {
      JSXOpeningElement(node) {
        const name = node.name.type === 'JSXIdentifier' ? node.name.name : null;
        if (name && GOVERNED_ELEMENTS.has(name)) {
          context.report({
            node,
            message:
              `Raw <${name}> is not allowed in product components. ` +
              `Import the Faros UI equivalent from '${LIBRARY_PATH}' instead.`,
          });
        }
      },
    };
  },
};

// Also enforce the single import path (no deep imports into faros-ui internals):
// import { Button } from '@/faros-ui/Button'  ← VIOLATION
// import { Button } from '@/faros-ui'          ← CORRECT
```

---

## Governance Decision Table

| Scenario | Required Action |
|---|---|
| New product component needs a button | `import { Button } from '@/faros-ui'`, choose a variant |
| New product component needs a modal | `import { Dialog } from '@/faros-ui'` — accessibility free |
| Design needs a new colour or spacing value | Add to `tokens.ts` first, then create/extend a component |
| Library component needs an internal interactive element | Use an existing library primitive or add a new variant — never a raw element |
| Inline style or `style={{}}` prop on any element | Always a violation; migrate to token-backed Tailwind classes |
| Ad-hoc Tailwind colour utility in a product component | Migrate to a token (e.g. `text-zinc-900` → `text.primary`); layout utilities `flex`, `gap-*`, `max-w-*` are exempt |
| Legacy component using inline styles | Mark `@deprecated`, quarantine in `/legacy`, migrate on next touch |
| New primitive needed that doesn't exist yet | Add to `faros-ui/`, export from `index.ts`, document the variant |

---

## Key Principle Summary

> **The Faros UI library is a contract, not a suggestion.** Product components are consumers of that contract — they have no knowledge of colours, shadows, or radii. The token system is the single source of truth for all visual values; the ESLint rule is the enforcement mechanism that makes compliance structural rather than cultural. A system where "adding a field propagates everywhere" for data also applies here: a token update propagates everywhere, and a missing token is a bug to fix in `tokens.ts`, not a reason to hard-code a value in a component.
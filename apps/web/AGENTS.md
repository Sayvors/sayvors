<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Sayvors UI rules

- **Never use gradients.** Not on backgrounds, surfaces, buttons, text, borders,
  or as decorative washes. Depth comes from solid fills and shadow stacks.
  The only exception is a third-party brand logo rendered as-is (e.g. the
  Google "G" in globals.css).
- **Never use glassmorphism** — no `backdrop-blur`, no translucent white panels,
  no blur behind content. Surfaces are solid pastel or neutral fills.
- Depth is a single light source at the top-left: a white inset on the top edge,
  a tinted inset plus outer shadow falling below. Non-clickable containers get
  the outer shadow only.
- Buttons get a tighter shadow stack than cards, and press feedback is
  `translateY(2px) scale(0.98)` — never animate `box-shadow`.
- Radius is roughly 25% of element height: 32px cards, 24px buttons, 20px
  inputs. No sharp corners anywhere.
- **Surfaces are white**, not pastel. A page background one step off white
  (`#f1f2f5`) is the only tint; colour is reserved for meaning — accent for the
  one primary action, danger for destructive, ok for live. Multiple competing
  surface colours were tried and rejected as too busy.
- Interactive clay elements need a visible 3px solid `:focus-visible` outline;
  soft shadows never replace it.
- Colors come from Sayvors Brand Guidelines V1.0 (`app/globals.css`): Deep
  Violet `#3D1D6E`, Magenta `#B0338A`, Coral `#FF4F6E`, Ink `#14101F`,
  Fog `#F4F2F7`; dark mode `#6B3FB5` / `#D8459F` / `#FF6E85`. Body text on a
  pastel surface is `#3B2D5E`, minimum 4.5:1.

/* Gold crown marker for a surface the current plan does not include.
 * Decorative on its own — the nav row and the upgrade dialog always carry the
 * text that explains it, so the glyph never has to be understood alone. */
export default function CrownIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path d="M2 5.6 5.1 8 8 4l2.9 4L14 5.6l-1.2 6.2a1 1 0 0 1-1 .8H4.2a1 1 0 0 1-1-.8L2 5.6Z" />
    </svg>
  );
}

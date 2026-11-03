export function SearchIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" className={className}>
      <circle cx="10.7" cy="10.7" r="6.2" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M15.2 15.2L20.5 20.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

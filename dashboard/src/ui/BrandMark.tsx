// The product's own mark: three rings, a sweep and the role on it.
//
// One colour (`currentColor`), so the tile it sits on decides how it reads.
// This is the drawing hand-tuned for 20 to 40 px: at the master weights
// (rings 3.0, sweep 3.4, role 5.0 of 100) the rings fall below a device pixel
// at rail size, so rings, sweep and role are heavier here and their places
// stay the same. Below 20 px the innermost ring goes, or the three rings pack
// into a bullseye; nothing in the dashboard draws the mark that small.
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 100 100" aria-hidden="true" focusable="false" data-brand-mark="">
      <g fill="none" stroke="currentColor" strokeWidth="6">
        <circle cx="50" cy="50" r="43.9" />
        <circle cx="50" cy="50" r="28.6" />
        <circle cx="50" cy="50" r="13.2" />
      </g>
      <path d="M50 50 81.18 18.82" stroke="currentColor" strokeWidth="7" strokeLinecap="round" />
      <circle cx="69.37" cy="30.63" r="6.5" fill="currentColor" />
    </svg>
  );
}

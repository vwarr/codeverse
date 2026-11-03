import { Link } from 'react-router-dom';

type LogoVariant = 'default' | 'inverted';

const COLOURS: Record<LogoVariant, { square: string; arc: string }> = {
  default: { square: '#1A1A19', arc: '#F6F6F4' },
  inverted: { square: '#F6F6F4', arc: '#1A1A19' },
};

/** Optical sizing: smaller renders get a heavier arc and a larger dot. */
function opticalSize(size: number): { stroke: number; dot: number } {
  if (size >= 40) {
    return { stroke: 6.5, dot: 4.5 };
  }
  if (size >= 20) {
    return { stroke: 7, dot: 5 };
  }
  return { stroke: 8, dot: 6 };
}

/**
 * The "C" mark: a rounded square, a "C" arc and an accent dot. Decorative: the word "codeverse"
 * next to it is the accessible name. Use `variant="inverted"` on dark backgrounds.
 */
export function LogoMark({
  size = 24,
  variant = 'default',
}: {
  size?: number;
  variant?: LogoVariant;
}) {
  const { square, arc } = COLOURS[variant];
  const { stroke, dot } = opticalSize(size);
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="14" fill={square} />
      <path
        d="M41 21.3A14 14 0 1 0 41 42.7"
        fill="none"
        stroke={arc}
        strokeWidth={stroke}
        strokeLinecap="round"
      />
      <circle cx="47" cy="32" r={dot} fill="var(--cv-accent)" />
    </svg>
  );
}

export function Logo({ variant = 'default' }: { variant?: LogoVariant }) {
  return (
    <Link to="/" className="cv-logo">
      <LogoMark size={24} variant={variant} />
      <span>codeverse</span>
    </Link>
  );
}

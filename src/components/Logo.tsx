import { Link } from 'react-router-dom';

/** The 7-circle mark. Decorative: the word "codeverse" next to it is the accessible name. */
export function LogoMark({ size = 22 }: { size?: number }) {
  const centres: [number, number][] = [
    [14, 14],
    [14, 5.6],
    [14, 22.4],
    [6.7, 9.8],
    [21.3, 9.8],
    [6.7, 18.2],
    [21.3, 18.2],
  ];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      stroke="var(--cv-accent)"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      {centres.map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="4.2" />
      ))}
    </svg>
  );
}

export function Logo() {
  return (
    <Link to="/" className="cv-logo">
      <LogoMark />
      <span>codeverse</span>
    </Link>
  );
}

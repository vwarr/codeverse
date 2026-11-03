import { ReactNode } from 'react';
import { Logo } from './Logo';

/** The bar at the top of every page: the logo on the left, page actions on the right. */
export function AppHeader({ children, width }: { children?: ReactNode; width?: number }) {
  return (
    <header className="cv-header">
      <div className="cv-header-inner" style={width ? { maxWidth: width } : undefined}>
        <Logo />
        {children && <div className="cv-header-end">{children}</div>}
      </div>
    </header>
  );
}

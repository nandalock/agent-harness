import React from 'react';

import { navigate } from '@app/host';

type LinkProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  children?: React.ReactNode;
  prefetch?: boolean;
  replace?: boolean;
  scroll?: boolean;
  shallow?: boolean;
  passHref?: boolean;
  legacyBehavior?: boolean;
  locale?: string | false;
};

const Link = React.forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  {
    href,
    children,
    prefetch: _prefetch,
    replace: _replace,
    scroll: _scroll,
    shallow: _shallow,
    passHref: _passHref,
    legacyBehavior: _legacyBehavior,
    locale: _locale,
    onClick,
    target,
    ...rest
  },
  ref,
) {
  function handleClick(event: React.MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented) return;
    if (target && target !== '_self') return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!href || href.startsWith('http://') || href.startsWith('https://') || href.startsWith('#')) {
      return;
    }
    event.preventDefault();
    navigate(href);
  }

  return (
    <a ref={ref} href={href} target={target} onClick={handleClick} {...rest}>
      {children}
    </a>
  );
});

export default Link;

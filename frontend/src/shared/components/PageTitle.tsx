import { useEffect, useRef } from "react";
import type { PropsWithChildren } from "react";

export function PageTitle({
  children,
  title,
}: PropsWithChildren<{ title: string }>) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} · Fuma`;
    heading.current?.focus();
  }, [title]);
  return (
    <h1 ref={heading} tabIndex={-1}>
      {children}
    </h1>
  );
}

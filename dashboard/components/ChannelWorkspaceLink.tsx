"use client";

import { useRouter } from "next/navigation";
import { useTransition, MouseEvent } from "react";

interface Props {
  href: string;
  className?: string;
  children: React.ReactNode;
  isButton?: boolean;
}

export function ChannelWorkspaceLink({ href, className, children, isButton }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    // If user uses modifier keys (Ctrl, Cmd) let browser handle it to open in new tab
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      return;
    }
    
    e.preventDefault();
    if (isPending) return;

    startTransition(() => {
      router.push(href);
    });
  };

  if (isButton) {
    return (
      <a
        href={href}
        onClick={handleClick}
        aria-busy={isPending}
        className={`${className} ${
          isPending ? "opacity-80 cursor-wait pointer-events-none" : ""
        }`}
      >
        {isPending ? (
          <>
            <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent" />
            Đang mở Workspace…
          </>
        ) : (
          children
        )}
      </a>
    );
  }

  // Normal link format
  return (
    <a
      href={href}
      onClick={handleClick}
      aria-busy={isPending}
      className={`${className} ${
        isPending ? "opacity-70 cursor-wait pointer-events-none" : ""
      }`}
    >
      {children}
    </a>
  );
}

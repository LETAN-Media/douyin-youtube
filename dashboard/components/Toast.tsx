"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

const ToastContext = createContext<{
  toast: (message: string, kind?: ToastKind) => void;
}>({ toast: () => {} });

let nextId = 1;

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, kind: ToastKind = "info") => {
    const id = nextId++;
    setItems((prev) => [...prev.slice(-3), { id, kind, message }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 4200);
  }, []);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4 sm:items-end sm:pr-6"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={`toast-enter pointer-events-auto w-full max-w-sm rounded-xl border px-4 py-3 text-sm shadow-lg ${
              t.kind === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                : t.kind === "error"
                  ? "border-red-200 bg-red-50 text-red-900"
                  : "border-slate-200 bg-white text-slate-800"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

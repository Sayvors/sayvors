"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { makeQueryClient } from "@/lib/query-client";

/**
 * Wraps the app in a QueryClient. A single instance per browser session —
 * the useState initializer guarantees it is created once per mount and is not
 * reset by React StrictMode's double-invocation.
 */
export default function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => makeQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

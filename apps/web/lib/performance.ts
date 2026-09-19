import dynamic from "next/dynamic";
import { ComponentType } from "react";

export function lazyLoad<T extends Record<string, unknown>>(
  factory: () => Promise<{ default: ComponentType<T> }>,
  options?: Record<string, unknown>
) {
  return dynamic(factory, { ssr: false, ...options });
}

export function preload(factory: () => Promise<{ default: ComponentType }>) {
  if (typeof window !== "undefined") {
    factory();
  }
}

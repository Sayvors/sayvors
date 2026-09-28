"use client";

import { useSyncExternalStore } from "react";

/**
 * Shared open/close state for the Ask Sayvors secondary sidebar.
 * Module-level store + useSyncExternalStore (same pattern as the
 * onboarding checklist) so the Header toggle and the sidebar stay
 * in sync without prop drilling through the layout.
 */

const KEY = "sayvors.chat.open";

const listeners = new Set<() => void>();

let current = false;
let initialized = false;

function ensureInit() {
  if (initialized || typeof window === "undefined") return;
  try {
    current = window.localStorage.getItem(KEY) === "1";
  } catch {
    current = false;
  }
  initialized = true;
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

function getSnapshot(): boolean {
  ensureInit();
  return current;
}

function getServerSnapshot(): boolean {
  return false;
}

export function isChatOpen(): boolean {
  return getSnapshot();
}

export function setChatOpen(next: boolean) {
  ensureInit();
  if (current === next) return;
  current = next;
  try {
    window.localStorage.setItem(KEY, next ? "1" : "0");
  } catch {
    /* private mode — session-only */
  }
  listeners.forEach((l) => l());
}

export function toggleChat() {
  setChatOpen(!getSnapshot());
}

export function useChatOpen(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

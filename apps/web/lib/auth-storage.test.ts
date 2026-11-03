import { beforeEach, describe, expect, it } from "vitest";
import { SESSION_LOCAL_KEYS, clearSessionLocalState } from "./auth-storage";

describe("clearSessionLocalState", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("removes user data and dead credentials", () => {
    for (const key of SESSION_LOCAL_KEYS) {
      window.localStorage.setItem(key, "value");
    }

    clearSessionLocalState();

    for (const key of SESSION_LOCAL_KEYS) {
      expect(window.localStorage.getItem(key)).toBeNull();
    }
  });

  it("keeps device preferences", () => {
    window.localStorage.setItem("sayvors-theme", "dark");
    window.localStorage.setItem("sayvors.locale", "ar");
    window.localStorage.setItem("sayvors.chat.sessions", "[]");

    clearSessionLocalState();

    expect(window.localStorage.getItem("sayvors-theme")).toBe("dark");
    expect(window.localStorage.getItem("sayvors.locale")).toBe("ar");
    expect(window.localStorage.getItem("sayvors.chat.sessions")).toBeNull();
  });
});

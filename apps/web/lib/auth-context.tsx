"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let _accessToken: string | null = null;
export function getAccessToken(): string | null { return _accessToken; }
export function setAccessToken(token: string | null) { _accessToken = token; }

interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  email_verified: boolean;
  onboarded: boolean;
  theme?: string;
  language?: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  signup: (data: SignupData) => Promise<{ verification_token?: string }>;
  login: (data: LoginData) => Promise<void>;
  googleLogin: (idToken: string) => Promise<User>;
  facebookLogin: (accessToken: string) => Promise<User>;
  logout: (allDevices?: boolean) => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (token: string, password: string) => Promise<void>;
  verifyEmail: (token: string) => Promise<void>;
  verifyOtp: (email: string, code: string) => Promise<void>;
  resendOtp: (email: string) => Promise<void>;
  refreshAuth: () => Promise<void>;
}

interface SignupData {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  business_type?: string;
  referral?: string;
  newsletter?: boolean;
}

interface LoginData {
  email: string;
  password: string;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("csrf_token="));
  return match ? match.split("=")[1] : null;
}

function buildHeaders(isForm = false): Record<string, string> {
  const headers: Record<string, string> = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  if (_accessToken) headers["Authorization"] = `Bearer ${_accessToken}`;
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const isForm = options.body instanceof FormData;
  const method = options.method || "GET";
  const headers = {
    ...buildHeaders(isForm),
    ...(options.headers as Record<string, string>),
  };

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && path !== "/api/v1/auth/refresh") {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return fetch(`${API_URL}${path}`, { ...options, headers: buildHeaders(isForm), credentials: "include" });
    }
    setAccessToken(null);
    // Don't redirect if already on an auth page — prevents infinite reload loop
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/signup") && !window.location.pathname.startsWith("/forgot-password") && !window.location.pathname.startsWith("/reset-password") && !window.location.pathname.startsWith("/verify-email") && !window.location.pathname.startsWith("/verify-otp")) {
      window.location.href = "/login";
    }
  }

  return response;
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.access_token) setAccessToken(data.access_token);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await apiFetch("/api/v1/auth/me");
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const signup = async (data: SignupData) => {
    const res = await apiFetch("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Signup failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
    return { verification_token: result.verification_token };
  };

  const login = async (data: LoginData) => {
    const res = await apiFetch("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json();
      const detail = (err as any).detail;
      // Backend returns {code: "email_not_verified"} as 403 for gated accounts.
      const error = new Error(typeof detail === "string" ? detail : detail?.message || "Login failed") as Error & { code?: string };
      if (typeof detail === "object" && detail?.code) error.code = detail.code;
      else if (res.status === 403) error.code = "email_not_verified";
      throw error;
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
  };

  const googleLogin = async (idToken: string): Promise<User> => {
    const res = await apiFetch("/api/v1/auth/google/verify", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    });

    if (!res.ok) {
      const err = await res.json();
      const detail = (err as any).detail;
      throw new Error(typeof detail === "string" ? detail : "Google sign-in failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
    return result.user as User;
  };

  const facebookLogin = async (accessToken: string): Promise<User> => {
    const res = await apiFetch("/api/v1/auth/facebook/verify", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken }),
    });

    if (!res.ok) {
      const err = await res.json();
      const detail = (err as any).detail;
      throw new Error(typeof detail === "string" ? detail : "Facebook sign-in failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    setUser(result.user);
    return result.user as User;
  };

  const logout = async (allDevices = false) => {
    await apiFetch("/api/v1/auth/logout", {
      method: "POST",
      body: JSON.stringify({ all_devices: allDevices }),
    });
    setAccessToken(null);
    setUser(null);
    window.location.href = "/login";
  };

  const forgotPassword = async (email: string) => {
    const res = await apiFetch("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Request failed");
    }
  };

  const resetPassword = async (token: string, password: string) => {
    const res = await apiFetch("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Reset failed");
    }
  };

  const verifyEmail = async (token: string) => {
    const res = await apiFetch("/api/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Verification failed");
    }

    await checkAuth();
  };

  const verifyOtp = async (email: string, code: string) => {
    const res = await apiFetch("/api/v1/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(typeof err.detail === "string" ? err.detail : "Verification failed");
    }

    const result = await res.json();
    if (result.access_token) setAccessToken(result.access_token);
    if (result.user) setUser(result.user);
  };

  const resendOtp = async (email: string) => {
    const res = await apiFetch("/api/v1/email/otp/request", {
      method: "POST",
      body: JSON.stringify({ email, purpose: "verification" }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(typeof err.detail === "string" ? err.detail : "Could not resend code");
    }
  };

  const refreshAuth = async () => {
    await checkAuth();
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signup,
        login,
        googleLogin,
        facebookLogin,
        logout,
        forgotPassword,
        resetPassword,
        verifyEmail,
        verifyOtp,
        resendOtp,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

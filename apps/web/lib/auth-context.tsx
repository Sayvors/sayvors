"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  email_verified: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  signup: (data: SignupData) => Promise<{ verification_token?: string }>;
  login: (data: LoginData) => Promise<void>;
  logout: (allDevices?: boolean) => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (token: string, password: string) => Promise<void>;
  verifyEmail: (token: string) => Promise<void>;
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

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const csrfToken = document.cookie
    .split("; ")
    .find((c) => c.startsWith("csrf_token="))
    ?.split("=")[1];

  if (csrfToken && ["POST", "PUT", "DELETE", "PATCH"].includes(options.method || "GET")) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && path !== "/auth/refresh") {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retryResponse = await fetch(`${API_URL}${path}`, {
        ...options,
        headers,
        credentials: "include",
      });
      return retryResponse;
    }
  }

  return response;
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await apiFetch("/auth/me");
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
    const res = await apiFetch("/auth/signup", {
      method: "POST",
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Signup failed");
    }

    const result = await res.json();
    setUser(result.user);
    return { verification_token: result.verification_token };
  };

  const login = async (data: LoginData) => {
    const res = await apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Login failed");
    }

    const result = await res.json();
    setUser(result.user);
  };

  const logout = async (allDevices = false) => {
    await apiFetch("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ all_devices: allDevices }),
    });
    setUser(null);
  };

  const forgotPassword = async (email: string) => {
    const res = await apiFetch("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Request failed");
    }
  };

  const resetPassword = async (token: string, password: string) => {
    const res = await apiFetch("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Reset failed");
    }
  };

  const verifyEmail = async (token: string) => {
    const res = await apiFetch("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Verification failed");
    }

    await checkAuth();
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
        logout,
        forgotPassword,
        resetPassword,
        verifyEmail,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

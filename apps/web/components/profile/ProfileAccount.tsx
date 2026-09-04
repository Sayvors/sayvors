"use client";

import { useState } from "react";

export default function ProfileAccount() {
  const [email, setEmail] = useState("syed@sayvors.com");
  const [phone, setPhone] = useState("+1 (555) 123-4567");
  const [editingEmail, setEditingEmail] = useState(false);
  const [editingPhone, setEditingPhone] = useState(false);

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <h2 className="text-[14px] font-bold text-ink mb-4">Account</h2>
      <div className="space-y-4">
        {/* Email */}
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Email Address</label>
          <div className="mt-1 flex items-center gap-2">
            {editingEmail ? (
              <>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="flex-1 rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
                />
                <button
                  onClick={() => setEditingEmail(false)}
                  className="rounded-lg bg-deep-violet px-3 py-2 text-[11px] font-bold text-white transition hover:bg-deep-violet/90"
                >
                  Save
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 text-[12px] text-ink/70">{email}</span>
                <button
                  onClick={() => setEditingEmail(true)}
                  className="text-[11px] font-semibold text-deep-violet transition hover:text-deep-violet/80"
                >
                  Change
                </button>
              </>
            )}
          </div>
        </div>

        {/* Phone */}
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Phone Number</label>
          <div className="mt-1 flex items-center gap-2">
            {editingPhone ? (
              <>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="flex-1 rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
                />
                <button
                  onClick={() => setEditingPhone(false)}
                  className="rounded-lg bg-deep-violet px-3 py-2 text-[11px] font-bold text-white transition hover:bg-deep-violet/90"
                >
                  Save
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 text-[12px] text-ink/70">{phone}</span>
                <button
                  onClick={() => setEditingPhone(true)}
                  className="text-[11px] font-semibold text-deep-violet transition hover:text-deep-violet/80"
                >
                  Change
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

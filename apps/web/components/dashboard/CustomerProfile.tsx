"use client";

import { useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { updateCustomerCategory } from "@/lib/api-customers";
import type { Customer, CustomerProfile as CustomerProfileData } from "@/lib/api-customers";

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";

const PRIORITY_CHIP: Record<string, string> = {
  urgent: "bg-[#FF4F6E]/10 text-[#C4304B]",
  high: "bg-amber-500/10 text-amber-700",
  normal: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  low: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

export default function CustomerProfile({
  profile,
  selected,
  onCategoryChanged,
}: {
  profile: CustomerProfileData;
  selected: Customer;
  onCategoryChanged?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [cat, setCat] = useState(profile.category || "normal");
  const [prio, setPrio] = useState(profile.priority || "normal");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await updateCustomerCategory(selected.channel_id, selected.key, cat, prio);
      onCategoryChanged?.();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Identity */}
      <section>
        <div className="flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-deep-violet/10 text-[14px] font-bold text-deep-violet">
            {(profile.identity.name || "?").slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className={`truncate text-[15px] font-bold ${INK}`}>
              {profile.identity.name || "Unknown sender"}
            </p>
            <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--ui-ink-2)]">
              <PlatformMark platform={profile.identity.platform as never} size={12} />
              <span>{profile.identity.platform}</span>
              {profile.identity.username && <span>· @{profile.identity.username}</span>}
            </div>
            {profile.identity.contact_phone && (
              <p className={`mt-0.5 truncate text-[11px] ${INK2}`}>{profile.identity.contact_phone}</p>
            )}
            {profile.identity.channel_name && (
              <p className={`mt-0.5 truncate text-[11px] ${INK2}`}>{profile.identity.channel_name}</p>
            )}
          </div>
        </div>
      </section>

      {/* Categorization */}
      <section>
        <h3 className={`mb-2 text-[11px] font-bold uppercase tracking-wide ${INK2}`}>Categorization</h3>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
            {profile.category || "normal"}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${PRIORITY_CHIP[profile.priority || "normal"]}`}>
            {profile.priority || "normal"}
          </span>
          {profile.important && (
            <span className="rounded-full bg-[#FF4F6E]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#C4304B]">
              Important
            </span>
          )}
          {profile.can_reply === false && (
            <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
              No reply from here
            </span>
          )}
        </div>
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className={`mt-2 text-[11px] font-semibold ${INK2} hover:text-[var(--ui-ink)]`}
          >
            Override category / priority
          </button>
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select value={cat} onChange={(e) => setCat(e.target.value)} className="input-field w-32 text-[11px]">
              <option value="complaint">complaint</option>
              <option value="feedback">feedback</option>
              <option value="inquiry">inquiry</option>
              <option value="review">review</option>
              <option value="other">other</option>
              <option value="normal">normal</option>
            </select>
            <select value={prio} onChange={(e) => setPrio(e.target.value)} className="input-field w-24 text-[11px]">
              <option value="urgent">urgent</option>
              <option value="high">high</option>
              <option value="normal">normal</option>
              <option value="low">low</option>
            </select>
            <button
              onClick={() => void save()}
              disabled={saving}
              className="rounded-[8px] bg-[var(--ui-ink)] px-3 py-1 text-[11px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className={`text-[11px] font-semibold ${INK2}`}
            >
              Cancel
            </button>
          </div>
        )}
      </section>

      {/* Lead */}
      {profile.lead && (
        <section>
          <h3 className={`mb-2 text-[11px] font-bold uppercase tracking-wide ${INK2}`}>Lead</h3>
          <div className="space-y-1.5 text-[12px]">
            <div className="flex items-center gap-2">
              <span className={`font-semibold ${INK}`}>Stage</span>
              <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
                {profile.lead.stage}
              </span>
            </div>
            {profile.lead.intent && (
              <div><span className={`font-semibold ${INK}`}>Intent: </span><span className={INK2}>{profile.lead.intent}</span></div>
            )}
            {profile.lead.request && (
              <div><span className={`font-semibold ${INK}`}>Request: </span><span className={INK2}>{profile.lead.request}</span></div>
            )}
            {profile.lead.summary && (
              <div><span className={`font-semibold ${INK}`}>Summary: </span><span className={INK2}>{profile.lead.summary}</span></div>
            )}
            {profile.lead.phone_number && (
              <div><span className={`font-semibold ${INK}`}>Phone: </span><span className={INK2}>{profile.lead.phone_number}</span></div>
            )}
            {profile.lead.opt_out && (
              <div className="text-[11px] font-semibold text-[#C4304B]">Opted out of messaging</div>
            )}
          </div>
        </section>
      )}

      {/* Reviews (Google) */}
      {profile.reviews.length > 0 && (
        <section>
          <h3 className={`mb-2 text-[11px] font-bold uppercase tracking-wide ${INK2}`}>Google reviews</h3>
          <div className="space-y-3">
            {profile.reviews.map((r) => (
              <div key={r.id} className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-bold text-amber-600">{"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)}</span>
                  <span className={`text-[10px] font-semibold uppercase tracking-wide ${INK2}`}>{r.status}</span>
                </div>
                {r.review_text && (
                  <p className={`mt-1 text-[12px] ${INK}`}>{r.review_text}</p>
                )}
                {r.reply_text && (
                  <div className="mt-2 border-l-2 border-deep-violet/30 pl-2">
                    <p className={`text-[10px] font-bold uppercase tracking-wide ${INK2}`}>Our reply</p>
                    <p className={`text-[12px] ${INK}`}>{r.reply_text}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Conversation */}
      <section>
        <h3 className={`mb-2 text-[11px] font-bold uppercase tracking-wide ${INK2}`}>
          Conversation ({profile.messages.length})
        </h3>
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {profile.messages.map((m) => (
            <div
              key={m.id}
              className={`rounded-[8px] px-3 py-2 text-[12px] ${
                m.direction === "inbound"
                  ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                  : "bg-deep-violet/5 text-[var(--ui-ink)]"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className={`text-[10px] font-bold uppercase tracking-wide ${INK2}`}>
                  {m.direction === "inbound" ? "Them" : "You"}
                </span>
                <span className={`text-[10px] ${INK2}`}>
                  {m.created_at ? new Date(m.created_at).toLocaleString() : ""}
                </span>
              </div>
              <p className="mt-0.5 whitespace-pre-wrap">{m.content || "—"}</p>
            </div>
          ))}
          {profile.messages.length === 0 && (
            <p className={`text-[12px] ${INK2}`}>No messages.</p>
          )}
        </div>
      </section>
    </div>
  );
}

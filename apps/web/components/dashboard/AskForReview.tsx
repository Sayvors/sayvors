"use client";

import { useState } from "react";

type ReviewChannel = "whatsapp" | "contacts" | "email";
type PlatformTab = "all" | "whatsapp" | "instagram" | "facebook";

interface DummyContact {
  id: string;
  platform: string;
  name: string;
  number: string;
}

interface BusinessProfile {
  id: string;
  name: string;
  reviewUrl: string;
}

const DUMMY_CONTACTS: DummyContact[] = [
  { id: "wa-1", platform: "whatsapp", name: "Ahmed Khan", number: "923001234567" },
  { id: "wa-2", platform: "whatsapp", name: "Sara Ali", number: "923011234567" },
  { id: "wa-3", platform: "whatsapp", name: "Usman Malik", number: "923021234567" },
  { id: "ig-1", platform: "instagram", name: "Fatima Noor", number: "923031234567" },
  { id: "ig-2", platform: "instagram", name: "Hassan Raza", number: "923041234567" },
  { id: "fb-1", platform: "facebook", name: "Ayesha Siddiqui", number: "923051234567" },
  { id: "fb-2", platform: "facebook", name: "Bilal Ahmed", number: "923061234567" },
];

const DUMMY_BUSINESSES: BusinessProfile[] = [
  { id: "biz-1", name: "Sayvors Company Main Branch - Al Malqa", reviewUrl: "https://www.google.com/maps/search/?api=1&query=Sayvors+Al+Malqa" },
  { id: "biz-2", name: "Sayvors Company - Olaya Branch", reviewUrl: "https://www.google.com/maps/search/?api=1&query=Sayvors+Olaya" },
  { id: "biz-3", name: "Sayvors Company - Diplomatic Quarter", reviewUrl: "https://www.google.com/maps/search/?api=1&query=Sayvors+Diplomatic+Quarter" },
];

const REVIEW_MESSAGE = "Hi! We hope you enjoyed your experience with us. Would you mind leaving us a quick review? It really helps our business grow. Thank you!";

const PLATFORM_META: Record<string, { label: string; color: string; bg: string }> = {
  whatsapp: { label: "WhatsApp", color: "text-emerald-600", bg: "bg-emerald/10" },
  instagram: { label: "Instagram", color: "text-pink-600", bg: "bg-pink/10" },
  facebook: { label: "Facebook", color: "text-blue-600", bg: "bg-blue/10" },
};

export default function AskForReview() {
  const [activeChannel, setActiveChannel] = useState<ReviewChannel | null>(null);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [selectedContactIds, setSelectedContactIds] = useState<Set<string>>(new Set());
  const [selectedBusinessIds, setSelectedBusinessIds] = useState<Set<string>>(new Set());
  const [platformTab, setPlatformTab] = useState<PlatformTab>("all");

  const filteredContacts = platformTab === "all"
    ? DUMMY_CONTACTS
    : DUMMY_CONTACTS.filter((c) => c.platform === platformTab);

  const allContactsSelected = filteredContacts.length > 0 && filteredContacts.every((c) => selectedContactIds.has(c.id));
  const allBusinessesSelected = DUMMY_BUSINESSES.length > 0 && DUMMY_BUSINESSES.every((b) => selectedBusinessIds.has(b.id));

  const toggleAllContacts = () => {
    if (allContactsSelected) {
      setSelectedContactIds(new Set());
    } else {
      setSelectedContactIds(new Set(filteredContacts.map((c) => c.id)));
    }
  };

  const toggleAllBusinesses = () => {
    if (allBusinessesSelected) {
      setSelectedBusinessIds(new Set());
    } else {
      setSelectedBusinessIds(new Set(DUMMY_BUSINESSES.map((b) => b.id)));
    }
  };

  const toggleContact = (id: string) => {
    setSelectedContactIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleBusiness = (id: string) => {
    setSelectedBusinessIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleWhatsAppSend = (number?: string) => {
    const cleaned = (number ?? phoneNumber).replace(/[^\d]/g, "");
    if (!cleaned) return;
    const url = `https://wa.me/${cleaned}?text=${encodeURIComponent(REVIEW_MESSAGE)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleSendSelected = () => {
    const selected = DUMMY_CONTACTS.filter((c) => selectedContactIds.has(c.id));
    for (const c of selected) {
      if (c.platform === "whatsapp") {
        handleWhatsAppSend(c.number);
      }
    }
  };

  return (
    <section
      aria-label="Ask for review"
      className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
            <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
          </svg>
        </span>
        <div>
          <h2 className="text-[14px] font-bold text-ink">Ask for Review</h2>
          <p className="text-[11px] text-ink/45">Reach out to customers directly</p>
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-ink/40">
          Select business for review
        </p>
        <div className="space-y-1.5">
          {DUMMY_BUSINESSES.map((biz) => (
            <label
              key={biz.id}
              className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg bg-white px-3 py-2 transition hover:bg-ink/[0.02]"
            >
              <input
                type="checkbox"
                checked={selectedBusinessIds.has(biz.id)}
                onChange={() => toggleBusiness(biz.id)}
                className="h-3.5 w-3.5 rounded border-ink/20 text-deep-violet-600 accent-deep-violet-600"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] font-medium text-ink">{biz.name}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <button
          onClick={() => setActiveChannel(activeChannel === "whatsapp" ? null : "whatsapp")}
          className={`group flex flex-row items-center gap-3 rounded-xl border-2 p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 sm:flex-col sm:gap-2 sm:p-4 sm:text-center ${
            activeChannel === "whatsapp"
              ? "border-deep-violet/40 bg-deep-violet/[0.06]"
              : "border-ink/[0.06] bg-white hover:border-deep-violet/20 hover:bg-deep-violet/[0.03]"
          }`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald/10 text-emerald-600 transition group-hover:scale-105">
            <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5" aria-hidden>
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
            </svg>
          </span>
          <div>
            <p className="text-[12px] font-bold text-ink">WhatsApp</p>
            <p className="text-[10px] text-ink/45">Direct message</p>
          </div>
        </button>

        <button
          onClick={() => setActiveChannel(activeChannel === "contacts" ? null : "contacts")}
          className={`group flex flex-row items-center gap-3 rounded-xl border-2 p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 sm:flex-col sm:gap-2 sm:p-4 sm:text-center ${
            activeChannel === "contacts"
              ? "border-deep-violet/40 bg-deep-violet/[0.06]"
              : "border-ink/[0.06] bg-white hover:border-deep-violet/20 hover:bg-deep-violet/[0.03]"
          }`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky/10 text-sky-600 transition group-hover:scale-105">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
              <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 00-3-3.87" />
              <path d="M16 3.13a4 4 0 010 7.75" />
            </svg>
          </span>
          <div>
            <p className="text-[12px] font-bold text-ink">Contacts</p>
            <p className="text-[10px] text-ink/45">{DUMMY_CONTACTS.length} saved</p>
          </div>
        </button>

        <button
          onClick={() => setActiveChannel(activeChannel === "email" ? null : "email")}
          className={`group flex flex-row items-center gap-3 rounded-xl border-2 p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 sm:flex-col sm:gap-2 sm:p-4 sm:text-center ${
            activeChannel === "email"
              ? "border-deep-violet/40 bg-deep-violet/[0.06]"
              : "border-ink/[0.06] bg-white hover:border-deep-violet/20 hover:bg-deep-violet/[0.03]"
          }`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber/10 text-amber-600 transition group-hover:scale-105">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
              <polyline points="22,6 12,13 2,6" />
            </svg>
          </span>
          <div>
            <p className="text-[12px] font-bold text-ink">Email</p>
            <p className="text-[10px] text-ink/45">Send request</p>
          </div>
        </button>
      </div>

      {activeChannel === "whatsapp" && (
        <div className="mt-4 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4">
          <p className="text-[12px] font-semibold text-ink">Send WhatsApp review request</p>
          <p className="mt-1 text-[11px] text-ink/50">
            Opens WhatsApp with a pre-filled message asking for a review.
          </p>

          <div className="mt-3">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">
                WhatsApp contacts
              </p>
              <button
                onClick={toggleAllContacts}
                className="text-[10px] font-bold text-deep-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                {allContactsSelected ? "Deselect all" : "Select all"}
              </button>
            </div>
            <div className="max-h-40 space-y-1.5 overflow-y-auto">
              {DUMMY_CONTACTS.filter((c) => c.platform === "whatsapp").map((contact) => (
                <label
                  key={contact.id}
                  className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg bg-white px-3 py-2 transition hover:bg-emerald/5"
                >
                  <input
                    type="checkbox"
                    checked={selectedContactIds.has(contact.id)}
                    onChange={() => toggleContact(contact.id)}
                    className="h-3.5 w-3.5 rounded border-ink/20 text-emerald-600 accent-emerald-600"
                  />
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald/10 text-emerald-600">
                    <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
                    </svg>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-medium text-ink">{contact.name}</span>
                    <span className="block truncate text-[10px] text-ink/40">{contact.number}</span>
                  </span>
                </label>
              ))}
            </div>
            {selectedContactIds.size > 0 && (
              <button
                onClick={handleSendSelected}
                className="mt-2 w-full rounded-xl bg-emerald px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-emerald/25 outline-none transition hover:bg-emerald/90 focus-visible:ring-2 focus-visible:ring-emerald/40 active:scale-[0.99]"
              >
                Send to {selectedContactIds.size} selected contact{selectedContactIds.size > 1 ? "s" : ""}
              </button>
            )}
          </div>

          <div className="mt-3 border-t border-ink/[0.06] pt-3">
            <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-ink/40">
              Or send to new number
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="tel"
                placeholder="Phone number"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                className="input-field flex-1"
              />
              <button
                onClick={() => handleWhatsAppSend()}
                disabled={!phoneNumber.trim()}
                className="rounded-lg bg-emerald px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-emerald/25 outline-none transition hover:bg-emerald/90 focus-visible:ring-2 focus-visible:ring-emerald/40 active:scale-[0.98] disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}

      {activeChannel === "contacts" && (
        <div className="mt-4 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4">
          <p className="text-[12px] font-semibold text-ink">Contacts saved in Sayvors</p>
          <p className="mt-1 text-[11px] text-ink/50">
            These are customers you&apos;ve connected with through integrated channels.
          </p>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {(["all", "whatsapp", "instagram", "facebook"] as PlatformTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setPlatformTab(tab)}
                className={`rounded-md px-2.5 py-1 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  platformTab === tab
                    ? "bg-white text-deep-violet shadow-sm"
                    : "text-ink/45 hover:text-ink/70"
                }`}
              >
                {tab === "all" ? "All" : PLATFORM_META[tab]?.label ?? tab}
              </button>
            ))}
          </div>

          <div className="mt-3">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">
                {platformTab === "all" ? "All contacts" : PLATFORM_META[platformTab]?.label}
              </p>
              <button
                onClick={toggleAllContacts}
                className="text-[10px] font-bold text-deep-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                {allContactsSelected ? "Deselect all" : "Select all"}
              </button>
            </div>
            <div className="max-h-40 space-y-1.5 overflow-y-auto">
              {filteredContacts.map((contact) => {
                const meta = PLATFORM_META[contact.platform];
                return (
                  <label
                    key={contact.id}
                    className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg bg-white px-3 py-2 transition hover:bg-ink/[0.02]"
                  >
                    <input
                      type="checkbox"
                      checked={selectedContactIds.has(contact.id)}
                      onChange={() => toggleContact(contact.id)}
                      className="h-3.5 w-3.5 rounded border-ink/20 text-deep-violet-600 accent-deep-violet-600"
                    />
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${meta?.bg ?? "bg-ink/[0.06]"} ${meta?.color ?? "text-ink/50"}`}>
                      <span className="text-[10px] font-bold">
                        {contact.name[0]?.toUpperCase() ?? "?"}
                      </span>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] font-medium text-ink">{contact.name}</span>
                      <span className="block truncate text-[10px] text-ink/40">{contact.number}</span>
                    </span>
                    <span className={`shrink-0 text-[10px] font-bold ${meta?.color ?? "text-ink/40"}`}>
                      {meta?.label ?? contact.platform}
                    </span>
                  </label>
                );
              })}
            </div>
            {selectedContactIds.size > 0 && (
              <button
                onClick={handleSendSelected}
                className="mt-2 w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99]"
              >
                Send to {selectedContactIds.size} selected contact{selectedContactIds.size > 1 ? "s" : ""}
              </button>
            )}
          </div>
        </div>
      )}

      {activeChannel === "email" && (
        <div className="mt-4 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4">
          <p className="text-[12px] font-semibold text-ink">Send email review request</p>
          <p className="mt-1 text-[11px] text-ink/50">
            Opens your email client with a pre-filled review request.
          </p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              type="email"
              placeholder="Customer email"
              className="input-field flex-1"
            />
            <button className="rounded-lg bg-amber px-3 py-1.5 text-[11px] font-bold text-white shadow-sm shadow-amber/25 outline-none transition hover:bg-amber/90 focus-visible:ring-2 focus-visible:ring-amber/40 active:scale-[0.98] disabled:opacity-50">
              Send
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

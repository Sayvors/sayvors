/**
 * CSV parsing + contact-column detection for the bulk review-ask uploader.
 *
 * Real merchant exports are messy: 40 columns, quoted commas, currency cells,
 * locations, notes. We therefore do two things instead of guessing per cell:
 *
 * 1. Parse RFC 4180 properly (quotes, escaped quotes, commas inside quotes).
 * 2. Map columns by header aliases first, then by value shape. Only the
 *    email/phone and name columns are read; every other column is ignored.
 *
 * If detection is ambiguous the UI lets the user pick the columns explicitly.
 */

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
  hasHeader: boolean;
}

const EMAIL_ALIASES = [
  "email", "e-mail", "emailaddress", "email address", "mail", "workemail",
  "work email", "primaryemail", "primary email", "contactemail", "contact email",
  "customeremail", "customer email",
];
const PHONE_ALIASES = [
  "phone", "phonenumber", "phone number", "mobile", "mobilenumber", "mobile number",
  "whatsapp", "whatsappnumber", "whatsapp number", "cell", "cellphone", "cell phone",
  "telephone", "tel", "contactnumber", "contact number", "contactphone", "contact phone",
];
const NAME_ALIASES = [
  "name", "fullname", "full name", "customername", "customer name", "contactname",
  "contact name", "firstname", "first name", "givenname", "given name",
];
const LAST_NAME_ALIASES = ["lastname", "last name", "surname", "familyname", "family name"];

function norm(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function aliasMatch(header: string, aliases: string[]): boolean {
  const n = norm(header);
  return aliases.some((a) => n === norm(a) || n.includes(norm(a)));
}

export function parseCsv(text: string): ParsedCsv {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cell.trim());
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell.trim());
      cell = "";
      if (row.some((c) => c.length > 0)) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell.trim());
  if (row.some((c) => c.length > 0)) rows.push(row);

  if (rows.length === 0) return { headers: [], rows: [], hasHeader: false };

  const first = rows[0];
  const headerLike = first.some(
    (c) => aliasMatch(c, EMAIL_ALIASES) || aliasMatch(c, PHONE_ALIASES) || aliasMatch(c, NAME_ALIASES) || aliasMatch(c, LAST_NAME_ALIASES)
  );
  // A first row containing an email/phone in any cell is data, not a header.
  const firstLooksData = first.some((c) => EMAIL_RE.test(c) || phoneDigits(c) !== null);
  const hasHeader = headerLike && !firstLooksData;

  return {
    headers: hasHeader ? first : first.map((_, i) => `Column ${i + 1}`),
    rows: hasHeader ? rows.slice(1) : rows,
    hasHeader,
  };
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/** Digits-only phone if it looks like a real number, otherwise null. */
export function phoneDigits(value: string): string | null {
  const raw = value.trim();
  if (!raw || isEmail(raw)) return null;
  const digits = raw.replace(/[^\d]/g, "");
  if (digits.length < 7 || digits.length > 15) return null;
  // Reject obvious years / IDs / currency amounts.
  if (/^(19|20)\d{2}$/.test(digits)) return null;
  if (/^\d+\.\d+$/.test(raw)) return null;
  return digits;
}

export function isPhone(value: string): boolean {
  return phoneDigits(value) !== null;
}

export interface ColumnGuess {
  email: number | null;
  phone: number | null;
  name: number | null;
  lastName: number | null;
}

function columnScore(rows: string[][], index: number, test: (v: string) => boolean): number {
  const sample = rows.slice(0, 50).map((r) => r[index] ?? "").filter((v) => v.length > 0);
  if (sample.length === 0) return 0;
  return sample.filter(test).length / sample.length;
}

export function guessColumns(parsed: ParsedCsv): ColumnGuess {
  const { headers, rows } = parsed;
  const emailHeader = headers.findIndex((h) => aliasMatch(h, EMAIL_ALIASES));
  const phoneHeader = headers.findIndex((h) => aliasMatch(h, PHONE_ALIASES));
  const nameHeader = headers.findIndex((h) => aliasMatch(h, NAME_ALIASES));
  const lastHeader = headers.findIndex((h) => aliasMatch(h, LAST_NAME_ALIASES));

  const emailByValue = headers
    .map((_, i) => i)
    .map((i) => ({ i, score: columnScore(rows, i, isEmail) }))
    .sort((a, b) => b.score - a.score)[0];
  const phoneByValue = headers
    .map((_, i) => i)
    .map((i) => ({ i, score: columnScore(rows, i, isPhone) }))
    .sort((a, b) => b.score - a.score)[0];

  return {
    email: emailHeader >= 0 ? emailHeader : emailByValue && emailByValue.score >= 0.5 ? emailByValue.i : null,
    phone: phoneHeader >= 0 ? phoneHeader : phoneByValue && phoneByValue.score >= 0.5 ? phoneByValue.i : null,
    name: nameHeader >= 0 ? nameHeader : null,
    lastName: lastHeader >= 0 ? lastHeader : null,
  };
}

export interface ExtractedContact {
  email?: string;
  phone?: string;
  name?: string;
}

export function extractContacts(
  parsed: ParsedCsv,
  guess: ColumnGuess,
  channel: "email" | "whatsapp"
): { contacts: ExtractedContact[]; invalid: number } {
  const contacts: ExtractedContact[] = [];
  let invalid = 0;
  const seen = new Set<string>();

  for (const row of parsed.rows) {
    const email = guess.email !== null ? (row[guess.email] ?? "").trim() : "";
    const phone = guess.phone !== null ? phoneDigits(row[guess.phone] ?? "") : null;
    const first = guess.name !== null ? (row[guess.name] ?? "").trim() : "";
    const last = guess.lastName !== null ? (row[guess.lastName] ?? "").trim() : "";
    const name = [first, last].filter(Boolean).join(" ").trim() || undefined;

    const value = channel === "email" ? email : phone ? `+${phone}` : "";
    if (channel === "email" ? !isEmail(value) : !phone) {
      invalid++;
      continue;
    }
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    contacts.push({
      email: channel === "email" ? value : undefined,
      phone: channel === "whatsapp" ? `+${phone}` : undefined,
      name,
    });
  }
  return { contacts, invalid };
}

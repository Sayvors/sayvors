import { describe, expect, it } from "vitest";
import { extractContacts, guessColumns, parseCsv } from "./csv";

describe("parseCsv", () => {
  it("maps email/name from a wide messy sheet and ignores other columns", () => {
    const csv = [
      "Location,Manager,Work Email,Full Name,Revenue,Notes,Phone",
      'Riyadh,Ali,sara@example.com,Sara Ahmed,"1,200 SAR",VIP,+966500000001',
      'Jeddah,Mona,omar@example.com,Omar Ali,900 SAR,"called, twice",+966500000002',
    ].join("\n");
    const parsed = parseCsv(csv);
    expect(parsed.hasHeader).toBe(true);
    expect(parsed.headers.length).toBe(7);
    const guess = guessColumns(parsed);
    expect(guess.email).toBe(2);
    expect(guess.name).toBe(3);
    const { contacts, invalid } = extractContacts(parsed, guess, "email");
    expect(invalid).toBe(0);
    expect(contacts).toEqual([
      { email: "sara@example.com", phone: undefined, name: "Sara Ahmed" },
      { email: "omar@example.com", phone: undefined, name: "Omar Ali" },
    ]);
  });

  it("handles quoted commas and escaped quotes", () => {
    const parsed = parseCsv('email,name\n"a@x.com","Doe, Jane"\n');
    expect(parsed.rows[0]).toEqual(["a@x.com", "Doe, Jane"]);
  });

  it("falls back to value-shape detection without headers", () => {
    const parsed = parseCsv("Ali,sara@example.com,+966500000001\nMona,omar@example.com,+966500000002\n");
    expect(parsed.hasHeader).toBe(false);
    const guess = guessColumns(parsed);
    expect(guess.email).toBe(1);
    expect(guess.phone).toBe(2);
  });

  it("skips invalid rows and deduplicates", () => {
    const parsed = parseCsv("email,name\nsara@example.com,Sara\nnot-an-email,Bad\nsara@example.com,Sara again\n");
    const { contacts, invalid } = extractContacts(parsed, guessColumns(parsed), "email");
    expect(invalid).toBe(1);
    expect(contacts).toHaveLength(1);
    expect(contacts[0].email).toBe("sara@example.com");
  });

  it("rejects years and short IDs as phone numbers", () => {
    const parsed = parseCsv("phone,name\n2024,Year\n123,Short\n+966500000001,Good\n");
    const { contacts, invalid } = extractContacts(parsed, guessColumns(parsed), "whatsapp");
    expect(invalid).toBe(2);
    expect(contacts).toEqual([{ email: undefined, phone: "+966500000001", name: "Good" }]);
  });
});

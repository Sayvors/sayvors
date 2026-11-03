/**
 * Return a URL only when it is safe to put in an anchor's href.
 *
 * Chat markdown is model output, and model output is influenced by customer
 * messages. A `javascript:` link clicked by an agent would execute in the
 * dashboard origin, so this fails closed. Relative links are allowed because
 * they navigate within the app; only HTTP(S) and mailto are allowed as
 * absolute schemes.
 */
const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

// Browsers strip some ASCII control characters while parsing URLs, which can
// turn an obfuscated string into a live scheme. Reject them before parsing.
const CONTROL_CHARS = /[\u0000-\u001F\u007F]/;

export function safeHref(raw: string): string | null {
  const value = raw.trim();
  if (!value || CONTROL_CHARS.test(value)) return null;

  try {
    // The base is a placeholder: relative values resolve against it, while
    // absolute values keep their own scheme for the allowlist check.
    const url = new URL(value, "https://sayvors.invalid");
    return SAFE_PROTOCOLS.has(url.protocol) ? value : null;
  } catch {
    return null;
  }
}

"""Human-typed short codes shared by review handoff and WhatsApp bridging.

Both surfaces hand a customer a code that gets read off a screen and typed
back, so they must agree on the character set and on the characters left out:
no ``0/O`` or ``1/I``, and no separators to mistype.

This is a public alphabet, not a credential — a live code only resolves inside
the tenant and thread it was minted for. One copy exists so the two surfaces
cannot drift into different alphabets, and so secret scanners do not flag the
same string twice under a key-sounding name.
"""

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

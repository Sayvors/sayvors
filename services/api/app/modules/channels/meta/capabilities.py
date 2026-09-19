"""Provider capability definitions: capability -> required/optional scopes.

Table-driven (not hardcoded per call site) so new capabilities extend the
map instead of branching logic. Scope strings verified against the Meta
Permissions Reference (2026); confirm exact strings in App Dashboard before
App Review — see docs/integrations/meta/{facebook,instagram}.md for known
doc conflicts.
"""

CAPABILITIES: dict[str, dict[str, dict[str, list[str]]]] = {
    "whatsapp": {
        "send_messages": {
            "required": ["whatsapp_business_messaging"],
            "optional": [],
        },
        "receive_messages": {
            "required": ["whatsapp_business_messaging"],
            "optional": [],
        },
        "manage_business_assets": {
            "required": ["whatsapp_business_management"],
            "optional": [],
        },
    },
    "facebook": {
        "read_page": {
            "required": ["pages_show_list", "pages_read_engagement"],
            "optional": ["read_insights"],
        },
        "read_comments": {
            "required": ["pages_read_user_content"],
            "optional": [],
        },
        "manage_comments": {
            "required": ["pages_manage_engagement"],
            "optional": [],
        },
        "manage_page": {
            "required": ["pages_manage_posts", "pages_manage_metadata"],
            "optional": [],
        },
        "messaging": {
            "required": ["pages_messaging"],
            "optional": [],
        },
        "manage_business_assets": {
            "required": ["business_management"],
            "optional": [],
        },
    },
    "instagram": {
        "read_profile": {
            "required": ["instagram_basic"],
            "optional": ["instagram_manage_insights"],
        },
        "read_comments": {
            "required": ["instagram_basic", "instagram_manage_comments"],
            "optional": [],
        },
        "manage_comments": {
            "required": ["instagram_basic", "instagram_manage_comments"],
            "optional": [],
        },
        "messaging": {
            "required": ["instagram_basic", "instagram_manage_messages"],
            "optional": [],
        },
        "publishing": {
            "required": ["instagram_basic", "instagram_content_publish"],
            "optional": [],
        },
    },
}


def required_scopes(provider: str, capabilities: list[str]) -> list[str]:
    """Union of required scopes for the given provider capabilities."""
    out: list[str] = []
    for cap in capabilities:
        for scope in CAPABILITIES.get(provider, {}).get(cap, {}).get("required", []):
            if scope not in out:
                out.append(scope)
    return out


def all_required_scopes(provider: str) -> list[str]:
    return required_scopes(provider, list(CAPABILITIES.get(provider, {})))

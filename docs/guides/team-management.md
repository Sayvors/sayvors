# Team Management

Team management is available to workspace members with the relevant team
permissions. Owners always pass permission checks. The customer app's Team page
uses `/api/v1/team` to manage members, roles, invites, and channel-level access.
For the full route list, see the [API endpoint reference](../api/endpoints.md).

## Invite a teammate

1. Open **Dashboard → Team**.
2. Choose a role for the teammate. Built-in roles are seeded for each workspace;
   a user with `team.manage` can edit built-in role permissions or create a
   custom role.
3. Enter the teammate's email and send the invite. Channel access can follow
   the role or be overridden per channel as **No access**, **View**, or **Edit**.
4. If delivery fails, the pending invite remains in the workspace and can be
   resent. A pending invite can also be revoked.

Invite acceptance depends on whether the invited email already has a Sayvors
account:

- **New account:** open the invite link and complete account creation with a
  password. Acceptance signs the new user in and joins the workspace.
- **Existing account:** first sign in to that account, then accept the invite.
  The invite token by itself cannot attach an existing account to a workspace.

Invite preview is public to anyone holding the invite link; keep the link
private. Expired or already-used links must be replaced by a newly sent invite.

## Roles and permissions

The permission catalog is available from `GET /api/v1/team/permissions` and is
the source for the role builder. `GET /api/v1/team/context` reports the current
member's role, permission set, and channel overrides.

Use roles for workspace-wide capabilities, then use channel overrides to
narrow or grant access to a specific channel:

- **Follow role:** use the role's permission for that channel.
- **No access:** explicitly deny channel access.
- **View:** allow read access.
- **Edit:** allow channel changes and actions where the endpoint checks edit
  access.

Built-in role names are fixed, but their permissions can be edited. Built-in
roles cannot be deleted. Custom roles cannot be deleted while assigned to a
member; reassign members first. A role must keep at least one permission.

## Member changes

Members with `team.manage` can change another member's role, status, and
channel overrides or remove the member. Only pending invitations can be
resent or revoked. Use the permission catalog and the member's current
workspace context when troubleshooting a missing page or action.

## API access

Every team endpoint except `GET /invites/preview` and `POST /invites/accept`
requires an authenticated session. Invite endpoints use the token as the
proof of invitation; existing users still need to authenticate before joining.
See the [API endpoint reference](../api/endpoints.md) for methods and paths.

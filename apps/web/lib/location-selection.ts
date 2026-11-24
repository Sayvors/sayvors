/** Pick the branch shown when the Locations page first opens.
 *
 *  Keep the API's order (groups, bulk scopes and branch labels depend on it),
 *  but prefer the first published/verified listing. A freshly drafted Google
 *  location can appear first in the account response; opening there makes the
 *  whole page look unverified even when live branches exist.
 */
export function preferredLocationId(
  locations: readonly { id: string; is_verified?: boolean | null }[],
): string | null {
  return (
    locations.find((location) => location.is_verified === true)?.id ??
    locations[0]?.id ??
    null
  );
}

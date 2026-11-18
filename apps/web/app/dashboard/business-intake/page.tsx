/* Reads the dashboard's deep-link params on the server and hands plain
 * strings to the client view. Doing it here (rather than with
 * `useSearchParams`) keeps the route out of a client-side-render bailout. */
import BusinessIntakeView from "./BusinessIntakeView";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function BusinessIntakePage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string | string[]; q?: string | string[] }>;
}) {
  const params = await searchParams;
  return (
    <BusinessIntakeView
      initialSection={first(params.focus)}
      initialQuestionKey={first(params.q)}
    />
  );
}

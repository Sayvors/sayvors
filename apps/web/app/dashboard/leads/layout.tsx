import PlanGate from "@/components/billing/PlanGate";

export default function LeadsLayout({ children }: { children: React.ReactNode }) {
  return <PlanGate surface="/dashboard/leads">{children}</PlanGate>;
}

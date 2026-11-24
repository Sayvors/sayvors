import PlanGate from "@/components/billing/PlanGate";

export default function GrowthLayout({ children }: { children: React.ReactNode }) {
  return <PlanGate surface="/dashboard/growth">{children}</PlanGate>;
}

import PlanGate from "@/components/billing/PlanGate";

export default function DatabankLayout({ children }: { children: React.ReactNode }) {
  return <PlanGate surface="/dashboard/databank">{children}</PlanGate>;
}

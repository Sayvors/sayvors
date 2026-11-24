import PlanGate from "@/components/billing/PlanGate";

export default function BenchmarkLayout({ children }: { children: React.ReactNode }) {
  return <PlanGate surface="/dashboard/benchmark">{children}</PlanGate>;
}

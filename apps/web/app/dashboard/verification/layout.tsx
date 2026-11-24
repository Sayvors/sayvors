import PlanGate from "@/components/billing/PlanGate";

export default function VerificationLayout({ children }: { children: React.ReactNode }) {
  return <PlanGate surface="/dashboard/verification">{children}</PlanGate>;
}

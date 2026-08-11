export type WizardData = {
  name: string;
  description: string;
  persona: string;
  coreInstructions: string;
  creativity: number;
  trainingMode: "zero-shot" | "few-shot";
  examples: { message: string; reply: string; tag: string }[];
  databankId: string;
};

export const defaultWizardData: WizardData = {
  name: "",
  description: "",
  persona: "Customer Support",
  coreInstructions: "",
  creativity: 50,
  trainingMode: "zero-shot",
  examples: [],
  databankId: "",
};

export type StepDef = {
  label: string;
  description: string;
  required: boolean;
  recommended?: boolean;
};

export const WIZARD_STEPS: StepDef[] = [
  { label: "Identity", description: "Name and persona", required: true },
  { label: "Instructions", description: "How the agent behaves", required: true, recommended: true },
  { label: "Knowledge", description: "Connect a databank", required: false, recommended: true },
  { label: "Save", description: "Review and save", required: true },
];

export const personaList = [
  { id: "Customer Support", icon: "\uD83C\uDFA7", desc: "Answers questions, troubleshoots issues, escalates when needed" },
  { id: "Sales Assistant", icon: "\uD83D\uDCB0", desc: "Qualifies leads, answers product questions, guides toward purchase" },
  { id: "HR Rep", icon: "\uD83D\uDC65", desc: "Helps with policies, benefits, onboarding, workplace questions" },
  { id: "Tech Support", icon: "\uD83D\uDD27", desc: "Troubleshoots technical issues step by step" },
  { id: "Concierge", icon: "\uD83E\uDD1D", desc: "Welcomes users, guides them through features" },
  { id: "Custom", icon: "\u2728", desc: "Build from scratch with your own instructions" },
];

export const personaInstructions: Record<string, string> = {
  "Customer Support": "You are a helpful customer support agent. Answer questions clearly, troubleshoot issues, and escalate when needed. Be empathetic and concise.",
  "Sales Assistant": "You are a sales assistant. Qualify leads, answer product questions, and guide prospects toward a purchase. Be persuasive but not pushy.",
  "HR Rep": "You are an HR representative. Help employees with policies, benefits, onboarding, and general workplace questions. Be professional and supportive.",
  "Tech Support": "You are a technical support specialist. Troubleshoot issues step by step, ask clarifying questions, and provide clear solutions.",
  "Concierge": "You are a friendly concierge. Welcome users warmly, guide them through features, and help them get started. Be warm and inviting.",
  Custom: "",
};

export const databanks = [
  { id: "db1", name: "Product Knowledge Base", docs: 12 },
  { id: "db2", name: "FAQ Collection", docs: 48 },
  { id: "db3", name: "Company Policies", docs: 7 },
];

export type StepProps = {
  data: WizardData;
  update: <K extends keyof WizardData>(key: K, value: WizardData[K]) => void;
};

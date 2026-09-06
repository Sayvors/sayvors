/**
 * Greeting dictionary for the dashboard header.
 * Shown as "<greeting>, <first name>" with a typewriter animation.
 * Every entry must read naturally in that slot at any time of day
 * (no morning/evening-specific lines — those come from timeGreeting).
 */

export const GREETINGS: readonly string[] = [
  "Hello",
  "Hi",
  "Hey",
  "Hey there",
  "Howdy",
  "Greetings",
  "Good day",
  "Hiya",
  "Salutations",
  "Hello hello",
  "Welcome back",
  "Welcome in",
  "Good to see you",
  "Great to see you",
  "Lovely to see you",
  "Always good to see you",
  "Good to have you here",
  "Glad you're here",
  "Always a pleasure",
  "Hello again",
  "Hi again",
  "Hey again",
  "Hope you're well",
  "Hope you're having a great day",
  "Hope today treats you well",
  "Ready when you are",
  "Let's get to it",
  "Let's make it happen",
  "Let's make today count",
  "Let's do this",
  "Let's roll",
  "Let's grow today",
  "Time to shine",
  "Big wins ahead",
  "Fresh day, fresh wins",
  "Here's to a productive day",
  "Onwards and upwards",
  "Back to business",
  "Down to business",
  "Showtime",
  "Let's check the pulse",
  "Here's your overview",
  "Your business at a glance",
  "Let's see how business is doing",
  "The numbers are in",
  "Ready for today's briefing",
  "Your assistant is ready",
  "Your AI has been busy",
  "Here's your command center",
  "All systems go",
  "Big day ahead",
  "Here's what's happening",
  "Let's dive in",
];

export function timeGreeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

/** Shuffle helper so the typewriter never runs the same order twice. */
export function shuffled<T>(items: readonly T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

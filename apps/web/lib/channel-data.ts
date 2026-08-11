export interface Channel {
  slug: string;
  name: string;
  icon: string;
  color: string;
  connected: boolean;
  agentActive: boolean;
  scopes: string[];
}

export interface Conversation {
  id: string;
  name: string;
  avatar: string;
  lastMsg: string;
  time: string;
  unread: boolean;
  agentMode: boolean;
}

export interface Message {
  id: number;
  role: "user" | "agent";
  content: string;
  time: string;
}

export interface Agent {
  id: string;
  name: string;
  status: "active" | "paused";
}

export const channels: Channel[] = [
  {
    slug: "instagram",
    name: "Instagram",
    icon: "📸",
    color: "from-pink-500 to-purple-500",
    connected: true,
    agentActive: false,
    scopes: ["instagram_basic", "instagram_manage_messages", "pages_show_list"],
  },
  {
    slug: "x",
    name: "X / Twitter",
    icon: "🐦",
    color: "from-sky-400 to-blue-500",
    connected: true,
    agentActive: false,
    scopes: ["tweet.read", "users.read", "dm.read", "dm.write"],
  },
  {
    slug: "facebook",
    name: "Facebook",
    icon: "👤",
    color: "from-blue-500 to-blue-600",
    connected: false,
    agentActive: false,
    scopes: ["pages_manage_metadata", "pages_messaging", "pages_show_list"],
  },
  {
    slug: "telegram",
    name: "Telegram",
    icon: "✈️",
    color: "from-blue-400 to-indigo-500",
    connected: true,
    agentActive: true,
    scopes: ["bot_token"],
  },
  {
    slug: "whatsapp",
    name: "WhatsApp",
    icon: "💬",
    color: "from-green-400 to-emerald-500",
    connected: true,
    agentActive: false,
    scopes: ["whatsapp_business_messaging", "whatsapp_business_management"],
  },
  {
    slug: "linkedin",
    name: "LinkedIn",
    icon: "💼",
    color: "from-blue-600 to-blue-700",
    connected: false,
    agentActive: false,
    scopes: ["r_liteprofile", "r_emailaddress", "w_member_social"],
  },
  {
    slug: "tiktok",
    name: "TikTok",
    icon: "🎵",
    color: "from-black to-gray-900",
    connected: false,
    agentActive: false,
    scopes: ["user.info.basic", "video.list", "video.publish"],
  },
];

export const agents: Agent[] = [
  { id: "support-bot", name: "Support Bot", status: "active" },
  { id: "sales-assistant", name: "Sales Assistant", status: "active" },
  { id: "lead-qualifier", name: "Lead Qualifier", status: "paused" },
  { id: "faq-bot", name: "FAQ Bot", status: "active" },
];

export const conversationsByChannel: Record<string, Conversation[]> = {
  whatsapp: [
    { id: "1", name: "Sarah Chen", avatar: "SC", lastMsg: "Thanks for the quick response!", time: "2m", unread: true, agentMode: true },
    { id: "2", name: "Marcus Rivera", avatar: "MR", lastMsg: "Can you send me the invoice?", time: "8m", unread: false, agentMode: false },
    { id: "3", name: "Elena Kowalski", avatar: "EK", lastMsg: "The campaign looks great!", time: "15m", unread: false, agentMode: true },
    { id: "4", name: "James Okafor", avatar: "JO", lastMsg: "When is the next meeting?", time: "32m", unread: true, agentMode: false },
    { id: "5", name: "Aisha Patel", avatar: "AP", lastMsg: "I'll review the proposal today", time: "1h", unread: false, agentMode: true },
  ],
  instagram: [
    { id: "6", name: "Olivia Thompson", avatar: "OT", lastMsg: "Love the new collection!", time: "5m", unread: true, agentMode: false },
    { id: "7", name: "Noah Williams", avatar: "NW", lastMsg: "Do you ship internationally?", time: "20m", unread: false, agentMode: true },
    { id: "8", name: "Sophia Martinez", avatar: "SM", lastMsg: "Can I get a discount code?", time: "45m", unread: false, agentMode: false },
  ],
  x: [
    { id: "9", name: "Liam Johnson", avatar: "LJ", lastMsg: "Great thread, following!", time: "10m", unread: false, agentMode: true },
    { id: "10", name: "Emma Davis", avatar: "ED", lastMsg: "When is the next drop?", time: "1h", unread: true, agentMode: false },
  ],
  telegram: [
    { id: "11", name: "Alex Kim", avatar: "AK", lastMsg: "Bot is working perfectly", time: "3m", unread: false, agentMode: true },
    { id: "12", name: "Maria Garcia", avatar: "MG", lastMsg: "Can you help me with order #4521?", time: "25m", unread: true, agentMode: true },
    { id: "13", name: "David Brown", avatar: "DB", lastMsg: "Thanks!", time: "2h", unread: false, agentMode: false },
  ],
  facebook: [],
  linkedin: [],
  tiktok: [],
};

export const messagesByConversation: Record<string, Message[]> = {
  "1": [
    { id: 1, role: "user", content: "Hi, I'm interested in your product. Can you tell me more about pricing?", time: "10:32 AM" },
    { id: 2, role: "agent", content: "Hello Sarah! I'd be happy to help. We have three plans: Starter ($29/mo), Pro ($79/mo), and Enterprise (custom). Which fits your needs?", time: "10:33 AM" },
    { id: 3, role: "user", content: "The Pro plan looks good. Does it include API access?", time: "10:35 AM" },
    { id: 4, role: "agent", content: "Yes, the Pro plan includes full API access, up to 10,000 requests/month, priority support, and all AI features.", time: "10:35 AM" },
    { id: 5, role: "user", content: "Great, I'll sign up for the Pro plan.", time: "10:37 AM" },
    { id: 6, role: "agent", content: "Excellent choice! I'll send you the signup link right away. You'll also get a 14-day free trial.", time: "10:37 AM" },
  ],
  "2": [
    { id: 1, role: "user", content: "Hey, I need an invoice for my last purchase.", time: "9:15 AM" },
    { id: 2, role: "agent", content: "Of course, Marcus! I've generated your invoice for order #3842. It's been sent to your email.", time: "9:16 AM" },
    { id: 3, role: "user", content: "Can you send me the invoice directly here?", time: "9:20 AM" },
  ],
  "3": [
    { id: 1, role: "agent", content: "Hi Elena! Just wanted to let you know that your campaign is now live across all channels.", time: "8:00 AM" },
    { id: 2, role: "user", content: "The campaign looks great! Love the creative.", time: "8:15 AM" },
    { id: 3, role: "agent", content: "Thank you! We're seeing strong engagement already. I'll send you the performance report at the end of the day.", time: "8:16 AM" },
  ],
  "4": [
    { id: 1, role: "user", content: "When is the next meeting scheduled?", time: "7:30 AM" },
    { id: 2, role: "agent", content: "Your next meeting is tomorrow at 2:00 PM EST with the marketing team. Would you like me to send you a calendar invite?", time: "7:31 AM" },
  ],
  "5": [
    { id: 1, role: "agent", content: "Hi Aisha! I've sent over the proposal you requested. Let me know if you have any questions.", time: "Yesterday" },
    { id: 2, role: "user", content: "I'll review the proposal today", time: "Yesterday" },
    { id: 3, role: "agent", content: "Take your time! I'm here if you need any clarification on the terms or pricing.", time: "Yesterday" },
  ],
  "6": [
    { id: 1, role: "user", content: "Love the new collection! When will it be available?", time: "11:00 AM" },
    { id: 2, role: "agent", content: "Thank you Olivia! The new collection drops this Friday at 10 AM EST. Would you like me to notify you when it's live?", time: "11:01 AM" },
  ],
  "7": [
    { id: 1, role: "user", content: "Do you ship internationally?", time: "9:30 AM" },
    { id: 2, role: "agent", content: "Yes, we ship to over 50 countries! Shipping rates vary by location. Where are you located?", time: "9:31 AM" },
    { id: 3, role: "user", content: "I'm in the UK.", time: "9:33 AM" },
    { id: 4, role: "agent", content: "Great! UK shipping is $9.99 for standard (5-7 days) and $19.99 for express (2-3 days). Orders over $75 ship free!", time: "9:34 AM" },
  ],
  "8": [
    { id: 1, role: "user", content: "Can I get a discount code?", time: "8:45 AM" },
    { id: 2, role: "agent", content: "Absolutely! Use code WELCOME15 for 15% off your first order. It's valid for the next 7 days.", time: "8:46 AM" },
  ],
  "9": [
    { id: 1, role: "user", content: "Great thread, following!", time: "2:00 PM" },
    { id: 2, role: "agent", content: "Thanks Liam! Stay tuned for more updates this week.", time: "2:01 PM" },
  ],
  "10": [
    { id: 1, role: "user", content: "When is the next drop?", time: "10:00 AM" },
    { id: 2, role: "agent", content: "Next drop is Thursday at noon EST. We're releasing 3 new colorways!", time: "10:01 AM" },
  ],
  "11": [
    { id: 1, role: "user", content: "Bot is working perfectly", time: "3:00 PM" },
    { id: 2, role: "agent", content: "Glad to hear it, Alex! Let me know if you need any adjustments to the bot settings.", time: "3:01 PM" },
  ],
  "12": [
    { id: 1, role: "user", content: "Can you help me with order #4521?", time: "1:30 PM" },
    { id: 2, role: "agent", content: "Of course, Maria! Let me look that up for you. Order #4521 was shipped yesterday and should arrive by Friday.", time: "1:31 PM" },
    { id: 3, role: "user", content: "Can I change the delivery address?", time: "1:33 PM" },
    { id: 4, role: "agent", content: "Unfortunately, since the order is already in transit, we can't change the address. However, you can contact the carrier directly to request a redirect.", time: "1:34 PM" },
  ],
  "13": [
    { id: 1, role: "user", content: "Thanks!", time: "11:00 AM" },
    { id: 2, role: "agent", content: "You're welcome, David! Have a great day.", time: "11:01 AM" },
  ],
};

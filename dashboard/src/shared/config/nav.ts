import { Activity, BarChart3, Bell, Brain, Globe2, Home, LineChart, MailCheck, Newspaper, ScrollText } from "lucide-react";

export const navItems = [
  { href: "/", label: "Overview", icon: Home },
  { href: "/prices", label: "Prices (A)", icon: LineChart },
  { href: "/news", label: "News Intel", icon: Globe2 },
  { href: "/announcements", label: "Announcements (B)", icon: Newspaper },
  { href: "/sentiment", label: "Sentiment (C)", icon: Bell },
  { href: "/analyst", label: "Analyst (D)", icon: Brain },
  { href: "/patterns", label: "Patterns (E)", icon: BarChart3 },
  { href: "/stories", label: "Agent F Monitor", icon: ScrollText },
  { href: "/system", label: "System Ops", icon: Activity },
  { href: "/email-validation", label: "Email Validation", icon: MailCheck },
];

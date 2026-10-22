import { Clock3, FileText, Globe, Plug, TerminalSquare, Users, Wrench } from "lucide-react";
import type { Family } from "@/lib/session-tree";

export const FAMILY_ICON: Record<Family, typeof TerminalSquare> = {
  shell: TerminalSquare,
  files: FileText,
  web: Globe,
  mcp: Plug,
  subagents: Users,
  session: Clock3,
  other: Wrench,
};

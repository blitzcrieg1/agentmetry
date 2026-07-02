"use client";

import { useEffect } from "react";
import { Zap } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SkillDeck() {
  const skills = useAgentStore((s) => s.skills);
  const setSkills = useAgentStore((s) => s.setSkills);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const setActiveSkill = useAgentStore((s) => s.setActiveSkill);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const sessionId = useAgentStore((s) => s.sessionId);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const clearTerminal = useAgentStore((s) => s.clearTerminal);
  const reset = useAgentStore((s) => s.reset);
  const updateNode = useAgentStore((s) => s.updateNode);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);

  useEffect(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/skills/`)
      .then((r) => r.json())
      .then((data) => setSkills(data.skills || []))
      .catch(() => {
        setSkills([
          {
            id: "lead_gen",
            name: "lead_gen",
            display_name: "Lead Gen Outbound",
            description: "Identify prospects and draft outreach emails",
          },
        ]);
      });
  }, [setSkills]);

  const runSkill = async (skillId: string) => {
    setActiveSkill(skillId);
    reset();
    clearTerminal();
    setExecutionStatus("running");
    updateNode("planner", "running");
    appendTerminal(`Launching skill: ${skillId}...`);

    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/skills/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skill_name: skillId,
          user_input: "Generate outreach for AI infrastructure prospects from vault context",
          session_id: sessionId,
        }),
      });
      const data = await res.json();

      if (data.status === "waiting_for_input") {
        setExecutionStatus("waiting_for_input");
      } else if (data.status === "completed") {
        ["planner", "researcher", "writer", "critic", "finalize"].forEach((n) =>
          updateNode(n, "completed")
        );
        setExecutionStatus("completed");
      } else if (data.status === "failed") {
        setExecutionStatus("failed");
      }
    } catch (err) {
      appendTerminal(`Error: ${err}`);
      setExecutionStatus("failed");
    }
  };

  const isRunning = executionStatus === "running";

  return (
    <div className="flex flex-col gap-4 h-full">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          The Armory
        </h2>
        <div className="space-y-2">
          {skills.map((skill) => (
            <Card
              key={skill.id}
              className={`cursor-pointer transition-all hover:border-primary/50 ${
                activeSkill === skill.id ? "border-primary" : ""
              }`}
            >
              <CardHeader className="p-3 pb-1">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Zap className="h-4 w-4 text-primary" />
                  {skill.display_name || skill.name}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <p className="text-xs text-muted-foreground mb-2">{skill.description}</p>
                <Button
                  size="sm"
                  className="w-full"
                  disabled={isRunning}
                  onClick={() => runSkill(skill.id)}
                >
                  {isRunning && activeSkill === skill.id ? "Running..." : "Execute"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <div className="mt-auto">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Memory Navigator
        </h2>
        <div className="text-xs text-muted-foreground space-y-1 font-mono">
          <div className="hover:text-foreground cursor-pointer">📁 10-Knowledge/</div>
          <div className="pl-3 hover:text-foreground cursor-pointer">📄 brand-guidelines.md</div>
          <div className="pl-3 hover:text-foreground cursor-pointer">📄 technical-arch.md</div>
          <div className="hover:text-foreground cursor-pointer">📁 99-Relations/</div>
          <div className="pl-3 hover:text-foreground cursor-pointer">📄 prospects.md</div>
          <div className="hover:text-foreground cursor-pointer">📁 30-Archive/</div>
        </div>
      </div>
    </div>
  );
}

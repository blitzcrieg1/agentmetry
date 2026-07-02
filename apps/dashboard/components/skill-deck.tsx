"use client";

import { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { buildGraphNodes, SKILL_DEFAULTS } from "@/lib/graph-utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MemoryNavigator } from "@/components/memory-navigator";

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
  const appendTerminal = useAgentStore((s) => s.appendTerminal);

  const [userInput, setUserInput] = useState(SKILL_DEFAULTS.lead_gen.input);

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
            description: "Identify prospects and draft personalized outreach emails",
            nodes: SKILL_DEFAULTS.lead_gen.nodes,
          },
          {
            id: "summarize_meeting",
            name: "summarize_meeting",
            display_name: "Meeting Summarizer",
            description: "Summarize meeting notes and extract action items",
            nodes: SKILL_DEFAULTS.summarize_meeting.nodes,
          },
        ]);
      });
  }, [setSkills]);

  const runSkill = async (skillId: string) => {
    const defaults = SKILL_DEFAULTS[skillId] ?? SKILL_DEFAULTS.lead_gen;
    const input = userInput.trim() || defaults.input;
    const nodes = buildGraphNodes(defaults.nodes);

    setActiveSkill(skillId);
    reset(nodes);
    clearTerminal();
    setExecutionStatus("running");
    appendTerminal(`Launching skill: ${skillId}...`);
    appendTerminal(`Task: ${input}`);

    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/skills/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skill_name: skillId,
          user_input: input,
          session_id: sessionId,
        }),
      });
      const data = await res.json();

      if (data.status === "waiting_for_input") {
        setExecutionStatus("waiting_for_input");
      } else if (data.status === "completed" || data.status === "approved") {
        setExecutionStatus("completed");
      } else if (data.status === "failed") {
        setExecutionStatus("failed");
        appendTerminal(`✗ ${data.error || "Execution failed"}`);
      }
    } catch (err) {
      appendTerminal(`Error: ${err}`);
      setExecutionStatus("failed");
    }
  };

  const selectSkill = (skillId: string) => {
    setActiveSkill(skillId);
    const defaults = SKILL_DEFAULTS[skillId];
    if (defaults) setUserInput(defaults.input);
  };

  const isRunning = executionStatus === "running";

  return (
    <div className="flex flex-col gap-4 h-full">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          The Armory
        </h2>

        <div className="mb-3">
          <label className="text-xs text-muted-foreground mb-1 block">Task input</label>
          <textarea
            className="w-full h-20 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-primary"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Describe what the agent should do..."
            disabled={isRunning}
          />
        </div>

        <div className="space-y-2">
          {skills.map((skill) => (
            <Card
              key={skill.id}
              className={`transition-all hover:border-primary/50 ${
                activeSkill === skill.id ? "border-primary" : ""
              }`}
              onClick={() => selectSkill(skill.id)}
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
                  onClick={(e) => {
                    e.stopPropagation();
                    runSkill(skill.id);
                  }}
                >
                  {isRunning && activeSkill === skill.id ? "Running..." : "Execute"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <div className="mt-auto">
        <MemoryNavigator />
      </div>
    </div>
  );
}

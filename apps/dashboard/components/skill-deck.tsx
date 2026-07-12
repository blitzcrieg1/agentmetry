"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Zap } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiPost } from "@/lib/api";
import { buildGraphNodes, defaultInputForSkill, displayNodesForSkill } from "@/lib/graph-utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MemoryNavigator } from "@/components/memory-navigator";

interface SkillDefinition {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  nodes?: string[];
  default_input?: string;
}

const HERO_SKILL = "audit_demo";

function SkillCard({
  skill,
  activeSkill,
  isRunning,
  onSelect,
  onRun,
}: {
  skill: SkillDefinition;
  activeSkill: string | null;
  isRunning: boolean;
  onSelect: () => void;
  onRun: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-all duration-300 hover:border-violet-500/40 ${
        activeSkill === skill.id
          ? "border-violet-500/60 bg-violet-950/20"
          : "border-border/60 bg-card/50"
      }`}
      onClick={onSelect}
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
            onRun();
          }}
        >
          {isRunning && activeSkill === skill.id ? "Running..." : "Run"}
        </Button>
      </CardContent>
    </Card>
  );
}

export function SkillDeck() {
  const skills = useAgentStore((s) => s.skills);
  const setSkills = useAgentStore((s) => s.setSkills);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const setActiveSkill = useAgentStore((s) => s.setActiveSkill);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const sessionId = useAgentStore((s) => s.sessionId);
  const devMode = useAgentStore((s) => s.devMode);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const clearTerminal = useAgentStore((s) => s.clearTerminal);
  const reset = useAgentStore((s) => s.reset);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);
  const setLastUserInput = useAgentStore((s) => s.setLastUserInput);

  const [userInput, setUserInput] = useState("");
  const [examplesOpen, setExamplesOpen] = useState(false);

  useEffect(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/skills/`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        const loaded: SkillDefinition[] = (data.skills || []).map((s: SkillDefinition) => ({
          ...s,
          id: s.id || s.name,
        }));
        setSkills(loaded);
        const preferred = loaded.find((s) => s.id === HERO_SKILL);
        if (preferred) {
          setActiveSkill(preferred.id);
          const defaultInput = defaultInputForSkill(preferred);
          setUserInput(defaultInput);
          setLastUserInput(defaultInput);
        } else if (loaded[0]) {
          setActiveSkill(loaded[0].id);
        }
      })
      .catch(() => appendTerminal("⚠ Could not load skills from orchestrator"));
  }, [setSkills, setActiveSkill, appendTerminal, setLastUserInput]);

  const runSkill = async (skillId: string) => {
    const skill = skills.find((s) => s.id === skillId);
    const input = userInput.trim() || defaultInputForSkill(skill || { id: skillId });
    const nodes = buildGraphNodes(displayNodesForSkill(skill || { id: skillId }));

    setActiveSkill(skillId);
    reset(nodes);
    clearTerminal();
    setExecutionStatus("running");
    setLastUserInput(input);
    appendTerminal(`Launching skill: ${skillId}...`);
    appendTerminal(`Task: ${input}`);

    try {
      const data = await apiPost("/api/v1/skills/execute", {
        skill_name: skillId,
        user_input: input,
        session_id: sessionId,
      });

      if (data.status === "waiting_for_input") {
        setExecutionStatus("waiting_for_input");
      } else if (data.status === "completed" || data.status === "approved") {
        setExecutionStatus("completed");
        window.setTimeout(() => useAgentStore.getState().clearPipelineView(), 4500);
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
    const skill = skills.find((s) => s.id === skillId);
    if (skill) {
      const input = defaultInputForSkill(skill);
      setUserInput(input);
      setLastUserInput(input);
    }
  };

  const isRunning = executionStatus === "running";
  const hero = skills.find((s) => s.id === HERO_SKILL);
  const legacy = skills.filter((s) => s.id !== HERO_SKILL);

  return (
    <div className="flex flex-col gap-4 h-full">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Run
        </h2>

        <div className="mb-3">
          <label className="text-xs text-muted-foreground mb-1 block">Input path</label>
          <textarea
            className="w-full h-20 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-primary"
            value={userInput}
            onChange={(e) => {
              setUserInput(e.target.value);
              setLastUserInput(e.target.value);
            }}
            placeholder="00-Inbox/audit-demo-note.md"
            disabled={isRunning}
          />
        </div>

        {hero ? (
          <SkillCard
            skill={hero}
            activeSkill={activeSkill}
            isRunning={isRunning}
            onSelect={() => selectSkill(hero.id)}
            onRun={() => runSkill(hero.id)}
          />
        ) : null}

        {devMode && legacy.length > 0 ? (
          <div className="mt-4">
            <button
              type="button"
              className="mb-2 flex w-full items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground"
              onClick={() => setExamplesOpen(!examplesOpen)}
            >
              {examplesOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Example skills (legacy) · {legacy.length}
            </button>
            {examplesOpen ? (
              <div className="space-y-2">
                {legacy.map((skill) => (
                  <SkillCard
                    key={skill.id}
                    skill={skill}
                    activeSkill={activeSkill}
                    isRunning={isRunning}
                    onSelect={() => selectSkill(skill.id)}
                    onRun={() => runSkill(skill.id)}
                  />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {devMode ? (
        <div className="mt-auto">
          <MemoryNavigator />
        </div>
      ) : null}
    </div>
  );
}

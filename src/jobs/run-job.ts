/**
 * Job entry point — orchestrates the TypeScript video production pipeline.
 *
 * Env is pre-populated before this module loads (dotenv configured at process
 * start by the bootstrap layer).
 *
 * Usage:
 *   node --experimental-transform-types src/jobs/run-job.ts <topic> [projectId] [mode]
 */

import {
  initJobPricing,
  guardModel,
  getGuardReport,
  recordUsage,
  _resetState,
  type GuardReport,
} from "../lib/model-guard.ts";

// ── Types ─────────────────────────────────────────────────────────────────

export type PipelineMode =
  | "full"          // New project: all LLM stages (script → scenes → voice → QA)
  | "resume"        // Resume Phase 2: skip script writing, start from visual prompts
  | "replan"        // Keep existing script, redo scene planning + visuals
  | "shorts-prep"   // Shorts Phase 1: script analysis → scene planning only
  | "shorts-render" // Shorts Phase 2: voice (SSML) + QA only
  | "images"        // Images only: visual prompts → refinement → anchors
  | "voice";        // Voice only: SSML → faithfulness validation

export interface JobConfig {
  projectId: string;
  topic: string;
  language?: string;
  pipelineMode?: PipelineMode;
  /** Existing script text — required for "resume" and "replan" modes. */
  scriptContent?: string;
  /** Existing scene plan text — required for "resume" mode. */
  scenesContent?: string;
}

interface LLMResult {
  content: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
}

// ── LLM call ─────────────────────────────────────────────────────────────

async function callLLM(modelId: string, prompt: string): Promise<LLMResult> {
  const apiKey = process.env["OPENROUTER_API_KEY"];
  if (!apiKey) throw new Error("[run-job] OPENROUTER_API_KEY not set");

  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: modelId,
      messages: [{ role: "user", content: prompt }],
    }),
  });

  if (!response.ok) {
    throw new Error(`[run-job] LLM call failed: ${response.status} ${response.statusText}`);
  }

  const data = (await response.json()) as {
    choices: Array<{ message: { content: string } }>;
    model: string;
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };

  return {
    content: data.choices[0]!.message.content,
    model: data.model,
    inputTokens: data.usage?.prompt_tokens ?? 0,
    outputTokens: data.usage?.completion_tokens ?? 0,
  };
}

// ── Stage primitive ───────────────────────────────────────────────────────

async function runStage(role: string, prompt: string): Promise<LLMResult> {
  const { selectedModel } = await guardModel(role);
  const result = await callLLM(selectedModel, prompt);
  recordUsage(role, result.inputTokens, result.outputTokens);
  return result;
}

// ── Phase A — Script (analysis → writing → judge → recompose) ────────────

interface ScriptPhaseResult {
  recomposed: LLMResult;
  scenePlan: LLMResult;
}

async function phaseScript(topic: string): Promise<ScriptPhaseResult> {
  console.log("[run-job] Phase A: script");

  const analysis = await runStage(
    "script-analysis",
    `Analyze this video topic and identify key themes: ${topic}`,
  );
  const draft = await runStage(
    "script-writing",
    `Write a video script based on this analysis:\n${analysis.content}`,
  );
  const refined = await runStage(
    "script-refinement",
    `Refine this video script for clarity and flow:\n${draft.content}`,
  );
  const judged = await runStage(
    "script-judge",
    `Compare these two script versions and select the better one:\n\nDraft:\n${draft.content}\n\nRefined:\n${refined.content}`,
  );
  const recomposed = await runStage(
    "guided-recomposer",
    `Recompose this script with improved pacing:\n${judged.content}`,
  );
  const scenePlan = await runStage(
    "scene-planning",
    `Plan scenes for this script:\n${recomposed.content}`,
  );

  return { recomposed, scenePlan };
}

// ── Phase B — Scene planning only (for replan mode) ──────────────────────

async function phaseReplan(scriptContent: string): Promise<LLMResult> {
  console.log("[run-job] Phase B: scene replanning");
  return runStage("scene-planning", `Plan scenes for this script:\n${scriptContent}`);
}

// ── Phase C — Visuals (prompts → refinement → anchors) ───────────────────

async function phaseVisuals(scenePlan: string): Promise<void> {
  console.log("[run-job] Phase C: visuals");
  const prompts = await runStage(
    "visual-prompts",
    `Generate image prompts for these scenes:\n${scenePlan}`,
  );
  await runStage(
    "visual-refinement",
    `Refine these image generation prompts:\n${prompts.content}`,
  );
  await runStage(
    "visual-anchors",
    `Extract visual anchor points from these scenes:\n${scenePlan}`,
  );
}

// ── Phase D — Voice (SSML → faithfulness validation) ─────────────────────

async function phaseVoice(scriptContent: string): Promise<void> {
  console.log("[run-job] Phase D: voice");
  const ssml = await runStage(
    "ssml",
    `Add SSML markup to this narration:\n${scriptContent}`,
  );
  await runStage(
    "faithfulness-val",
    `Validate faithfulness of generated content to original:\n\nOriginal:\n${scriptContent}\n\nGenerated:\n${ssml.content}`,
  );
}

// ── Phase E — QA ──────────────────────────────────────────────────────────

async function phaseQA(scriptContent: string): Promise<void> {
  console.log("[run-job] Phase E: QA");
  await runStage("qa", `Review this script for quality issues:\n${scriptContent}`);
}

// ── Cost summary ──────────────────────────────────────────────────────────

function printCostSummary(jobId: string, mode: PipelineMode, reports: GuardReport[]): void {
  const DLINE = "══════════════════════════════════════════════════════════════════";
  const LINE  = "──────────────────────────────────────────────────────────────────";
  const R_W = 22, M_W = 32, N_W = 8;

  const fmtN = (n: number) => n.toLocaleString("en-US").padStart(N_W);
  const fmtC = (c: number) => `$${c.toFixed(4)}`;

  let totalIn = 0, totalOut = 0, totalCost = 0;

  console.log(`[run-job] ${DLINE}`);
  console.log(`[run-job] JOB COST SUMMARY  ${jobId}  (mode: ${mode})`);
  console.log(`[run-job] ${LINE}`);
  console.log(
    `[run-job]  ${"Role".padEnd(R_W)} ${"Model".padEnd(M_W)} ${"In tok".padStart(N_W)} ${"Out tok".padStart(N_W)}   Cost`,
  );
  console.log(`[run-job] ${LINE}`);

  for (const r of reports) {
    const inTok  = r.inputTokensUsed  ?? 0;
    const outTok = r.outputTokensUsed ?? 0;
    const cost   = r.costUsd          ?? 0;
    totalIn += inTok; totalOut += outTok; totalCost += cost;

    const modelLabel = r.isFallback ? `${r.selectedModel} (fb)` : r.selectedModel;
    console.log(
      `[run-job]  ${r.role.padEnd(R_W)} ${modelLabel.padEnd(M_W)}${fmtN(inTok)}${fmtN(outTok)}   ${fmtC(cost)}`,
    );
  }

  console.log(`[run-job] ${LINE}`);
  console.log(
    `[run-job]  ${"TOTAL".padEnd(R_W)} ${"".padEnd(M_W)}${fmtN(totalIn)}${fmtN(totalOut)}   ${fmtC(totalCost)}`,
  );
  console.log(`[run-job] ${DLINE}`);
}

// ── Main job function ─────────────────────────────────────────────────────

export async function runJob(config: JobConfig): Promise<void> {
  const { projectId, topic, pipelineMode = "full" } = config;

  // Always the first call — fetches fresh OpenRouter rates, validates all roles.
  // Throws immediately if any role has no passing model.
  await initJobPricing();

  console.log(`[run-job] Starting job ${projectId} | topic: "${topic}" | mode: ${pipelineMode}`);

  switch (pipelineMode) {
    case "full": {
      // All stages: script analysis → writing → judge → recompose →
      //             scene plan → visuals → voice → QA
      const { recomposed, scenePlan } = await phaseScript(topic);
      await phaseVisuals(scenePlan.content);
      await phaseVoice(recomposed.content);
      await phaseQA(recomposed.content);
      break;
    }

    case "resume": {
      // Script + scenes already exist — run visuals, voice, QA only.
      const script = config.scriptContent ?? "";
      const scenes = config.scenesContent ?? "";
      if (!script) throw new Error("[run-job] resume mode requires scriptContent");
      if (!scenes) throw new Error("[run-job] resume mode requires scenesContent");
      await phaseVisuals(scenes);
      await phaseVoice(script);
      await phaseQA(script);
      break;
    }

    case "replan": {
      // Existing script — redo scene planning + visuals + voice + QA.
      const script = config.scriptContent ?? "";
      if (!script) throw new Error("[run-job] replan mode requires scriptContent");
      const scenePlan = await phaseReplan(script);
      await phaseVisuals(scenePlan.content);
      await phaseVoice(script);
      await phaseQA(script);
      break;
    }

    case "shorts-prep": {
      // Shorts Phase 1: condensed script analysis → scene planning only.
      const analysis = await runStage(
        "script-analysis",
        `Extract key highlights for a short-form video on: ${topic}`,
      );
      await runStage(
        "scene-planning",
        `Plan a short-form scene sequence (30–60 s) based on:\n${analysis.content}`,
      );
      break;
    }

    case "shorts-render": {
      // Shorts Phase 2: voice + QA on existing short-form script.
      const script = config.scriptContent ?? "";
      if (!script) throw new Error("[run-job] shorts-render mode requires scriptContent");
      await phaseVoice(script);
      await phaseQA(script);
      break;
    }

    case "images": {
      // Visual prompts + refinement + anchors for an existing scene plan.
      const scenes = config.scenesContent ?? "";
      if (!scenes) throw new Error("[run-job] images mode requires scenesContent");
      await phaseVisuals(scenes);
      break;
    }

    case "voice": {
      // SSML markup + faithfulness validation for an existing script.
      const script = config.scriptContent ?? "";
      if (!script) throw new Error("[run-job] voice mode requires scriptContent");
      await phaseVoice(script);
      break;
    }
  }

  // Print per-role cost table then wipe cache — no stale prices bleed into next job.
  printCostSummary(projectId, pipelineMode, getGuardReport());
  _resetState();
}

// ── CLI entry ─────────────────────────────────────────────────────────────

if (process.argv[1] && process.argv[1].endsWith("run-job.ts")) {
  const topic      = process.argv[2] ?? "Untitled Video";
  const projectId  = process.argv[3] ?? `job-${Date.now()}`;
  const modeArg    = process.argv[4] as PipelineMode | undefined;
  runJob({ projectId, topic, pipelineMode: modeArg }).catch((err: Error) => {
    console.error(`[run-job] FATAL: ${err.message}`);
    process.exit(1);
  });
}

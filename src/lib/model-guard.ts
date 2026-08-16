/**
 * Model cost guard — fetches live OpenRouter pricing at job start,
 * validates every assigned model against cost/discount rules,
 * and either returns the approved model ID or throws before any API call.
 */

// ── Public types ──────────────────────────────────────────────────────────

export interface ModelPricing {
  id: string;
  inputPricePerM: number;
  outputPricePerM: number;
  discountRate: number;
  passesGuard: boolean;
  failReasons: string[];
}

export interface GuardThresholds {
  minDiscount: number;
  maxInputPrice: number;
  maxOutputPrice: number;
}

export interface GuardReport {
  role: string;
  selectedModel: string;
  isFallback: boolean;
  fallbackIndex?: number;
  primaryFailReasons?: string[];
  pricing: ModelPricing;
  inputTokensUsed?: number;
  outputTokensUsed?: number;
  costUsd?: number;
}

// ── Module-level state — reset on every initJobPricing() call ─────────────

let _pricingCache: Map<string, ModelPricing> | null = null;
let _thresholds: GuardThresholds | null = null;
let _roleModels: Map<string, string> | null = null;
let _roleFallbacks: Map<string, string[]> | null = null;
let _guardReports: GuardReport[] = [];

// ── Internal helpers ──────────────────────────────────────────────────────

function fmt(price: number): string {
  return "$" + price.toFixed(3);
}

function pct(rate: number): string {
  return Math.round(rate * 100) + "%";
}

function pad(str: string, n: number): string {
  return str.padEnd(n);
}

function loadThresholds(): GuardThresholds {
  return {
    minDiscount: parseFloat(process.env["GUARD_MIN_DISCOUNT"] ?? "0.15"),
    maxInputPrice: parseFloat(process.env["GUARD_MAX_INPUT_PRICE"] ?? "0.50"),
    maxOutputPrice: parseFloat(process.env["GUARD_MAX_OUTPUT_PRICE"] ?? "0.65"),
  };
}

function loadRoleModels(): Map<string, string> {
  const map = new Map<string, string>();
  for (const [key, value] of Object.entries(process.env)) {
    if (key.startsWith("ROLE_MODEL__") && value) {
      const role = key.slice("ROLE_MODEL__".length);
      map.set(role, value.trim());
    }
  }
  if (map.size === 0) {
    throw new Error("[model-guard] NO_ROLES — No ROLE_MODEL__ entries found in environment");
  }
  return map;
}

function loadRoleFallbacks(): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const [key, value] of Object.entries(process.env)) {
    if (key.startsWith("ROLE_FALLBACK__") && value) {
      const role = key.slice("ROLE_FALLBACK__".length);
      map.set(
        role,
        value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      );
    }
  }
  return map;
}

interface RawPricing {
  prompt: string;
  completion: string;
  original_prompt?: string;
  original_completion?: string;
}

function computePricing(id: string, raw: RawPricing, thresholds: GuardThresholds): ModelPricing {
  const promptVal = parseFloat(raw.prompt);
  const completionVal = parseFloat(raw.completion);
  const origPromptVal = raw.original_prompt ? parseFloat(raw.original_prompt) : 0;
  const origCompletionVal = raw.original_completion ? parseFloat(raw.original_completion) : 0;

  let discountRate = 0;
  if (origPromptVal > 0) {
    discountRate = 1 - promptVal / origPromptVal;
  } else if (origCompletionVal > 0) {
    discountRate = 1 - completionVal / origCompletionVal;
  }

  const inputPricePerM = promptVal * 1_000_000;
  const outputPricePerM = completionVal * 1_000_000;

  const failReasons: string[] = [];
  if (discountRate < thresholds.minDiscount) {
    failReasons.push(
      `discount ${pct(discountRate)} < ${pct(thresholds.minDiscount)}`,
    );
  }
  if (inputPricePerM > thresholds.maxInputPrice) {
    failReasons.push(
      `input ${fmt(inputPricePerM)} > ${fmt(thresholds.maxInputPrice)}`,
    );
  }
  if (outputPricePerM > thresholds.maxOutputPrice) {
    failReasons.push(
      `output ${fmt(outputPricePerM)} > ${fmt(thresholds.maxOutputPrice)}`,
    );
  }

  return {
    id,
    inputPricePerM,
    outputPricePerM,
    discountRate,
    passesGuard: failReasons.length === 0,
    failReasons,
  };
}

// ── Exported functions ────────────────────────────────────────────────────

/**
 * Record actual token usage for the most recent guardModel() call for a role.
 * Call this immediately after every LLM response so the cost table is accurate.
 */
export function recordUsage(role: string, inputTokens: number, outputTokens: number): void {
  for (let i = _guardReports.length - 1; i >= 0; i--) {
    const report = _guardReports[i]!;
    if (report.role === role) {
      report.inputTokensUsed = inputTokens;
      report.outputTokensUsed = outputTokens;
      const p = report.pricing;
      report.costUsd =
        (inputTokens / 1_000_000) * p.inputPricePerM +
        (outputTokens / 1_000_000) * p.outputPricePerM;
      return;
    }
  }
}

/**
 * Reset all internal state. For testing only — not part of the public API.
 */
export function _resetState(): void {
  _pricingCache = null;
  _thresholds = null;
  _roleModels = null;
  _roleFallbacks = null;
  _guardReports = [];
}

/**
 * Fetch live pricing from OpenRouter and validate all assigned role models.
 * Must be called once at the start of every job, before any guardModel() call.
 * Throws immediately on missing API key, network errors, or any role with no
 * passing model.
 */
export async function initJobPricing(): Promise<void> {
  // Always reset — never reuse state from a prior call
  _pricingCache = null;
  _thresholds = null;
  _roleModels = null;
  _roleFallbacks = null;
  _guardReports = [];

  const apiKey = process.env["OPENROUTER_API_KEY"];
  if (!apiKey) {
    throw new Error(
      "[model-guard] MISSING_API_KEY — OPENROUTER_API_KEY is not set",
    );
  }

  // Load role assignments before the network call — fail fast on bad config
  const roleModels = loadRoleModels();
  const roleFallbacks = loadRoleFallbacks();
  const thresholds = loadThresholds();

  const response = await fetch("https://openrouter.ai/api/v1/models", {
    headers: { Authorization: `Bearer ${apiKey}` },
  });

  if (!response.ok) {
    throw new Error(
      `[model-guard] API_ERROR — OpenRouter returned ${response.status}: ${response.statusText}`,
    );
  }

  const body = (await response.json()) as { data?: unknown };
  if (!body.data || !Array.isArray(body.data)) {
    throw new Error(
      "[model-guard] API_ERROR — response body does not contain a data array",
    );
  }

  const rawModels = body.data as Array<{ id: string; pricing: RawPricing }>;

  // Build pricing cache — only for models in the API response
  const cache = new Map<string, ModelPricing>();
  for (const model of rawModels) {
    if (!model.id || !model.pricing) continue;
    cache.set(model.id, computePricing(model.id, model.pricing, thresholds));
  }

  _pricingCache = cache;
  _thresholds = thresholds;
  _roleModels = roleModels;
  _roleFallbacks = roleFallbacks;

  // ── Print init report ──────────────────────────────────────────────────
  const DLINE = "══════════════════════════════════════════";
  const LINE = "──────────────────────────────────────────";
  const ROLE_W = 18;
  const MODEL_W = 40;

  console.log(`[model-guard] ${DLINE}`);
  console.log(
    `[model-guard] JOB INIT — live pricing loaded (${rawModels.length} models)`,
  );
  console.log(
    `[model-guard] Thresholds: discount ≥ ${pct(thresholds.minDiscount)}` +
      `  input ≤ ${fmt(thresholds.maxInputPrice)}` +
      `  output ≤ ${fmt(thresholds.maxOutputPrice)}`,
  );
  console.log(`[model-guard] ${LINE}`);

  const failingRoles: string[] = [];

  for (const [role, primaryModel] of roleModels.entries()) {
    const fallbacks = roleFallbacks.get(role) ?? [];
    const candidates = [primaryModel, ...fallbacks];

    let chosen: ModelPricing | null = null;
    let chosenId = "";
    let chosenIsFallback = false;
    const tried: Array<{ id: string; reasons: string[] }> = [];

    for (let i = 0; i < candidates.length; i++) {
      const modelId = candidates[i]!;
      const pricing = cache.get(modelId);
      if (!pricing) {
        tried.push({ id: modelId, reasons: ["not found in OpenRouter response"] });
        continue;
      }
      if (pricing.passesGuard) {
        chosen = pricing;
        chosenId = modelId;
        chosenIsFallback = i > 0;
        break;
      } else {
        tried.push({ id: modelId, reasons: pricing.failReasons });
      }
    }

    if (chosen) {
      const badge = chosenIsFallback ? "~" : "✓";
      console.log(
        `[model-guard] ${badge} ${pad(role, ROLE_W)} ${pad(chosenId, MODEL_W)}` +
          ` ${fmt(chosen.inputPricePerM)}/${fmt(chosen.outputPricePerM)}  ${pct(chosen.discountRate)} off`,
      );
    } else {
      failingRoles.push(role);
      console.log(`[model-guard] ✗ ${role} — all models failed:`);
      for (const t of tried) {
        console.log(`[model-guard]   ${t.id}: ${t.reasons.join(", ")}`);
      }
    }
  }

  console.log(`[model-guard] ${LINE}`);

  if (failingRoles.length > 0) {
    const msg =
      `[model-guard] FATAL — ${failingRoles.length} role(s) have no passing model. Job cannot start.`;
    console.log(msg);
    console.log(`[model-guard] ${DLINE}`);
    throw new Error(msg);
  }

  console.log(`[model-guard] All ${roleModels.size} roles ready. Job may proceed.`);
  console.log(`[model-guard] ${DLINE}`);
}

/**
 * Validate the model for a given role immediately before an LLM API call.
 * Tries the primary model first, then fallbacks in order.
 * Returns a GuardReport describing the chosen model and its pricing.
 * Throws if initJobPricing() was not called first, the role is unknown,
 * or all candidates fail the guard rules.
 */
export async function guardModel(role: string): Promise<GuardReport> {
  if (!_pricingCache || !_thresholds || !_roleModels || !_roleFallbacks) {
    throw new Error(
      "[model-guard] NOT_INITIALIZED — call initJobPricing() before guardModel()",
    );
  }

  const primaryModel = _roleModels.get(role);
  if (!primaryModel) {
    throw new Error(
      `[model-guard] UNKNOWN_ROLE — role '${role}' not found in ROLE_MODEL__ env vars`,
    );
  }

  const fallbacks = _roleFallbacks.get(role) ?? [];
  const candidates = [primaryModel, ...fallbacks];
  const tried: Array<{ id: string; reasons: string[] }> = [];

  for (let i = 0; i < candidates.length; i++) {
    const modelId = candidates[i]!;
    const pricing = _pricingCache.get(modelId);
    if (!pricing) {
      tried.push({ id: modelId, reasons: ["not found in pricing cache"] });
      continue;
    }
    if (pricing.passesGuard) {
      const isFallback = i > 0;
      const report: GuardReport = {
        role,
        selectedModel: modelId,
        isFallback,
        ...(isFallback && {
          fallbackIndex: i,
          primaryFailReasons: tried[0]?.reasons ?? [],
        }),
        pricing,
      };
      _guardReports.push(report);

      const context = isFallback
        ? `fallback #${i} — primary: ${tried[0]?.reasons.join(", ")}`
        : "primary";
      console.log(
        `[model-guard] ✓ ${pad(role, 16)} → ${modelId}  ` +
          `${fmt(pricing.inputPricePerM)}/${fmt(pricing.outputPricePerM)}  ` +
          `${pct(pricing.discountRate)} off  (${context})`,
      );

      return report;
    } else {
      tried.push({ id: modelId, reasons: pricing.failReasons });
    }
  }

  console.log(
    `[model-guard] ✗ BLOCKED ${role} — all ${candidates.length} models failed guard:`,
  );
  for (const t of tried) {
    console.log(`[model-guard]   ${t.id}: ${t.reasons.join(", ")}`);
  }

  throw new Error(
    `[model-guard] BLOCKED — role '${role}': all models failed guard rules`,
  );
}

/**
 * Returns cached pricing for any model ID.
 * Returns undefined if initJobPricing() has not been called or the model
 * was not in the OpenRouter response.
 */
export function getModelPricing(modelId: string): ModelPricing | undefined {
  return _pricingCache?.get(modelId);
}

/**
 * Returns all GuardReports produced during the current job (one per guardModel call).
 * Returns an empty array if no guards have run yet.
 * Resets between initJobPricing() calls.
 */
export function getGuardReport(): GuardReport[] {
  return [..._guardReports];
}

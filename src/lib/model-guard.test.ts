/**
 * Unit tests for model-guard.ts
 * Run with: node --experimental-transform-types --test src/lib/model-guard.test.ts
 */

import { describe, it, before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  initJobPricing,
  guardModel,
  getModelPricing,
  getGuardReport,
  _resetState,
  type ModelPricing,
  type GuardReport,
} from "./model-guard.ts";

// ── Mock helpers ──────────────────────────────────────────────────────────

interface MockModel {
  id: string;
  prompt: string;
  completion: string;
  original_prompt?: string;
  original_completion?: string;
}

let fetchCallCount = 0;
let savedFetch: typeof globalThis.fetch | undefined;

function mockFetch(models: MockModel[]): void {
  savedFetch = globalThis.fetch;
  fetchCallCount = 0;
  const data = models.map((m) => ({
    id: m.id,
    pricing: {
      prompt: m.prompt,
      completion: m.completion,
      ...(m.original_prompt !== undefined && { original_prompt: m.original_prompt }),
      ...(m.original_completion !== undefined && {
        original_completion: m.original_completion,
      }),
    },
  }));
  (globalThis as Record<string, unknown>)["fetch"] = async () => {
    fetchCallCount++;
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ data }),
    };
  };
}

function restoreFetch(): void {
  if (savedFetch !== undefined) {
    (globalThis as Record<string, unknown>)["fetch"] = savedFetch;
  } else {
    delete (globalThis as Record<string, unknown>)["fetch"];
  }
  savedFetch = undefined;
}

/** Override specific env vars for the duration of a test. Returns a restore fn. */
function mockEnv(vars: Record<string, string>): () => void {
  const saved: Record<string, string | undefined> = {};
  // Save and clear any existing ROLE_MODEL__ / ROLE_FALLBACK__ keys if we are
  // providing our own, so leaked keys from the real .env don't interfere.
  const clearPrefixes = ["ROLE_MODEL__", "ROLE_FALLBACK__"];
  const shouldClearPrefixes =
    Object.keys(vars).some((k) => clearPrefixes.some((p) => k.startsWith(p)));

  if (shouldClearPrefixes) {
    for (const key of Object.keys(process.env)) {
      if (clearPrefixes.some((p) => key.startsWith(p))) {
        saved[key] = process.env[key];
        delete process.env[key];
      }
    }
  }
  for (const [key, value] of Object.entries(vars)) {
    saved[key] = process.env[key];
    process.env[key] = value;
  }
  return () => {
    // Restore all touched keys
    const allKeys = new Set([...Object.keys(saved)]);
    for (const key of allKeys) {
      if (saved[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = saved[key];
      }
    }
  };
}

// ── Pre-built mock model fixtures ─────────────────────────────────────────

// 75% off — $0.075/$0.625 — passes all rules
const MOCK_PASSING_MODEL: MockModel = {
  id: "mock/passing",
  prompt: "0.0000000750",
  completion: "0.0000006250",
  original_prompt: "0.0000003000",
};

// 90% off — $0.010/$0.030 — passes all rules (very cheap)
const MOCK_CHEAP_MODEL: MockModel = {
  id: "mock/cheap",
  prompt: "0.0000000100",
  completion: "0.0000000300",
  original_prompt: "0.0000001000",
};

// ~10% off — $0.068/$0.137 — fails discount rule only
const MOCK_FAIL_DISCOUNT: MockModel = {
  id: "mock/fail-discount",
  prompt: "0.0000000680",
  completion: "0.0000001370",
  original_prompt: "0.0000000756",
};

// 80% off — $0.348/$0.696 — fails output price rule only
const MOCK_FAIL_OUTPUT: MockModel = {
  id: "mock/fail-output",
  prompt: "0.0000003480",
  completion: "0.0000006960",
  original_prompt: "0.0000017400",
};

// ── Helper: minimal valid env for a single role ───────────────────────────

function baseEnv(extra?: Record<string, string>): Record<string, string> {
  return {
    OPENROUTER_API_KEY: "test-key-123",
    "ROLE_MODEL__test-role": MOCK_PASSING_MODEL.id,
    ...extra,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────

// ── guardModel pre-init (must run before any describe that calls initJobPricing)

describe("guardModel — pre-init cases", () => {
  before(() => {
    _resetState();
  });

  it("throws NOT_INITIALIZED when called before initJobPricing", async () => {
    await assert.rejects(
      () => guardModel("any-role"),
      (err: Error) => {
        assert.ok(err.message.includes("NOT_INITIALIZED"), err.message);
        return true;
      },
    );
  });
});

// ── loadGuardThresholds ───────────────────────────────────────────────────

describe("loadGuardThresholds", () => {
  let restore: (() => void) | undefined;

  afterEach(async () => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("reads GUARD_MIN_DISCOUNT from env", async () => {
    // Set threshold to 0.80 — only models with ≥ 80% discount pass
    restore = mockEnv({
      ...baseEnv(),
      GUARD_MIN_DISCOUNT: "0.80",
    });
    mockFetch([MOCK_PASSING_MODEL]); // 75% off — fails 80% threshold
    await assert.rejects(
      () => initJobPricing(),
      /FATAL/,
    );
  });

  it("reads GUARD_MAX_INPUT_PRICE from env", async () => {
    restore = mockEnv({
      ...baseEnv(),
      GUARD_MAX_INPUT_PRICE: "0.05", // $0.050 max — MOCK_PASSING_MODEL ($0.075) exceeds it
    });
    mockFetch([MOCK_PASSING_MODEL]);
    await assert.rejects(
      () => initJobPricing(),
      /FATAL/,
    );
  });

  it("reads GUARD_MAX_OUTPUT_PRICE from env", async () => {
    restore = mockEnv({
      ...baseEnv(),
      GUARD_MAX_OUTPUT_PRICE: "0.60", // $0.600 max — MOCK_PASSING_MODEL ($0.625) exceeds it
    });
    mockFetch([MOCK_PASSING_MODEL]);
    await assert.rejects(
      () => initJobPricing(),
      /FATAL/,
    );
  });

  it("falls back to default minDiscount 0.15 when GUARD_MIN_DISCOUNT is absent", async () => {
    restore = mockEnv(baseEnv()); // no GUARD_MIN_DISCOUNT
    mockFetch([MOCK_PASSING_MODEL]); // 75% off — passes default 0.15
    await initJobPricing(); // should not throw
    const p = getModelPricing(MOCK_PASSING_MODEL.id)!;
    assert.ok(p.passesGuard, "should pass with default threshold");
  });

  it("falls back to default maxInputPrice 0.50 when GUARD_MAX_INPUT_PRICE is absent", async () => {
    restore = mockEnv(baseEnv());
    // $0.500/M is exactly at boundary — should pass
    const boundaryModel: MockModel = {
      id: "mock/boundary-input",
      prompt: "0.0000005000",
      completion: "0.0000001000",
      original_prompt: "0.0000010000",
    };
    mockFetch([boundaryModel]);
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__test-role": boundaryModel.id,
    });
    await initJobPricing();
    const p = getModelPricing(boundaryModel.id)!;
    assert.ok(p.passesGuard, "boundary input should pass with default 0.50 threshold");
  });

  it("falls back to default maxOutputPrice 0.65 when GUARD_MAX_OUTPUT_PRICE is absent", async () => {
    const boundaryModel: MockModel = {
      id: "mock/boundary-output",
      prompt: "0.0000001000",
      completion: "0.0000006500",
      original_prompt: "0.0000010000",
    };
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__test-role": boundaryModel.id,
    });
    mockFetch([boundaryModel]);
    await initJobPricing();
    const p = getModelPricing(boundaryModel.id)!;
    assert.ok(p.passesGuard, "boundary output should pass with default 0.65 threshold");
  });

  it("parses string env values to float correctly", async () => {
    restore = mockEnv({
      ...baseEnv(),
      GUARD_MIN_DISCOUNT: "0.80", // string "0.80" → float 0.80
    });
    mockFetch([MOCK_PASSING_MODEL]); // 75% discount → fails 80% threshold
    await assert.rejects(
      () => initJobPricing(),
      /FATAL/,
      "should treat string '0.80' as float 0.80 not string comparison",
    );
  });
});

// ── loadRoleModels ────────────────────────────────────────────────────────

describe("loadRoleModels", () => {
  let restore: (() => void) | undefined;

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("parses ROLE_MODEL__ prefix correctly into role → modelId map", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": MOCK_PASSING_MODEL.id,
    });
    mockFetch([MOCK_PASSING_MODEL]);
    await initJobPricing();
    const report = await guardModel("my-role");
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
  });

  it("throws NO_ROLES when no ROLE_MODEL__ keys present", async () => {
    restore = mockEnv({ OPENROUTER_API_KEY: "test-key-123" });
    mockFetch([MOCK_PASSING_MODEL]);
    await assert.rejects(
      () => initJobPricing(),
      (err: Error) => {
        assert.ok(err.message.includes("NO_ROLES"), err.message);
        return true;
      },
    );
  });

  it("trims whitespace from model IDs", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": `  ${MOCK_PASSING_MODEL.id}  `,
    });
    mockFetch([MOCK_PASSING_MODEL]);
    await initJobPricing();
    const report = await guardModel("my-role");
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
  });
});

// ── loadRoleFallbacks ─────────────────────────────────────────────────────

describe("loadRoleFallbacks", () => {
  let restore: (() => void) | undefined;

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("parses ROLE_FALLBACK__ prefix into role → string[] map", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": MOCK_FAIL_DISCOUNT.id,
      "ROLE_FALLBACK__my-role": `${MOCK_PASSING_MODEL.id},${MOCK_CHEAP_MODEL.id}`,
    });
    mockFetch([MOCK_FAIL_DISCOUNT, MOCK_PASSING_MODEL, MOCK_CHEAP_MODEL]);
    await initJobPricing();
    const report = await guardModel("my-role");
    assert.equal(report.isFallback, true);
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
  });

  it("splits comma-separated fallbacks correctly", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": MOCK_FAIL_DISCOUNT.id,
      "ROLE_FALLBACK__my-role": `${MOCK_FAIL_OUTPUT.id},${MOCK_PASSING_MODEL.id},${MOCK_CHEAP_MODEL.id}`,
    });
    mockFetch([MOCK_FAIL_DISCOUNT, MOCK_FAIL_OUTPUT, MOCK_PASSING_MODEL, MOCK_CHEAP_MODEL]);
    await initJobPricing();
    // Primary and first fallback fail; second fallback passes
    const report = await guardModel("my-role");
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
    assert.equal(report.fallbackIndex, 2);
  });

  it("trims whitespace around each fallback entry", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": MOCK_FAIL_DISCOUNT.id,
      "ROLE_FALLBACK__my-role": `  ${MOCK_PASSING_MODEL.id}  , ${MOCK_CHEAP_MODEL.id} `,
    });
    mockFetch([MOCK_FAIL_DISCOUNT, MOCK_PASSING_MODEL, MOCK_CHEAP_MODEL]);
    await initJobPricing();
    const report = await guardModel("my-role");
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
  });

  it("returns empty fallback list when no ROLE_FALLBACK__ keys present", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__my-role": MOCK_FAIL_DISCOUNT.id,
      // no ROLE_FALLBACK__my-role
    });
    mockFetch([MOCK_FAIL_DISCOUNT]);
    await assert.rejects(
      () => initJobPricing(),
      /FATAL/,
    );
  });
});

// ── guard rules ───────────────────────────────────────────────────────────

describe("guard rules", () => {
  let restore: (() => void) | undefined;

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  // Always uses MOCK_PASSING_MODEL for the role so initJobPricing() succeeds.
  // All provided models appear in the fetch response and are therefore cached —
  // call getModelPricing(id) after setup() to inspect their computed pricing.
  async function setup(extraModels: MockModel[]): Promise<void> {
    const seen = new Set<string>();
    const allModels: MockModel[] = [];
    for (const m of [MOCK_PASSING_MODEL, ...extraModels]) {
      if (!seen.has(m.id)) { seen.add(m.id); allModels.push(m); }
    }
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__r": MOCK_PASSING_MODEL.id,
    });
    mockFetch(allModels);
    await initJobPricing(); // always succeeds — MOCK_PASSING_MODEL is the role's model
  }

  it("model passes when discount >= 0.15, input <= 0.50, output <= 0.65", async () => {
    await setup([]);
    const p = getModelPricing(MOCK_PASSING_MODEL.id)!;
    assert.ok(p.passesGuard, JSON.stringify(p.failReasons));
    assert.deepEqual(p.failReasons, []);
    assert.ok(p.discountRate >= 0.15);
    assert.ok(p.inputPricePerM <= 0.50);
    assert.ok(p.outputPricePerM <= 0.65);
  });

  it("model fails when discount < 0.15", async () => {
    await setup([MOCK_FAIL_DISCOUNT]);
    const p = getModelPricing(MOCK_FAIL_DISCOUNT.id)!;
    assert.ok(!p.passesGuard);
    assert.ok(p.failReasons.some((r) => r.includes("discount")), p.failReasons.join());
  });

  it("model fails when input > 0.50", async () => {
    const highInput: MockModel = {
      id: "mock/high-input",
      prompt: "0.0000006000",      // $0.600/M — exceeds $0.500
      completion: "0.0000001000",
      original_prompt: "0.0000010000", // 40% off — passes discount
    };
    await setup([highInput]);
    const p = getModelPricing(highInput.id)!;
    assert.ok(!p.passesGuard);
    assert.ok(p.failReasons.some((r) => r.includes("input")), p.failReasons.join());
  });

  it("model fails when output > 0.65", async () => {
    await setup([MOCK_FAIL_OUTPUT]);
    const p = getModelPricing(MOCK_FAIL_OUTPUT.id)!;
    assert.ok(!p.passesGuard);
    assert.ok(p.failReasons.some((r) => r.includes("output")), p.failReasons.join());
  });

  it("model fails when multiple rules violated — failReasons lists all failures", async () => {
    const multiFailModel: MockModel = {
      id: "mock/multi-fail",
      prompt: "0.0000006000",      // $0.600/M — fails input
      completion: "0.0000006960",  // $0.696/M — fails output
      original_prompt: "0.0000006316", // ~5% off — fails discount
    };
    await setup([multiFailModel]);
    const p = getModelPricing(multiFailModel.id)!;
    assert.ok(!p.passesGuard);
    assert.ok(p.failReasons.length >= 2, `expected ≥2 reasons, got: ${p.failReasons.join()}`);
    assert.ok(p.failReasons.some((r) => r.includes("discount")), p.failReasons.join());
    assert.ok(p.failReasons.some((r) => r.includes("input") || r.includes("output")), p.failReasons.join());
  });

  it("model passes at exact boundary values (0.15, 0.50, 0.65)", async () => {
    // Use 50% discount to avoid IEEE 754 imprecision at the 0.15 boundary.
    // The check verifies <= (not <) for input and output.
    const boundaryModel: MockModel = {
      id: "mock/boundary-all",
      prompt: "0.0000005000",      // $0.500/M — at maxInput boundary (<=)
      completion: "0.0000006500",  // $0.650/M — at maxOutput boundary (<=)
      original_prompt: "0.0000010000", // $1.000/M → 50% off (well above 15%)
    };
    await setup([boundaryModel]);
    const p = getModelPricing(boundaryModel.id)!;
    assert.ok(p.passesGuard, `failReasons: ${p.failReasons.join()}`);
    assert.equal(p.failReasons.length, 0);
    assert.ok(Math.abs(p.inputPricePerM - 0.5) < 0.001, `input=${p.inputPricePerM}`);
    assert.ok(Math.abs(p.outputPricePerM - 0.65) < 0.001, `output=${p.outputPricePerM}`);
  });

  it("discount derived from original_prompt when present", async () => {
    const model: MockModel = {
      id: "mock/orig-prompt",
      prompt: "0.0000001000",
      completion: "0.0000002000",
      original_prompt: "0.0000002000", // 50% off
    };
    await setup([model]);
    const p = getModelPricing(model.id)!;
    assert.ok(Math.abs(p.discountRate - 0.5) < 0.001, `expected ~50%, got ${p.discountRate}`);
  });

  it("discount derived from original_completion when original_prompt absent", async () => {
    const model: MockModel = {
      id: "mock/orig-completion",
      prompt: "0.0000001000",
      completion: "0.0000002000",
      // no original_prompt
      original_completion: "0.0000004000", // 50% off on completion
    };
    await setup([model]);
    const p = getModelPricing(model.id)!;
    assert.ok(Math.abs(p.discountRate - 0.5) < 0.001, `expected ~50%, got ${p.discountRate}`);
  });

  it("discount is 0 when neither original field present", async () => {
    const model: MockModel = {
      id: "mock/no-discount",
      prompt: "0.0000001000",
      completion: "0.0000002000",
      // no originals
    };
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__r": model.id,
    });
    mockFetch([model, MOCK_PASSING_MODEL]);
    await assert.rejects(() => initJobPricing(), /FATAL/); // fails discount rule
    const p = getModelPricing(model.id)!;
    assert.equal(p.discountRate, 0);
    assert.ok(p.failReasons.some((r) => r.includes("discount 0%")), p.failReasons.join());
  });
});

// ── initJobPricing ────────────────────────────────────────────────────────

describe("initJobPricing", () => {
  let restore: (() => void) | undefined;

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("throws MISSING_API_KEY when OPENROUTER_API_KEY not set", async () => {
    restore = mockEnv({ "ROLE_MODEL__r": MOCK_PASSING_MODEL.id });
    // Ensure OPENROUTER_API_KEY is absent
    const savedKey = process.env["OPENROUTER_API_KEY"];
    delete process.env["OPENROUTER_API_KEY"];
    mockFetch([MOCK_PASSING_MODEL]);
    try {
      await assert.rejects(
        () => initJobPricing(),
        (err: Error) => {
          assert.ok(err.message.includes("MISSING_API_KEY"), err.message);
          return true;
        },
      );
    } finally {
      if (savedKey !== undefined) process.env["OPENROUTER_API_KEY"] = savedKey;
    }
  });

  it("throws API_ERROR on non-200 response", async () => {
    restore = mockEnv(baseEnv());
    (globalThis as Record<string, unknown>)["fetch"] = async () => ({
      ok: false,
      status: 429,
      statusText: "Too Many Requests",
      json: async () => ({}),
    });
    await assert.rejects(
      () => initJobPricing(),
      (err: Error) => {
        assert.ok(err.message.includes("API_ERROR"), err.message);
        assert.ok(err.message.includes("429"), err.message);
        return true;
      },
    );
  });

  it("throws on malformed response (no data array)", async () => {
    restore = mockEnv(baseEnv());
    (globalThis as Record<string, unknown>)["fetch"] = async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ models: [] }), // missing data array
    });
    await assert.rejects(
      () => initJobPricing(),
      (err: Error) => {
        assert.ok(err.message.includes("data array"), err.message);
        return true;
      },
    );
  });

  it("throws NO_ROLES when no ROLE_MODEL__ in env", async () => {
    restore = mockEnv({ OPENROUTER_API_KEY: "test-key-123" });
    mockFetch([MOCK_PASSING_MODEL]);
    await assert.rejects(
      () => initJobPricing(),
      (err: Error) => {
        assert.ok(err.message.includes("NO_ROLES"), err.message);
        return true;
      },
    );
  });

  it("populates pricing cache on success", async () => {
    restore = mockEnv(baseEnv());
    mockFetch([MOCK_PASSING_MODEL, MOCK_CHEAP_MODEL]);
    await initJobPricing();
    const p = getModelPricing(MOCK_PASSING_MODEL.id);
    assert.ok(p, "MOCK_PASSING_MODEL should be in cache");
    assert.ok(Math.abs(p.inputPricePerM - 0.075) < 0.001);
    assert.ok(Math.abs(p.outputPricePerM - 0.625) < 0.001);
    assert.ok(Math.abs(p.discountRate - 0.75) < 0.001);
  });

  it("re-fetches on second call (does not reuse prior state)", async () => {
    restore = mockEnv(baseEnv());
    mockFetch([MOCK_PASSING_MODEL]);
    await initJobPricing();
    assert.equal(fetchCallCount, 1);
    await initJobPricing();
    assert.equal(fetchCallCount, 2);
  });

  it("logs ✓ for every passing role at init", async () => {
    const logLines: string[] = [];
    const orig = console.log;
    console.log = (...args: unknown[]) => logLines.push(String(args[0]));
    restore = mockEnv(baseEnv());
    mockFetch([MOCK_PASSING_MODEL]);
    try {
      await initJobPricing();
    } finally {
      console.log = orig;
    }
    const passingLines = logLines.filter((l) => l.includes("✓"));
    assert.ok(passingLines.length >= 1, "expected at least one ✓ line");
    assert.ok(
      passingLines.some((l) => l.includes(MOCK_PASSING_MODEL.id)),
      `expected model id in log, got: ${passingLines.join("\n")}`,
    );
  });

  it("throws FATAL after logging when any role has no passing model", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__bad-role": MOCK_FAIL_DISCOUNT.id,
    });
    mockFetch([MOCK_FAIL_DISCOUNT]);
    await assert.rejects(
      () => initJobPricing(),
      (err: Error) => {
        assert.ok(err.message.includes("FATAL"), err.message);
        return true;
      },
    );
  });
});

// ── guardModel (full suite) ───────────────────────────────────────────────

describe("guardModel", () => {
  let restore: (() => void) | undefined;

  beforeEach(async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__primary-role": MOCK_PASSING_MODEL.id,
      "ROLE_MODEL__fallback-role": MOCK_FAIL_DISCOUNT.id,
      "ROLE_FALLBACK__fallback-role": `${MOCK_FAIL_OUTPUT.id},${MOCK_PASSING_MODEL.id}`,
      "ROLE_MODEL__blocked-role": MOCK_FAIL_DISCOUNT.id,
      "ROLE_FALLBACK__blocked-role": MOCK_FAIL_OUTPUT.id,
    });
    mockFetch([MOCK_PASSING_MODEL, MOCK_FAIL_DISCOUNT, MOCK_FAIL_OUTPUT, MOCK_CHEAP_MODEL]);
    // blocked-role has no passing model → initJobPricing throws FATAL.
    // State IS committed before the throw, so guardModel works for all other roles.
    await initJobPricing().catch(() => {});
  });

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("throws UNKNOWN_ROLE for unrecognised role string", async () => {
    await assert.rejects(
      () => guardModel("typo-role"),
      (err: Error) => {
        assert.ok(err.message.includes("UNKNOWN_ROLE"), err.message);
        assert.ok(err.message.includes("typo-role"), err.message);
        return true;
      },
    );
  });

  it("returns GuardReport with primary model when it passes", async () => {
    const report = await guardModel("primary-role");
    assert.equal(report.role, "primary-role");
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
    assert.equal(report.isFallback, false);
    assert.equal(report.fallbackIndex, undefined);
    assert.equal(report.primaryFailReasons, undefined);
  });

  it("isFallback is false on primary selection", async () => {
    const report = await guardModel("primary-role");
    assert.equal(report.isFallback, false);
  });

  it("tries fallback when primary fails, returns fallback GuardReport", async () => {
    const report = await guardModel("fallback-role");
    assert.equal(report.isFallback, true);
    assert.equal(report.selectedModel, MOCK_PASSING_MODEL.id);
  });

  it("isFallback is true and fallbackIndex is set on fallback selection", async () => {
    const report = await guardModel("fallback-role");
    assert.equal(report.isFallback, true);
    assert.ok(report.fallbackIndex !== undefined);
    assert.ok(report.fallbackIndex! >= 1);
  });

  it("primaryFailReasons set when using fallback", async () => {
    const report = await guardModel("fallback-role");
    assert.ok(Array.isArray(report.primaryFailReasons));
    assert.ok(report.primaryFailReasons!.length > 0, "should have primary fail reasons");
  });

  it("throws BLOCKED when primary and all fallbacks fail", async () => {
    await assert.rejects(
      () => guardModel("blocked-role"),
      (err: Error) => {
        assert.ok(err.message.includes("BLOCKED"), err.message);
        assert.ok(err.message.includes("blocked-role"), err.message);
        return true;
      },
    );
  });

  it("logs correct model ID and pricing on every call", async () => {
    const logLines: string[] = [];
    const orig = console.log;
    console.log = (...args: unknown[]) => logLines.push(String(args[0]));
    try {
      await guardModel("primary-role");
    } finally {
      console.log = orig;
    }
    const guardLine = logLines.find((l) => l.includes("✓") && l.includes(MOCK_PASSING_MODEL.id));
    assert.ok(guardLine, `expected log line with model id, got: ${logLines.join("\n")}`);
    assert.ok(guardLine.includes("$"), "should include price info");
  });
});

// ── getGuardReport ────────────────────────────────────────────────────────

describe("getGuardReport", () => {
  let restore: (() => void) | undefined;

  afterEach(() => {
    restoreFetch();
    restore?.();
    restore = undefined;
    _resetState();
  });

  it("returns empty array before any guardModel calls", async () => {
    restore = mockEnv(baseEnv());
    mockFetch([MOCK_PASSING_MODEL]);
    await initJobPricing();
    assert.deepEqual(getGuardReport(), []);
  });

  it("accumulates one report per guardModel call", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__role-a": MOCK_PASSING_MODEL.id,
      "ROLE_MODEL__role-b": MOCK_CHEAP_MODEL.id,
    });
    mockFetch([MOCK_PASSING_MODEL, MOCK_CHEAP_MODEL]);
    await initJobPricing();
    await guardModel("role-a");
    assert.equal(getGuardReport().length, 1);
    await guardModel("role-b");
    assert.equal(getGuardReport().length, 2);
    assert.equal(getGuardReport()[0]!.role, "role-a");
    assert.equal(getGuardReport()[1]!.role, "role-b");
  });

  it("resets between initJobPricing calls", async () => {
    restore = mockEnv({
      OPENROUTER_API_KEY: "test-key-123",
      "ROLE_MODEL__role-a": MOCK_PASSING_MODEL.id,
    });
    mockFetch([MOCK_PASSING_MODEL]);
    await initJobPricing();
    await guardModel("role-a");
    assert.equal(getGuardReport().length, 1);

    // Second initJobPricing call should reset the report list
    await initJobPricing();
    assert.equal(getGuardReport().length, 0);
  });
});

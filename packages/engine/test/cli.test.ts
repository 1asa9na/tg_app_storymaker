import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const CLI = fileURLToPath(new URL("../src/cli.ts", import.meta.url));

function run(input: string) {
  const result = spawnSync(process.execPath, [CLI], { input, encoding: "utf8" });
  return { code: result.status, stdout: result.stdout, stderr: result.stderr };
}

describe("cli", () => {
  it("compiles scenes and reports diagnostics per scene", () => {
    const { code, stdout } = run(
      JSON.stringify({
        scenes: { ok: "# effect: xp 5\nПривет.\n", broken: "# bg: beach\nТекст.\n" },
        registry: { backgrounds: ["gym"] },
      }),
    );

    const response = JSON.parse(stdout);
    expect(code).toBe(0);
    expect(response.ok).toBe(false);
    expect(response.scenes.ok.effects).toEqual([{ op: "xp", amount: 5 }]);
    expect(typeof response.scenes.ok.json).toBe("string");
    expect(response.scenes.broken).toBeUndefined();
    expect(response.diagnostics.broken[0].message).toBe("Фона «beach» нет в тайтле");
  });

  it("exits with 2 on a malformed request", () => {
    const { code, stderr } = run("{}");

    expect(code).toBe(2);
    expect(stderr).toContain("scenes");
  });
});

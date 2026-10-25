// Компиляция сцен для сервера: JSON на stdin → JSON на stdout.
//   node packages/engine/src/cli.ts < request.json
// Запрос: {"scenes": {"<ключ>": "<исходник ink>"}, "registry": {...}}
// Ответ:  {"ok": bool, "scenes": {"<ключ>": {"json", "effects"}}, "diagnostics": {"<ключ>": [...]}}
import { readFileSync } from "node:fs";

import { compileScene, type CompiledScene, type Diagnostic, type Registry } from "./compile.ts";

interface Request {
  scenes: Record<string, string>;
  registry?: Registry;
}

let request: Request;
try {
  request = JSON.parse(readFileSync(0, "utf8")) as Request;
  if (typeof request.scenes !== "object" || request.scenes === null) {
    throw new Error("поле scenes обязательно");
  }
} catch (error) {
  process.stderr.write(`некорректный запрос: ${(error as Error).message}\n`);
  process.exit(2);
}

const scenes: Record<string, CompiledScene> = {};
const diagnostics: Record<string, Diagnostic[]> = {};
let ok = true;
for (const [key, source] of Object.entries(request.scenes)) {
  const result = compileScene(source, request.registry);
  if (result.scene) {
    scenes[key] = result.scene;
  } else {
    ok = false;
  }
  if (result.diagnostics.length > 0) {
    diagnostics[key] = result.diagnostics;
  }
}
process.stdout.write(JSON.stringify({ ok, scenes, diagnostics }));

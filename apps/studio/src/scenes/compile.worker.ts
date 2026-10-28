// Компиляция сцены в фоне, чтобы не тормозить ввод: тот же компилятор, что и при сборке
// (packages/engine/src/compile.ts), и тот же реестр ключей от сервера.
import { compileScene, type CompileResult, type Registry } from "@storymaker/engine/compile";

export interface CompileRequest {
  id: number;
  source: string;
  registry: Registry;
}

export interface CompileResponse {
  id: number;
  result: CompileResult;
}

self.onmessage = (event: MessageEvent<CompileRequest>) => {
  const { id, source, registry } = event.data;
  let result: CompileResult;
  try {
    result = compileScene(source, registry);
  } catch (error) {
    result = {
      scene: null,
      diagnostics: [
        { severity: "error", line: null, message: `Компилятор упал: ${(error as Error).message}` },
      ],
    };
  }
  self.postMessage({ id, result } satisfies CompileResponse);
};

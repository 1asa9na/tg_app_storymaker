// Monaco для сцен: только ядро редактора и нужные функции (без встроенных языков и LSP),
// воркер — из нашего бандла, без CDN. Модуль грузится лениво вместе со страницей сцен.
import "monaco-editor/nls/lang/ru.js";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/features/codicon/register.js";
import "monaco-editor/features/codeEditor/register.js";
import "monaco-editor/features/bracketMatching/register.js";
import "monaco-editor/features/clipboard/register.js";
import "monaco-editor/features/comment/register.js";
import "monaco-editor/features/contextmenu/register.js";
import "monaco-editor/features/cursorUndo/register.js";
import "monaco-editor/features/find/register.js";
import "monaco-editor/features/folding/register.js";
import "monaco-editor/features/gotoError/register.js";
import "monaco-editor/features/gotoLine/register.js";
import "monaco-editor/features/gotoSymbol/register.js";
import "monaco-editor/features/hover/register.js";
import "monaco-editor/features/linesOperations/register.js";
import "monaco-editor/features/multicursor/register.js";
import "monaco-editor/features/quickOutline/register.js";
import "monaco-editor/features/snippet/register.js";
import "monaco-editor/features/suggest/register.js";
import "monaco-editor/features/wordHighlighter/register.js";
import "monaco-editor/features/wordOperations/register.js";
// Ядро, которое editor.main подключает отдельно от features: без него нет подсказок и команд.
import "monaco-editor/editor/browser/coreCommands.js";
import "monaco-editor/editor/common/standaloneStrings.js";
import "monaco-editor/editor/contrib/suggest/browser/suggestController.js";
import "monaco-editor/editor/contrib/gotoSymbol/browser/goToCommands.js";
import "monaco-editor/editor/contrib/gotoError/browser/markerSelectionStatus.js";
import "monaco-editor/editor/contrib/dropOrPasteInto/browser/copyPasteContribution.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";

import {
  complete,
  EFFECTS,
  FUNCTIONS,
  outline,
  TAGS,
  type SceneContext,
  type Suggestion,
} from "./analysis";

export { monaco };

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };

export const LANGUAGE = "ink";
export const THEME = "storymaker";

/** Ключи тайтла для подсказок: обновляется страницей, провайдеры читают при вызове. */
let context: SceneContext | null = null;
export function setContext(next: SceneContext) {
  context = next;
}

const language: monaco.languages.IMonarchLanguage = {
  // Перевод строки виден правилам: им закрываются состояния, живущие до конца строки.
  includeLF: true,
  defaultToken: "",
  functions: Object.keys(FUNCTIONS),
  keywords: ["and", "or", "not", "true", "false", "mod"],
  tokenizer: {
    root: [
      [/^\s*={2,}.*/, "knot"],
      [/^\s*=\s*\w+.*/, "stitch"],
      [/^\s*(?:INCLUDE|VAR|CONST|LIST|EXTERNAL)\b/, "keyword", "@code"],
      [/^\s*~/, "keyword", "@code"],
      [/^\s*TODO\b.*/, "comment.todo"],
      [/^(\s*)((?:[*+]\s*)+)(\(\w+\))/, ["", "choice", "label"]],
      [/^(\s*)((?:[*+]\s*)+)/, ["", "choice"]],
      [/^(\s*)((?:-(?!>)\s*)+)(\(\w+\))/, ["", "gather", "label"]],
      [/^(\s*)((?:-(?!>)\s*)+)([a-z][a-z0-9_]*)(:)(?=\s)/, ["", "gather", "speaker", "speaker"]],
      [/^(\s*)((?:-(?!>)\s*)+)/, ["", "gather"]],
      [/^(\s*)([a-z][a-z0-9_]*)(:)(?=\s)/, ["", "speaker", "speaker"]],
      { include: "@line" },
    ],
    line: [
      [/\/\/.*/, "comment"],
      [/\/\*/, "comment", "@comment"],
      [
        /(#\s*)(effect)(\s*:\s*)([a-z_]+)([^#\]\n]*)/,
        ["tag", "tag.name", "tag", "tag.op", "tag.value"],
      ],
      [/(#\s*)([a-z_]+)(\s*:)([^#\]\n]*)/, ["tag", "tag.name", "tag", "tag.value"]],
      [/#[^#\]\n]*/, "tag"],
      [/(->->|->|<-)(\s*)([\w.]+)/, ["divert", "", "divert.target"]],
      [/->->|->|<-/, "divert"],
      [/<>/, "glue"],
      [/\{/, "logic", "@logic"],
      [/[[\]]/, "bracket.choice"],
      [/[^#{}[\]/<>\-\n]+/, ""],
      [/[\s\S]/, ""],
    ],
    comment: [
      [/[^*]+/, "comment"],
      [/\*\//, "comment", "@pop"],
      [/\*/, "comment"],
    ],
    code: [[/\n/, "", "@pop"], [/\/\/.*/, "comment"], { include: "@expression" }],
    logic: [
      [/\{/, "logic", "@push"],
      [/\}/, "logic", "@pop"],
      [/#[^#}\n]*/, "tag"],
      { include: "@expression" },
    ],
    expression: [
      [/"([^"\\\n]|\\.)*"/, "string"],
      [/\d+(\.\d+)?/, "number"],
      [/[A-Za-z_]\w*(?=\s*\()/, { cases: { "@functions": "predefined", "@default": "function" } }],
      [/[A-Za-z_][\w.]*/, { cases: { "@keywords": "keyword", "@default": "variable" } }],
      [/->/, "divert"],
      [/[-+*/%=!<>&|?:]/, "operator"],
      [/[\s\S]/, ""],
    ],
  },
};

const KIND: Record<Suggestion["kind"], monaco.languages.CompletionItemKind> = {
  tag: monaco.languages.CompletionItemKind.Keyword,
  key: monaco.languages.CompletionItemKind.Constant,
  character: monaco.languages.CompletionItemKind.User,
  node: monaco.languages.CompletionItemKind.Module,
  function: monaco.languages.CompletionItemKind.Function,
  value: monaco.languages.CompletionItemKind.EnumMember,
};

const SYMBOL: Record<string, monaco.languages.SymbolKind> = {
  knot: monaco.languages.SymbolKind.Module,
  stitch: monaco.languages.SymbolKind.Namespace,
  label: monaco.languages.SymbolKind.Key,
  function: monaco.languages.SymbolKind.Function,
};

let registered = false;

export function registerInk() {
  if (registered) return;
  registered = true;

  monaco.languages.register({ id: LANGUAGE });
  monaco.languages.setMonarchTokensProvider(LANGUAGE, language);
  monaco.languages.setLanguageConfiguration(LANGUAGE, {
    comments: { lineComment: "//", blockComment: ["/*", "*/"] },
    brackets: [
      ["{", "}"],
      ["[", "]"],
      ["(", ")"],
    ],
    autoClosingPairs: [
      { open: "{", close: "}" },
      { open: "[", close: "]" },
      { open: "(", close: ")" },
      { open: '"', close: '"' },
    ],
    // Ключи — латиница, цифры и _; точка разделяет узел и подузел в `-> knot.stitch`.
    wordPattern: /[A-Za-z_][\w.]*/,
  });

  monaco.editor.defineTheme(THEME, {
    base: "vs",
    inherit: true,
    rules: [
      { token: "knot", foreground: "5b3fa8", fontStyle: "bold" },
      { token: "stitch", foreground: "7a5fc0", fontStyle: "bold" },
      { token: "choice", foreground: "c2410c", fontStyle: "bold" },
      { token: "gather", foreground: "c2410c", fontStyle: "bold" },
      { token: "label", foreground: "7a5fc0" },
      { token: "bracket.choice", foreground: "c2410c" },
      { token: "speaker", foreground: "0f766e", fontStyle: "bold" },
      { token: "tag", foreground: "8a8299" },
      { token: "tag.name", foreground: "a21caf" },
      { token: "tag.op", foreground: "a21caf" },
      { token: "tag.value", foreground: "15803d" },
      { token: "divert", foreground: "b91c1c", fontStyle: "bold" },
      { token: "divert.target", foreground: "5b3fa8" },
      { token: "glue", foreground: "b91c1c" },
      { token: "logic", foreground: "1d4ed8", fontStyle: "bold" },
      { token: "predefined", foreground: "1d4ed8" },
      { token: "variable", foreground: "1e40af" },
      { token: "string", foreground: "15803d" },
      { token: "number", foreground: "b45309" },
      { token: "keyword", foreground: "1d4ed8" },
      { token: "operator", foreground: "475569" },
      { token: "comment", foreground: "94a3b8", fontStyle: "italic" },
      { token: "comment.todo", foreground: "d97706", fontStyle: "italic bold" },
    ],
    colors: {
      "editor.background": "#ffffff",
      "editorLineNumber.foreground": "#b4adc2",
    },
  });

  monaco.languages.registerCompletionItemProvider(LANGUAGE, {
    triggerCharacters: ["#", ":", " ", ">", '"', "(", "{", "."],
    provideCompletionItems(model, position) {
      if (!context) return { suggestions: [] };
      const before = model.getLineContent(position.lineNumber).slice(0, position.column - 1);
      const result = complete(before, model.getValue(), context);
      if (!result) return { suggestions: [] };
      const range = new monaco.Range(
        position.lineNumber,
        position.column - result.replace,
        position.lineNumber,
        position.column,
      );
      return {
        suggestions: result.items.map((item, index) => ({
          label: item.detail ? { label: item.label, description: item.detail } : item.label,
          insertText: item.insert ?? item.label,
          filterText: item.label,
          // Порядок как в данных тайтла, а не по алфавиту.
          sortText: String(index).padStart(4, "0"),
          kind: KIND[item.kind],
          documentation: item.documentation ? { value: item.documentation } : undefined,
          range,
          command: item.retrigger
            ? { id: "editor.action.triggerSuggest", title: "ещё подсказки" }
            : undefined,
        })),
      };
    },
  });

  monaco.languages.registerHoverProvider(LANGUAGE, {
    provideHover(model, position) {
      const word = model.getWordAtPosition(position);
      if (!word || !context) return null;
      const line = model.getLineContent(position.lineNumber);
      const before = line.slice(0, word.startColumn - 1);
      const key = word.word;
      let text: string | undefined;
      if (/#\s*$/.test(before)) text = TAGS[key];
      else if (/effect:\s*$/.test(before)) text = EFFECTS[key];
      else if (FUNCTIONS[key] && line.slice(word.endColumn - 1).startsWith("(")) {
        text = FUNCTIONS[key];
      } else if (context.characters[key]) {
        const c = context.characters[key];
        text = `**${c.name}** — эмоции: ${c.emotions.join(", ") || "нет"}`;
      } else if (context.items[key]) text = `Предмет: **${context.items[key]}**`;
      else if (context.quests[key]) text = `Квест: **${context.quests[key]}**`;
      else if (context.stats[key]) text = `Характеристика: **${context.stats[key]}**`;
      if (!text) return null;
      return {
        range: new monaco.Range(
          position.lineNumber,
          word.startColumn,
          position.lineNumber,
          word.endColumn,
        ),
        contents: [{ value: text }],
      };
    },
  });

  monaco.languages.registerDefinitionProvider(LANGUAGE, {
    provideDefinition(model, position) {
      const word = model.getWordAtPosition(position);
      if (!word) return null;
      const nodes = outline(model.getValue());
      const target =
        nodes.find((node) => node.path === word.word) ??
        nodes.find((node) => node.path.endsWith(`.${word.word}`));
      if (!target) return null;
      return {
        uri: model.uri,
        range: new monaco.Range(target.line, 1, target.line, 1),
      };
    },
  });

  monaco.languages.registerDocumentSymbolProvider(LANGUAGE, {
    provideDocumentSymbols(model) {
      return outline(model.getValue()).map((node) => {
        const range = new monaco.Range(node.line, 1, node.line, model.getLineMaxColumn(node.line));
        return {
          name: node.path,
          detail: "",
          kind: SYMBOL[node.kind]!,
          tags: [],
          range,
          selectionRange: range,
        };
      });
    },
  });

  // Узел сворачивается до следующего узла, подузел — до следующего подузла или узла.
  monaco.languages.registerFoldingRangeProvider(LANGUAGE, {
    provideFoldingRanges(model) {
      const nodes = outline(model.getValue()).filter((node) => node.kind !== "label");
      const end = model.getLineCount() + 1;
      return nodes
        .map((node, i) => {
          const next = nodes
            .slice(i + 1)
            .find((other) => node.kind === "stitch" || other.kind !== "stitch");
          return { start: node.line, end: (next?.line ?? end) - 1 };
        })
        .filter((range) => range.end > range.start);
    },
  });
}

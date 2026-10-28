import type { CompileResult, Diagnostic } from "@storymaker/engine/compile";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { problems as describe, request, StudioError } from "../api";
import { setLeaveGuard } from "../navigation";
import { nodeAt, outline, type SceneContext } from "./analysis";
import CompileWorker from "./compile.worker?worker";
import type { CompileRequest, CompileResponse } from "./compile.worker";
import { LANGUAGE, monaco, registerInk, setContext, THEME } from "./monaco";
import { Preview } from "./Preview";

// Сцены тайтла: список слева, редактор ink в Monaco, превью справа. Ошибки компилятора
// и наших тегов подчёркиваются в строках сразу при вводе; сохранить можно и с ошибками —
// их не пропустит сборка. Править сцены может любой сотрудник.

interface Problems {
  errors: string[];
  warnings: string[];
}

interface Loaded {
  source: string;
  /** Время сохранённой версии; null — сцены ещё нет на сервере. */
  updatedAt: string | null;
}

interface Conflict {
  exists: boolean;
  updated_at: string | null;
  updated_by: string | null;
}

const KEY = /^[a-z][a-z0-9_]*$/;
const SCENE_FLAG = /effect:\s*(?:un)?flag\s+([a-z][a-z0-9_]*)|\bflag\(\s*"([a-z][a-z0-9_]*)"\s*\)/g;

let worker: Worker | null = null;
let nextId = 0;

/** Компиляция в фоновом воркере; ответ на устаревший запрос отбрасывается вызывающим. */
function compile(source: string, registry: SceneContext["registry"]): Promise<CompileResult> {
  worker ??= new CompileWorker();
  const id = ++nextId;
  const target = worker;
  return new Promise((resolve) => {
    const onMessage = (event: MessageEvent<CompileResponse>) => {
      if (event.data.id !== id) return;
      target.removeEventListener("message", onMessage);
      resolve(event.data.result);
    };
    target.addEventListener("message", onMessage);
    target.postMessage({ id, source, registry } satisfies CompileRequest);
  });
}

function template(context: SceneContext): string {
  const bg = context.backgrounds[0] ?? "home";
  return `# bg: ${bg}\nТекст сцены.\n-> END\n`;
}

export function ScenesPage({
  slug,
  sceneKey,
  onOpen,
}: {
  slug: string;
  sceneKey: string | null;
  onOpen(key: string | null): void;
}) {
  const [context, setLocalContext] = useState<SceneContext | null>(null);
  const [failed, setFailed] = useState(false);
  const [problems, setProblems] = useState<Problems | null>(null);
  const dirty = useRef(false);

  const reload = useCallback(
    () =>
      request<SceneContext>("GET", `/titles/${slug}/scenes`).then(
        (next) => {
          setContext(next);
          setLocalContext(next);
        },
        () => setFailed(true),
      ),
    [slug],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  // Любой переход внутри студии — к другой сцене или прочь со страницы — спросит о правках.
  useEffect(() => {
    setLeaveGuard(() => {
      if (!dirty.current) return true;
      if (!window.confirm("В сцене есть несохранённые правки. Уйти без них?")) return false;
      dirty.current = false;
      return true;
    });
    return () => setLeaveGuard(null);
  }, []);

  const open = (key: string | null) => {
    if (key !== sceneKey) onOpen(key);
  };

  if (failed) return <p className="error">Не удалось загрузить сцены тайтла.</p>;
  if (!context) return <p className="muted">Загружаем…</p>;

  const exists = sceneKey !== null && context.scenes.some((s) => s.key === sceneKey);

  return (
    <div className="scenes">
      <nav className="scene-list">
        <ul>
          {context.scenes.map((scene) => (
            <li key={scene.key}>
              <button
                type="button"
                className={`link${scene.key === sceneKey ? " active" : ""}`}
                onClick={() => open(scene.key)}
              >
                {scene.key}
              </button>
            </li>
          ))}
          {sceneKey && !exists && (
            <li>
              <span className="link active">{sceneKey}</span>{" "}
              <span className="muted small">новая</span>
            </li>
          )}
        </ul>
        <NewScene taken={context.scenes.map((s) => s.key)} onCreate={open} />
        {problems && (problems.errors.length > 0 || problems.warnings.length > 0) && (
          <details className="title-problems">
            <summary>Проблемы тайтла: {problems.errors.length + problems.warnings.length}</summary>
            <ul className="problems">
              {[...problems.errors, ...problems.warnings].map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </details>
        )}
      </nav>
      {sceneKey ? (
        <SceneEditor
          key={sceneKey}
          slug={slug}
          sceneKey={sceneKey}
          exists={exists}
          context={context}
          onDirty={(value) => (dirty.current = value)}
          onSaved={(next) => {
            setProblems(next);
            reload();
          }}
          onDeleted={(next) => {
            setProblems(next);
            dirty.current = false;
            reload();
            onOpen(null);
          }}
        />
      ) : (
        <div className="scene-empty muted">
          <p>Выберите сцену слева или создайте новую.</p>
          <p className="small">
            Подсказки: после <code>#</code> — теги, после <code>-&gt;</code> — узлы, в начале строки
            — персонажи. Ctrl+S — сохранить, F12 — к узлу, Ctrl+Shift+O — список узлов.
          </p>
        </div>
      )}
    </div>
  );
}

function NewScene({ taken, onCreate }: { taken: string[]; onCreate(key: string): void }) {
  const [value, setValue] = useState("");
  const valid = KEY.test(value) && !taken.includes(value);
  const create = () => {
    onCreate(value);
    setValue("");
  };
  return (
    <span className="add-flag">
      <input
        value={value}
        placeholder="новая_сцена"
        aria-label="Ключ новой сцены"
        onChange={(e) => setValue(e.target.value.trim())}
        onKeyDown={(e) => e.key === "Enter" && valid && create()}
      />
      <button type="button" className="small secondary" disabled={!valid} onClick={create}>
        +
      </button>
    </span>
  );
}

function SceneEditor({
  slug,
  sceneKey,
  exists,
  context,
  onDirty,
  onSaved,
  onDeleted,
}: {
  slug: string;
  sceneKey: string;
  exists: boolean;
  context: SceneContext;
  onDirty(dirty: boolean): void;
  onSaved(problems: Problems): void;
  onDeleted(problems: Problems): void;
}) {
  const url = `/titles/${slug}/scenes/${sceneKey}`;
  // Сцена, которой ещё нет на сервере, начинается с шаблона — без запроса.
  const [loaded, setLoaded] = useState<Loaded | "error" | null>(() =>
    exists ? null : { source: template(context), updatedAt: null },
  );
  const [source, setSource] = useState(() => (exists ? "" : template(context)));
  /** Время версии на сервере, от которой идут правки; null — сцены там ещё нет. */
  const [savedAt, setSavedAt] = useState<string | null>(null);
  /** null — сцена ещё ни разу не проверялась. */
  const [diagnostics, setDiagnostics] = useState<Diagnostic[] | null>(null);
  const [json, setJson] = useState<string | null>(null);
  const [cursorLine, setCursorLine] = useState(1);
  const [dirty, setDirty] = useState(!exists);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const host = useRef<HTMLDivElement>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const savedVersion = useRef(0);
  const checked = useRef(false);
  const save = useRef<(overwrite?: string | null) => void>(() => {});

  useEffect(() => {
    if (!exists) return;
    request<{ source: string; updated_at: string }>("GET", url).then(
      (scene) => {
        setLoaded({ source: scene.source, updatedAt: scene.updated_at });
        setSource(scene.source);
        setSavedAt(scene.updated_at);
      },
      () => setLoaded("error"),
    );
    // Сцена грузится один раз: после сохранения список обновится, а текст — уже в редакторе.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  // Редактор создаётся, когда текст загружен, и живёт, пока открыта эта сцена.
  useEffect(() => {
    if (!loaded || loaded === "error" || !host.current) return;
    registerInk();
    const model = monaco.editor.createModel(
      loaded.source,
      LANGUAGE,
      monaco.Uri.parse(`scene:///${slug}/${sceneKey}.ink`),
    );
    savedVersion.current = loaded.updatedAt ? model.getAlternativeVersionId() : -1;
    const editor = monaco.editor.create(host.current, {
      model,
      theme: THEME,
      automaticLayout: true,
      minimap: { enabled: false },
      wordWrap: "on",
      fontSize: 14,
      lineHeight: 22,
      tabSize: 4,
      scrollBeyondLastLine: false,
      fixedOverflowWidgets: true,
      // Подсказки только наши: слова из текста сцены мешают писать прозу.
      wordBasedSuggestions: "off",
      quickSuggestions: { other: true, comments: false, strings: true },
      // Кириллица в тексте — не «похожие символы», подсвечивать её не нужно.
      unicodeHighlight: { ambiguousCharacters: false, invisibleCharacters: false },
    });
    editorRef.current = editor;

    const changed = editor.onDidChangeModelContent(() => {
      setSource(model.getValue());
      const isDirty = model.getAlternativeVersionId() !== savedVersion.current;
      setDirty(isDirty);
      onDirty(isDirty);
      setMessage(null);
    });
    const moved = editor.onDidChangeCursorPosition((e) => setCursorLine(e.position.lineNumber));
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => save.current());
    editor.focus();
    return () => {
      changed.dispose();
      moved.dispose();
      editor.dispose();
      model.dispose();
      editorRef.current = null;
    };
    // Пропсы-колбэки не пересоздают редактор.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, slug, sceneKey]);

  // Компиляция с задержкой после ввода; маркеры — в строках редактора.
  useEffect(() => {
    if (!source) return;
    let cancelled = false;
    const timer = setTimeout(
      () => {
        compile(source, context.registry).then((result) => {
          if (cancelled) return;
          checked.current = true;
          setDiagnostics(result.diagnostics);
          if (result.scene) setJson(result.scene.json);
          const model = editorRef.current?.getModel();
          if (!model) return;
          monaco.editor.setModelMarkers(
            model,
            "ink",
            result.diagnostics.map((d) => {
              const line = Math.min(d.line ?? 1, model.getLineCount());
              return {
                severity:
                  d.severity === "error"
                    ? monaco.MarkerSeverity.Error
                    : monaco.MarkerSeverity.Warning,
                message: d.message,
                startLineNumber: line,
                startColumn: model.getLineFirstNonWhitespaceColumn(line) || 1,
                endLineNumber: line,
                endColumn: model.getLineMaxColumn(line),
              };
            }),
          );
        });
        // Первый раз — сразу, дальше — когда ввод затих.
      },
      checked.current ? 350 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [source, context.registry]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const errors = diagnostics?.filter((d) => d.severity === "error").length ?? 0;
  const warnings = (diagnostics?.length ?? 0) - errors;

  const saveScene = async (overwrite?: string | null) => {
    const editor = editorRef.current;
    const model = editor?.getModel();
    if (!model || busy) return;
    setBusy(true);
    setMessage(null);
    const version = model.getAlternativeVersionId();
    try {
      const result = await request<{ updated_at: string; problems: Problems }>("PUT", url, {
        source: model.getValue(),
        base: overwrite === undefined ? savedAt : overwrite,
      });
      setSavedAt(result.updated_at);
      savedVersion.current = version;
      const isDirty = model.getAlternativeVersionId() !== version;
      setDirty(isDirty);
      onDirty(isDirty);
      setConflict(null);
      setMessage({
        ok: true,
        text: errors
          ? `Сохранено, но в сцене ошибок: ${errors} — сборка её не пропустит.`
          : "Сохранено. Игроки увидят после сборки и публикации.",
      });
      onSaved(result.problems);
    } catch (error) {
      if (error instanceof StudioError && error.status === 409) {
        setConflict(error.detail as Conflict);
      } else {
        setMessage({ ok: false, text: describe(error).join("; ") });
      }
    } finally {
      setBusy(false);
    }
  };

  // Ctrl+S в редакторе вызывает свежую версию сохранения.
  useLayoutEffect(() => {
    save.current = saveScene;
  });

  const reloadFromServer = async () => {
    const editor = editorRef.current;
    if (!editor) return;
    try {
      const scene = await request<{ source: string; updated_at: string }>("GET", url);
      setSavedAt(scene.updated_at);
      editor.getModel()?.setValue(scene.source);
      savedVersion.current = editor.getModel()?.getAlternativeVersionId() ?? 0;
      setDirty(false);
      onDirty(false);
      setConflict(null);
    } catch (error) {
      setMessage({ ok: false, text: describe(error).join("; ") });
    }
  };

  const remove = async () => {
    if (!window.confirm(`Удалить сцену ${sceneKey}? События, которые её запускают, сломаются.`)) {
      return;
    }
    try {
      const result = await request<{ problems: Problems }>("DELETE", url);
      onDeleted(result.problems);
    } catch (error) {
      setMessage({ ok: false, text: describe(error).join("; ") });
    }
  };

  const reveal = (line: number | null) => {
    const editor = editorRef.current;
    if (!editor || !line) return;
    editor.revealLineInCenter(line);
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.focus();
  };

  const nodes = useMemo(() => outline(source), [source]);
  const sceneFlags = useMemo(
    () => [...source.matchAll(SCENE_FLAG)].map((m) => (m[1] ?? m[2])!),
    [source],
  );

  if (loaded === "error") return <p className="error">Не удалось загрузить сцену.</p>;

  return (
    <div className="scene-workspace">
      <div className="scene-main">
        <div className="scene-bar">
          <strong>{sceneKey}</strong>
          <span
            className={
              diagnostics === null
                ? "muted small"
                : errors
                  ? "error small"
                  : warnings
                    ? "warning small"
                    : "ok small"
            }
          >
            {loaded === null
              ? "загружаем…"
              : diagnostics === null
                ? "проверяем…"
                : errors
                  ? `ошибок: ${errors}`
                  : warnings
                    ? `предупреждений: ${warnings}`
                    : "без ошибок"}
          </span>
          <button
            type="button"
            className="small"
            disabled={!dirty || busy}
            onClick={() => save.current()}
          >
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
          {savedAt !== null && (
            <button type="button" className="small secondary" onClick={remove}>
              Удалить
            </button>
          )}
          {message && (
            <span className={message.ok ? "ok small" : "error small"}>{message.text}</span>
          )}
        </div>
        {conflict && (
          <div className="card conflict">
            <p>
              {conflict.exists
                ? `Сцену уже изменил${conflict.updated_by ? ` ${conflict.updated_by}` : "и"}${
                    conflict.updated_at
                      ? ` в ${new Date(conflict.updated_at).toLocaleTimeString("ru")}`
                      : ""
                  }. Ваши правки не сохранены.`
                : "Сцену удалили, пока вы её правили."}
            </p>
            <div className="actions">
              <button
                type="button"
                className="small"
                onClick={() => save.current(conflict.updated_at)}
              >
                {conflict.exists ? "Сохранить поверх" : "Создать заново"}
              </button>
              {conflict.exists && (
                <button type="button" className="small secondary" onClick={reloadFromServer}>
                  Загрузить их версию (мои правки пропадут)
                </button>
              )}
            </div>
          </div>
        )}
        <div ref={host} className="scene-editor" />
        {diagnostics && diagnostics.length > 0 && (
          <ul className="diagnostics">
            {diagnostics.map((d, i) => (
              <li key={i} className={d.severity}>
                <button type="button" className="link" onClick={() => reveal(d.line)}>
                  {d.line ? `строка ${d.line}` : "сцена"}
                </button>{" "}
                {d.message}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Preview
        slug={slug}
        context={context}
        json={json}
        checked={diagnostics !== null}
        nodes={nodes}
        cursor={nodeAt(nodes, cursorLine)}
        sceneFlags={sceneFlags}
      />
    </div>
  );
}

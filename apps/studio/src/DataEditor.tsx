import { useCallback, useEffect, useMemo, useState } from "react";

import { problems as describe, request } from "./api";
import { clean, SchemaForm, type Refs, type Schema } from "./SchemaForm";

// Данные тайтла по сущностям: разделы слева, форма справа. Ошибки полей сущности не дают
// сохранить; ошибки ссылок по всему тайтлу видны сверху (сборка с ними не пройдёт).

const SECTIONS: { kind: string; label: string; single?: boolean }[] = [
  { kind: "config", label: "Настройки", single: true },
  { kind: "characters", label: "Персонажи" },
  { kind: "locations", label: "Локации" },
  { kind: "map", label: "Карта", single: true },
  { kind: "activities", label: "Занятия" },
  { kind: "items", label: "Предметы" },
  { kind: "quests", label: "Квесты" },
  { kind: "events", label: "События" },
  { kind: "achievements", label: "Достижения" },
];
const MAIN = "main";

type Obj = Record<string, unknown>;
type Sections = Record<string, Obj | null>;

interface Documents {
  sections: Sections;
  scenes: string[];
  problems: { errors: string[]; warnings: string[] };
}

const names = (section: Obj | null | undefined): Record<string, string> =>
  Object.fromEntries(
    Object.entries(section ?? {}).map(([key, value]) => [
      key,
      typeof (value as Obj)?.name === "string" ? ((value as Obj).name as string) : key,
    ]),
  );

/** Ключи для выпадающих списков формы — из текущих данных тайтла. */
function buildRefs(docs: Documents): Refs {
  const config = (docs.sections.config ?? {}) as Obj;
  const time = (config.time ?? {}) as Obj;
  const slots = Array.isArray(time.slots) ? (time.slots as Obj[]) : [];
  const week = Array.isArray(time.week) ? (time.week as string[]) : [];
  return {
    locations: names(docs.sections.locations),
    characters: names(docs.sections.characters),
    items: names(docs.sections.items),
    activities: names(docs.sections.activities),
    quests: names(docs.sections.quests),
    scenes: Object.fromEntries(docs.scenes.map((key) => [key, key])),
    slots: Object.fromEntries(
      slots
        .filter((s) => typeof s.id === "string")
        .map((s) => [s.id as string, String(s.name ?? s.id)]),
    ),
    weekdays: Object.fromEntries(week.map((day) => [day, day])),
    resources: names((config.resources ?? {}) as Obj),
  };
}

export function DataEditor({ slug, editor }: { slug: string; editor: boolean }) {
  const base = `/titles/${slug}/documents`;
  const [schemas, setSchemas] = useState<Record<string, Schema> | null>(null);
  const [docs, setDocs] = useState<Documents | null>(null);
  const [kind, setKind] = useState("config");
  const [key, setKey] = useState<string | null>(MAIN);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    Promise.all([
      request<Record<string, Schema>>("GET", "/schema"),
      request<Documents>("GET", base),
    ]).then(
      ([s, d]) => {
        setSchemas(s);
        setDocs(d);
      },
      () => setFailed(true),
    );
  }, [base]);

  const refs = useMemo(() => (docs ? buildRefs(docs) : {}), [docs]);

  const select = (nextKind: string, nextKey: string | null) => {
    setKind(nextKind);
    setKey(nextKey);
  };

  const onSaved = useCallback(
    (savedKind: string, savedKey: string, data: Obj | null, problems: Documents["problems"]) => {
      setDocs((current) => {
        if (!current) return current;
        const sections = { ...current.sections };
        if (SECTIONS.find((s) => s.kind === savedKind)?.single) {
          sections[savedKind] = data;
        } else {
          const section = { ...(sections[savedKind] ?? {}) };
          if (data === null) delete section[savedKey];
          else section[savedKey] = data;
          sections[savedKind] = section;
        }
        return { ...current, sections, problems };
      });
    },
    [],
  );

  if (failed) return <p className="error">Не удалось загрузить данные тайтла.</p>;
  if (!schemas || !docs) return <p className="muted">Загружаем…</p>;

  const section = SECTIONS.find((s) => s.kind === kind)!;
  const entityKey = section.single ? MAIN : key;
  const current = section.single
    ? (docs.sections[kind] ?? {})
    : entityKey
      ? ((docs.sections[kind] ?? {})[entityKey] as Obj | undefined)
      : undefined;

  return (
    <div className="data">
      <Problems problems={docs.problems} />
      <div className="data-layout">
        <nav className="data-nav">
          {SECTIONS.map((s) => {
            const entries = Object.entries(names(docs.sections[s.kind]));
            return (
              <div key={s.kind} className="data-section">
                <button
                  type="button"
                  className={`link section-link${kind === s.kind && s.single ? " active" : ""}`}
                  onClick={() => select(s.kind, s.single ? MAIN : null)}
                >
                  {s.label}
                  {!s.single && <span className="muted small"> {entries.length}</span>}
                </button>
                {!s.single && kind === s.kind && (
                  <ul>
                    {entries.map(([k, label]) => (
                      <li key={k}>
                        <button
                          type="button"
                          className={`link${key === k ? " active" : ""}`}
                          onClick={() => select(s.kind, k)}
                        >
                          {label}
                        </button>
                      </li>
                    ))}
                    {editor && (
                      <li>
                        <NewKey
                          taken={docs.sections[s.kind] ?? {}}
                          onCreate={(k) => select(s.kind, k)}
                        />
                      </li>
                    )}
                  </ul>
                )}
              </div>
            );
          })}
        </nav>
        <section className="data-form">
          {entityKey ? (
            <Entity
              key={`${kind}:${entityKey}`}
              base={base}
              kind={kind}
              entityKey={entityKey}
              title={section.single ? section.label : `${section.label}: ${entityKey}`}
              schema={schemas[kind]!}
              value={current ?? null}
              refs={refs}
              editor={editor}
              single={Boolean(section.single)}
              onSaved={onSaved}
              onDeleted={() => select(kind, null)}
            />
          ) : (
            <p className="muted">Выберите запись слева{editor ? " или добавьте новую" : ""}.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function Problems({ problems }: { problems: Documents["problems"] }) {
  if (!problems.errors.length && !problems.warnings.length) {
    return <p className="ok">Ошибок в данных нет. Сцены проверит сборка.</p>;
  }
  return (
    <details className="card problems-card" open={problems.errors.length > 0}>
      <summary>
        Ошибок: {problems.errors.length}, предупреждений: {problems.warnings.length} — сборка с
        ошибками не пройдёт
      </summary>
      <ul className="problems error">
        {problems.errors.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <ul className="problems warning">
        {problems.warnings.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </details>
  );
}

function NewKey({ taken, onCreate }: { taken: Obj; onCreate(key: string): void }) {
  const [value, setValue] = useState("");
  const valid = /^[a-z][a-z0-9_]*$/.test(value) && !(value in taken);
  return (
    <span className="add-flag">
      <input
        value={value}
        placeholder="новый_ключ"
        onChange={(e) => setValue(e.target.value.trim())}
        onKeyDown={(e) => e.key === "Enter" && valid && (onCreate(value), setValue(""))}
      />
      <button
        type="button"
        className="small secondary"
        disabled={!valid}
        onClick={() => {
          onCreate(value);
          setValue("");
        }}
      >
        +
      </button>
    </span>
  );
}

function Entity({
  base,
  kind,
  entityKey,
  title,
  schema,
  value,
  refs,
  editor,
  single,
  onSaved,
  onDeleted,
}: {
  base: string;
  kind: string;
  entityKey: string;
  title: string;
  schema: Schema;
  value: Obj | null;
  refs: Refs;
  editor: boolean;
  single: boolean;
  onSaved(kind: string, key: string, data: Obj | null, problems: Documents["problems"]): void;
  onDeleted(): void;
}) {
  const [draft, setDraft] = useState<Obj>(() => structuredClone(value ?? {}));
  const [dirty, setDirty] = useState(value === null);
  const [errors, setErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const url = `${base}/${kind}/${entityKey}`;

  const save = async () => {
    setBusy(true);
    setErrors([]);
    setSaved(false);
    const data = clean(draft, schema, { root: schema }) as Obj;
    try {
      const result = await request<{ problems: Documents["problems"] }>("PUT", url, { data });
      onSaved(kind, entityKey, data, result.problems);
      setDraft(data);
      setDirty(false);
      setSaved(true);
    } catch (error) {
      setErrors(describe(error));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (
      !window.confirm(`Удалить ${entityKey}? Если ключ уже у игроков, публикация это остановит.`)
    ) {
      return;
    }
    try {
      const result = await request<{ problems: Documents["problems"] }>("DELETE", url);
      onSaved(kind, entityKey, null, result.problems);
      onDeleted();
    } catch (error) {
      setErrors(describe(error));
    }
  };

  return (
    <div className="card">
      <h2>{title}</h2>
      {value === null && <p className="muted">Новая запись: заполните и сохраните.</p>}
      <fieldset disabled={!editor} className="plain">
        <SchemaForm
          schema={schema}
          value={draft}
          refs={refs}
          onChange={(next) => {
            setDraft(next);
            setDirty(true);
            setSaved(false);
          }}
        />
      </fieldset>
      {errors.length > 0 && (
        <ul className="problems error">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {editor && (
        <div className="actions sticky-actions">
          <button type="button" disabled={!dirty || busy} onClick={save}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
          {saved && <span className="ok">Сохранено. Игроки увидят после сборки и публикации.</span>}
          {!single && value !== null && (
            <button type="button" className="secondary" onClick={remove}>
              Удалить
            </button>
          )}
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import YAML from "yaml";

// Форма по JSON Schema из Pydantic (apps/api/.../game/schema.py). Разметка в схеме:
// title — подпись, description — подсказка, x-ref — выпадающий список ключей раздела,
// x-key-ref — то же для ключей словаря, x-yaml — свободная структура (условия, эффекты),
// x-cost — цена занятия (части дня и ресурсы тайтла).

export interface Schema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  additionalProperties?: Schema | boolean;
  /** Словарь с ключами-идентификаторами: {"^[a-z]…$": схема значения}. */
  patternProperties?: Record<string, Schema>;
  anyOf?: Schema[];
  enum?: unknown[];
  const?: unknown;
  $ref?: string;
  $defs?: Record<string, Schema>;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  "x-ref"?: string;
  "x-key-ref"?: string;
  "x-yaml"?: boolean;
  "x-cost"?: boolean;
}

/** Ключи разделов для выпадающих списков: раздел → ключ → подпись. */
export type Refs = Record<string, Record<string, string>>;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

interface Ctx {
  root: Schema;
  refs: Refs;
}

function resolve(schema: Schema, ctx: Ctx): Schema {
  if (!schema.$ref) return schema;
  const name = schema.$ref.split("/").pop()!;
  const target = ctx.root.$defs?.[name] ?? {};
  // Подпись и подсказка поля важнее описания модели.
  return { ...target, title: schema.title ?? target.title, description: schema.description };
}

/** «X или null» → X и признак, что поле можно оставить пустым. */
function unwrap(schema: Schema, ctx: Ctx): { schema: Schema; nullable: boolean } {
  const resolved = resolve(schema, ctx);
  const options = resolved.anyOf;
  if (!options) return { schema: resolved, nullable: false };
  const rest = options.filter((o) => o.type !== "null");
  const nullable = rest.length < options.length;
  if (rest.length === 1) {
    const inner = resolve(rest[0]!, ctx);
    return {
      schema: {
        ...inner,
        title: resolved.title,
        description: resolved.description,
        "x-ref": resolved["x-ref"] ?? inner["x-ref"],
        "x-yaml": resolved["x-yaml"] ?? inner["x-yaml"],
      },
      nullable,
    };
  }
  return { schema: { ...resolved, anyOf: rest }, nullable };
}

/** Убирает пустые необязательные значения, чтобы в данных не копились null и {}. */
export function clean(value: unknown, schema: Schema, ctx: { root: Schema }): unknown {
  const resolved = resolve(schema, { root: ctx.root, refs: {} });
  if (Array.isArray(value)) {
    const items = resolved.items ?? unwrap(resolved, { root: ctx.root, refs: {} }).schema.items;
    return value.map((v) => (items ? clean(v, items, ctx) : v));
  }
  if (!isObj(value)) return value;
  const { schema: inner } = unwrap(resolved, { root: ctx.root, refs: {} });
  const result: Obj = {};
  for (const [key, v] of Object.entries(value)) {
    const fieldSchema = inner.properties?.[key];
    const required = inner.required?.includes(key) ?? false;
    const cleaned = fieldSchema ? clean(v, fieldSchema, ctx) : v;
    const empty =
      cleaned === undefined ||
      cleaned === null ||
      cleaned === "" ||
      (Array.isArray(cleaned) && cleaned.length === 0) ||
      (isObj(cleaned) && Object.keys(cleaned).length === 0);
    if (empty && !required) continue;
    result[key] = cleaned;
  }
  return result;
}

export function SchemaForm({
  schema,
  value,
  refs,
  onChange,
}: {
  schema: Schema;
  value: Obj;
  refs: Refs;
  onChange(value: Obj): void;
}) {
  const ctx = { root: schema, refs };
  return <ObjectFields schema={schema} value={value} ctx={ctx} onChange={onChange} />;
}

function ObjectFields({
  schema,
  value,
  ctx,
  onChange,
}: {
  schema: Schema;
  value: Obj;
  ctx: Ctx;
  onChange(value: Obj): void;
}) {
  const properties = schema.properties ?? {};
  return (
    <div className="form">
      {Object.entries(properties).map(([key, field]) => (
        <Field
          key={key}
          name={key}
          schema={field}
          required={schema.required?.includes(key) ?? false}
          value={value[key]}
          ctx={ctx}
          onChange={(next) => onChange({ ...value, [key]: next })}
        />
      ))}
    </div>
  );
}

function Label({ schema, name, required }: { schema: Schema; name: string; required?: boolean }) {
  return (
    <span className="field-label">
      {schema.title ?? name}
      {required && <span className="required"> *</span>}
      {schema.description && <span className="hint"> — {schema.description}</span>}
    </span>
  );
}

function Field({
  name,
  schema: raw,
  required,
  value,
  ctx,
  onChange,
}: {
  name: string;
  schema: Schema;
  required: boolean;
  value: unknown;
  ctx: Ctx;
  onChange(value: unknown): void;
}) {
  const { schema, nullable } = unwrap(raw, ctx);
  const current = value === undefined ? undefined : value;
  const resolvedRaw = resolve(raw, ctx);
  const fallback = resolvedRaw.default ?? schema.default;
  const placeholder =
    fallback === undefined || fallback === null || typeof fallback === "object"
      ? undefined
      : String(fallback);

  if (schema["x-yaml"]) {
    return (
      <div className="field wide">
        <Label schema={schema} name={name} required={required} />
        <YamlField value={current} onChange={onChange} />
      </div>
    );
  }

  if (schema["x-cost"]) {
    const cost = isObj(current) ? current : {};
    return (
      <fieldset className="field wide">
        <legend>
          <Label schema={schema} name={name} />
        </legend>
        <div className="row">
          <label>
            Частей дня
            <input
              type="number"
              min={0}
              value={typeof cost.slots === "number" ? cost.slots : 1}
              onChange={(e) => onChange({ ...cost, slots: Number(e.target.value) })}
            />
          </label>
          {Object.entries(ctx.refs.resources ?? {}).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min={0}
                value={typeof cost[key] === "number" ? (cost[key] as number) : ""}
                onChange={(e) => {
                  const next = { ...cost };
                  if (e.target.value === "" || Number(e.target.value) === 0) delete next[key];
                  else next[key] = Number(e.target.value);
                  onChange(next);
                }}
              />
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (schema.enum) {
    return (
      <label className="field">
        <Label schema={schema} name={name} required={required} />
        <select
          value={current === undefined || current === null ? "" : String(current)}
          onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
        >
          {(nullable || !required || current === undefined) && <option value="">—</option>}
          {schema.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (schema.anyOf) {
    // Несколько вариантов типа (число или "max"): текстом, число распознаём.
    return (
      <label className="field">
        <Label schema={schema} name={name} required={required} />
        <input
          value={current === undefined || current === null ? "" : String(current)}
          onChange={(e) => {
            const text = e.target.value.trim();
            onChange(text === "" ? undefined : /^-?\d+$/.test(text) ? Number(text) : text);
          }}
        />
      </label>
    );
  }

  const ref = schema["x-ref"];
  switch (schema.type) {
    case "string":
      if (ref) {
        const options = ctx.refs[ref] ?? {};
        return (
          <label className="field">
            <Label schema={schema} name={name} required={required} />
            <select
              value={typeof current === "string" ? current : ""}
              onChange={(e) => onChange(e.target.value || undefined)}
            >
              <option value="">—</option>
              {typeof current === "string" && current && !(current in options) && (
                <option value={current}>{current} (нет такого)</option>
              )}
              {Object.entries(options).map(([key, label]) => (
                <option key={key} value={key}>
                  {label === key ? key : `${label} (${key})`}
                </option>
              ))}
            </select>
          </label>
        );
      }
      return (
        <label className="field">
          <Label schema={schema} name={name} required={required} />
          <input
            value={typeof current === "string" ? current : ""}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
          />
        </label>
      );
    case "integer":
    case "number":
      return (
        <label className="field">
          <Label schema={schema} name={name} required={required} />
          <input
            type="number"
            step={schema.type === "integer" ? 1 : "any"}
            min={schema.minimum}
            max={schema.maximum}
            value={typeof current === "number" ? current : ""}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
          />
        </label>
      );
    case "boolean":
      return (
        <label className="field check">
          <input
            type="checkbox"
            checked={typeof current === "boolean" ? current : Boolean(schema.default)}
            onChange={(e) => onChange(e.target.checked)}
          />
          <Label schema={schema} name={name} />
        </label>
      );
    case "array":
      return (
        <ArrayField
          name={name}
          schema={schema}
          required={required}
          value={Array.isArray(current) ? current : []}
          ctx={ctx}
          onChange={onChange}
        />
      );
    case "object":
      if (schema.properties && nullable && !isObj(current)) {
        return (
          <div className="field wide">
            <Label schema={schema} name={name} />
            <button type="button" className="small secondary" onClick={() => onChange({})}>
              + Задать
            </button>
          </div>
        );
      }
      if (schema.properties) {
        return (
          <fieldset className="field wide">
            <legend>
              <Label schema={schema} name={name} required={required} />
              {nullable && (
                <button type="button" className="link small" onClick={() => onChange(undefined)}>
                  {" "}
                  убрать
                </button>
              )}
            </legend>
            <ObjectFields
              schema={schema}
              value={isObj(current) ? current : {}}
              ctx={ctx}
              onChange={onChange}
            />
          </fieldset>
        );
      }
      return (
        <DictField
          name={name}
          schema={schema}
          value={isObj(current) ? current : {}}
          ctx={ctx}
          onChange={onChange}
        />
      );
    default:
      return (
        <div className="field wide">
          <Label schema={schema} name={name} required={required} />
          <YamlField value={current} onChange={onChange} />
        </div>
      );
  }
}

function ArrayField({
  name,
  schema,
  required,
  value,
  ctx,
  onChange,
}: {
  name: string;
  schema: Schema;
  required: boolean;
  value: unknown[];
  ctx: Ctx;
  onChange(value: unknown): void;
}) {
  const items = resolve(schema.items ?? {}, ctx);
  const ref = schema["x-ref"] ?? items["x-ref"];

  if (items.type === "string" && ref) {
    const options = ctx.refs[ref] ?? {};
    return (
      <fieldset className="field wide">
        <legend>
          <Label schema={schema} name={name} required={required} />
        </legend>
        <div className="checks">
          {Object.entries(options).map(([key, label]) => (
            <label key={key} className="check">
              <input
                type="checkbox"
                checked={value.includes(key)}
                onChange={(e) =>
                  onChange(
                    e.target.checked
                      ? Object.keys(options).filter((k) => k === key || value.includes(k))
                      : value.filter((v) => v !== key),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (items.type === "string" || items.type === "integer") {
    return (
      <label className="field wide">
        <Label schema={schema} name={name} required={required} />
        <ListInput value={value} onChange={onChange} />
      </label>
    );
  }

  return (
    <fieldset className="field wide">
      <legend>
        <Label schema={schema} name={name} required={required} />
      </legend>
      {value.map((item, index) => (
        <div key={index} className="list-item">
          <ObjectFields
            schema={items}
            value={isObj(item) ? item : {}}
            ctx={ctx}
            onChange={(next) => onChange(value.map((v, i) => (i === index ? next : v)))}
          />
          <div className="list-actions">
            <button
              type="button"
              className="small secondary"
              disabled={index === 0}
              onClick={() => {
                const next = [...value];
                [next[index - 1], next[index]] = [next[index], next[index - 1]];
                onChange(next);
              }}
            >
              ↑
            </button>
            <button
              type="button"
              className="small secondary"
              onClick={() => onChange(value.filter((_, i) => i !== index))}
            >
              Удалить
            </button>
          </div>
        </div>
      ))}
      <button type="button" className="small secondary" onClick={() => onChange([...value, {}])}>
        + Добавить
      </button>
    </fieldset>
  );
}

/** Список строк через запятую; правится текстом, разбирается при уходе с поля. */
function ListInput({ value, onChange }: { value: unknown[]; onChange(value: unknown): void }) {
  const [text, setText] = useState(value.join(", "));
  return (
    <input
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() =>
        onChange(
          text
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean),
        )
      }
    />
  );
}

function DictField({
  name,
  schema,
  value,
  ctx,
  onChange,
}: {
  name: string;
  schema: Schema;
  value: Obj;
  ctx: Ctx;
  onChange(value: unknown): void;
}) {
  const values =
    Object.values(schema.patternProperties ?? {})[0] ??
    (typeof schema.additionalProperties === "object" ? schema.additionalProperties : {});
  const valueSchema = resolve(values, ctx);
  const keyRef = schema["x-key-ref"];
  const options = keyRef ? (ctx.refs[keyRef] ?? {}) : null;
  const [newKey, setNewKey] = useState("");

  // Произвольный словарь без схемы значений — проще YAML.
  if (!valueSchema.type && !valueSchema.properties) {
    return (
      <div className="field wide">
        <Label schema={schema} name={name} />
        <YamlField value={value} onChange={onChange} />
      </div>
    );
  }

  const add = (key: string) => {
    if (!key || key in value) return;
    onChange({ ...value, [key]: valueSchema.properties ? {} : 0 });
    setNewKey("");
  };

  return (
    <fieldset className="field wide">
      <legend>
        <Label schema={schema} name={name} />
      </legend>
      {Object.entries(value).map(([key, item]) => (
        <div key={key} className="list-item">
          <div className="dict-key">
            <code>{options?.[key] ? `${options[key]} (${key})` : key}</code>
            <button
              type="button"
              className="small secondary"
              onClick={() => {
                const next = { ...value };
                delete next[key];
                onChange(next);
              }}
            >
              Удалить
            </button>
          </div>
          {valueSchema.properties ? (
            <ObjectFields
              schema={valueSchema}
              value={isObj(item) ? item : {}}
              ctx={ctx}
              onChange={(next) => onChange({ ...value, [key]: next })}
            />
          ) : (
            <input
              type="number"
              value={typeof item === "number" ? item : ""}
              onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
            />
          )}
        </div>
      ))}
      <div className="row">
        {options ? (
          <select value={newKey} onChange={(e) => setNewKey(e.target.value)}>
            <option value="">— добавить —</option>
            {Object.entries(options)
              .filter(([key]) => !(key in value))
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        ) : (
          <input
            value={newKey}
            placeholder="ключ латиницей"
            onChange={(e) => setNewKey(e.target.value.trim())}
          />
        )}
        <button
          type="button"
          className="small secondary"
          disabled={!/^[a-z][a-z0-9_]*$/.test(newKey)}
          onClick={() => add(newKey)}
        >
          + Добавить
        </button>
      </div>
    </fieldset>
  );
}

/** Условия и эффекты: YAML-блок, разбирается при уходе с поля. */
function YamlField({ value, onChange }: { value: unknown; onChange(value: unknown): void }) {
  const initial =
    value === undefined || value === null || (isObj(value) && Object.keys(value).length === 0)
      ? ""
      : YAML.stringify(value).trimEnd();
  const [text, setText] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      <textarea
        className="yaml"
        rows={Math.max(2, text.split("\n").length)}
        value={text}
        spellCheck={false}
        placeholder="например: affection.anna: { gte: 10 }"
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (!text.trim()) {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            onChange(YAML.parse(text));
            setError(null);
          } catch (e) {
            setError(e instanceof Error ? e.message.split("\n")[0]! : "ошибка YAML");
          }
        }}
      />
      {error && <span className="error small">{error}</span>}
    </>
  );
}

import type { Command, Effect, Position, SceneChoice, SceneRunner, Step } from "@storymaker/engine";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AudioPlayer } from "./audio.ts";
import "./vn.css";

export interface AssetResolver {
  background(key: string): string | undefined;
  sprite(character: string, emotion: string): string | undefined;
  audio?(kind: "music" | "sfx", key: string): string | undefined;
}

export interface CharacterInfo {
  name: string;
  color?: string;
}

export interface VnSceneProps {
  runner: SceneRunner;
  assets: AssetResolver;
  /** Имена и цвета персонажей по ключам. */
  characters: Record<string, CharacterInfo>;
  /** Имя протагониста для реплик `me:`. */
  playerName?: string;
  /** Миллисекунд на символ; 0 — без печатного эффекта. */
  typingDelay?: number;
  onEnd(effects: Effect[]): void;
  /** Подтверждение платного выбора (списание кристаллов). Без обработчика выбор разрешён. */
  onPremiumChoice?(choice: SceneChoice): Promise<boolean>;
}

interface StageCharacter {
  emotion: string;
  position: Position;
}

interface Stage {
  background: string | null;
  characters: Record<string, StageCharacter>;
}

type Shown = Extract<Step, { type: "line" } | { type: "choices" }> | null;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Сцена стартует один раз на runner: StrictMode монтирует компонент дважды,
// а повторный next() проглотил бы первую реплику.
const started = new WeakSet<SceneRunner>();

export function VnScene({
  runner,
  assets,
  characters,
  playerName = "Я",
  typingDelay = 30,
  onEnd,
  onPremiumChoice,
}: VnSceneProps) {
  const [stage, setStage] = useState<Stage>({ background: null, characters: {} });
  const [shown, setShown] = useState<Shown>(null);
  const [typed, setTyped] = useState(0);
  const [fx, setFx] = useState<"shake" | "flash" | null>(null);
  const audio = useRef<AudioPlayer | null>(null);
  const busy = useRef(false);
  const alive = useRef(true);
  // Свежие пропсы без перезапуска сцены, если родитель передал новые функции.
  const props = useRef({ assets, onEnd });
  useLayoutEffect(() => {
    props.current = { assets, onEnd };
  });

  const apply = useCallback(async (commands: Command[]) => {
    const { assets } = props.current;
    for (const command of commands) {
      switch (command.type) {
        case "bg":
          setStage((s) => ({ ...s, background: command.key }));
          break;
        case "show":
          setStage((s) => ({
            ...s,
            characters: {
              ...s.characters,
              [command.character]: {
                emotion: command.emotion,
                position: command.position ?? s.characters[command.character]?.position ?? "center",
              },
            },
          }));
          break;
        case "hide":
          setStage((s) => {
            const rest = { ...s.characters };
            delete rest[command.character];
            return { ...s, characters: rest };
          });
          break;
        case "music":
          audio.current?.music(command.key && assets.audio?.("music", command.key));
          break;
        case "sfx": {
          const url = assets.audio?.("sfx", command.key);
          if (url) {
            audio.current?.sfx(url);
          }
          break;
        }
        case "wait":
          await delay(command.seconds * 1000);
          break;
        case "fx":
          setFx(command.name);
          setTimeout(() => alive.current && setFx(null), command.name === "shake" ? 450 : 300);
          break;
      }
    }
  }, []);

  const advance = useCallback(async () => {
    if (busy.current) {
      return;
    }
    busy.current = true;
    try {
      const step = runner.next();
      await apply(step.commands);
      if (!alive.current) {
        return;
      }
      if (step.type === "end") {
        setShown(null);
        audio.current?.music(null);
        props.current.onEnd(step.effects);
        return;
      }
      setTyped(0);
      setShown(step);
    } finally {
      busy.current = false;
    }
  }, [apply, runner]);

  useEffect(() => {
    alive.current = true;
    audio.current = new AudioPlayer();
    if (!started.has(runner)) {
      started.add(runner);
      void advance();
    }
    return () => {
      alive.current = false;
      audio.current?.stop();
    };
  }, [advance, runner]);

  const text = shown?.type === "line" ? shown.text : "";
  const visible = typingDelay === 0 ? text.length : typed;
  const typing = visible < text.length;

  useEffect(() => {
    if (!typing) {
      return;
    }
    const timer = setTimeout(() => setTyped((n) => n + 1), typingDelay);
    return () => clearTimeout(timer);
  }, [typed, typing, text, typingDelay]);

  const onTap = () => {
    if (shown?.type !== "line") {
      return;
    }
    if (typing) {
      setTyped(text.length);
    } else {
      void advance();
    }
  };

  const onChoose = async (choice: SceneChoice) => {
    if (choice.premium !== null && onPremiumChoice && !(await onPremiumChoice(choice))) {
      return;
    }
    runner.choose(choice.index);
    void advance();
  };

  const background = stage.background ? assets.background(stage.background) : undefined;
  const speaker = shown?.type === "line" ? shown.speaker : null;
  const speakerInfo =
    speaker === "me"
      ? { name: playerName }
      : speaker
        ? (characters[speaker] ?? { name: speaker })
        : null;

  return (
    <div className={`vn-scene${fx === "shake" ? " vn-shake" : ""}`} onClick={onTap}>
      <div
        className="vn-background"
        style={background ? { backgroundImage: `url("${background}")` } : undefined}
      />
      {Object.entries(stage.characters).map(([key, character]) => {
        const sprite = assets.sprite(key, character.emotion);
        return sprite ? (
          <img
            key={key}
            className={`vn-sprite vn-${character.position}${speaker === key ? " vn-speaking" : ""}`}
            src={sprite}
            alt=""
            draggable={false}
          />
        ) : null;
      })}
      {fx === "flash" && <div className="vn-flash" />}

      {shown?.type === "line" && (
        <div className="vn-dialogue">
          {speakerInfo && (
            <div className="vn-name" style={{ color: speakerInfo.color }}>
              {speakerInfo.name}
            </div>
          )}
          <p className={speaker ? "vn-text" : "vn-text vn-narration"}>
            {text.slice(0, visible)}
            <span className="vn-rest">{text.slice(visible)}</span>
          </p>
          {!typing && <div className="vn-next">▼</div>}
        </div>
      )}

      {shown?.type === "choices" && (
        <div className="vn-choices">
          {shown.choices.map((choice) => (
            <button
              key={choice.index}
              type="button"
              className="vn-choice"
              onClick={(event) => {
                event.stopPropagation();
                void onChoose(choice);
              }}
            >
              <span>{choice.text}</span>
              {choice.premium !== null && <span className="vn-price">💎 {choice.premium}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

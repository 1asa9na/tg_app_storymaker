import { formatCost, formatEffects, questJournal, relationLevel } from "./format.ts";
import type { GameAssets } from "./placeholders.ts";
import type { Activity, GameData, View } from "./types.ts";

function names(game: GameData, characters: string[]): string {
  return characters.map((key) => game.characters[key]?.name ?? key).join(", ");
}

/** Карта: иллюстрация с точками или список карточек, если иллюстрации нет. */
export function MapPanel({
  game,
  view,
  assets,
  onGo,
}: {
  game: GameData;
  view: View;
  assets: GameAssets;
  onGo(location: string): void;
}) {
  const image = game.map.image ? assets.map(game.map.image) : undefined;
  const withPoints = image && view.locations.every((l) => l.point);
  if (withPoints) {
    return (
      <div className="gu-map" style={{ backgroundImage: `url("${image}")` }}>
        {view.locations.map((location) => (
          <button
            key={location.id}
            type="button"
            className={[
              "gu-pin",
              location.lock ? "gu-locked" : "",
              location.id === view.here.location ? "gu-here" : "",
            ].join(" ")}
            style={{ left: `${location.point!.x * 100}%`, top: `${location.point!.y * 100}%` }}
            onClick={() => onGo(location.id)}
          >
            {location.name}
            {location.characters.length > 0 && <small>{names(game, location.characters)}</small>}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="gu-cards">
      {view.locations.map((location) => {
        const here = location.id === view.here.location;
        return (
          <button
            key={location.id}
            type="button"
            className={location.lock ? "gu-card gu-locked" : "gu-card"}
            style={{
              backgroundImage: `url("${assets.background(game.locations[location.id]?.background ?? location.id)}")`,
            }}
            onClick={() => onGo(location.id)}
          >
            <strong>
              {location.name}
              {here ? " · вы здесь" : ""}
            </strong>
            {location.characters.length > 0 && <span>{names(game, location.characters)}</span>}
            {location.lock && <small>{location.lock}</small>}
          </button>
        );
      })}
    </div>
  );
}

/** Локация: фон, кто здесь, занятия с ценой и тем, что они дают. */
export function PlacePanel({
  game,
  view,
  assets,
  onActivity,
  onSleep,
  onLeave,
}: {
  game: GameData;
  view: View;
  assets: GameAssets;
  onActivity(activity: Activity): void;
  onSleep(): void;
  onLeave(): void;
}) {
  const location = view.here.location ? game.locations[view.here.location] : undefined;
  if (!location) return null;
  return (
    <div className="gu-place">
      <div
        className="gu-place-bg"
        style={{ backgroundImage: `url("${assets.background(location.background)}")` }}
      >
        <div className="gu-sprites">
          {view.here.characters.map((key) => (
            <img
              key={key}
              src={assets.sprite(key, game.characters[key]?.emotions[0] ?? "neutral")}
              alt={game.characters[key]?.name ?? key}
            />
          ))}
        </div>
        <h2>{location.name}</h2>
      </div>
      <div className="gu-activities">
        {view.here.activities.map((activity) => {
          const details = [
            ...formatCost(activity.cost, game),
            ...formatEffects(activity.effects, game),
          ];
          return (
            <button
              key={activity.id}
              type="button"
              className={activity.lock ? "gu-activity gu-locked" : "gu-activity"}
              onClick={() => onActivity(activity)}
            >
              <strong>{activity.name}</strong>
              {details.length > 0 && <span>{details.join(" · ")}</span>}
              {activity.lock && <small>{activity.lock}</small>}
            </button>
          );
        })}
        {view.can_sleep && (
          <button type="button" className="gu-activity gu-sleep" onClick={onSleep}>
            <strong>Лечь спать</strong>
            <span>Наступит следующий день</span>
          </button>
        )}
        <button type="button" className="secondary" onClick={onLeave}>
          На карту
        </button>
      </div>
    </div>
  );
}

/** Инвентарь. Подарки и расходники открывают лист действия. */
export function BagPanel({
  game,
  view,
  assets,
  onItem,
}: {
  game: GameData;
  view: View;
  assets: GameAssets;
  onItem(item: string): void;
}) {
  const items = Object.entries(view.state.items).filter(([, count]) => count > 0);
  if (!items.length) return <p className="gu-empty">Сумка пуста.</p>;
  return (
    <ul className="gu-rows">
      {items.map(([key, count]) => {
        const item = game.items[key];
        const usable = item?.kind === "gift" || item?.kind === "consumable";
        const icon = item?.icon ? assets.icon(item.icon) : undefined;
        return (
          <li key={key}>
            <button type="button" className="gu-row" disabled={!usable} onClick={() => onItem(key)}>
              {icon && <img className="gu-icon" src={icon} alt="" />}
              <strong>
                {item?.name ?? key}
                {count > 1 ? ` ×${count}` : ""}
              </strong>
              {item?.description && <span>{item.description}</span>}
              {item?.kind === "gift" && <small>Можно подарить</small>}
              {item?.kind === "consumable" && <small>Можно использовать</small>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function JournalPanel({ game, view }: { game: GameData; view: View }) {
  const quests = Object.entries(view.state.quests);
  if (!quests.length) return <p className="gu-empty">Пока ни одного задания.</p>;
  const active = quests.filter(([, q]) => q.status === "active");
  const done = quests.filter(([, q]) => q.status === "done");
  return (
    <div className="gu-journal">
      {active.map(([key]) => (
        <article key={key} className="gu-quest">
          <strong>{game.quests[key]?.name ?? key}</strong>
          <span>{questJournal(view.state, game, key)}</span>
        </article>
      ))}
      {done.length > 0 && <h3>Выполнено</h3>}
      {done.map(([key]) => (
        <article key={key} className="gu-quest gu-done">
          <strong>{game.quests[key]?.name ?? key}</strong>
        </article>
      ))}
    </div>
  );
}

/** Отношения и характеристики. */
export function PeoplePanel({ game, view }: { game: GameData; view: View }) {
  return (
    <div className="gu-people">
      <ul className="gu-rows">
        {Object.entries(game.characters).map(([key, character]) => {
          const value = view.state.affection[key] ?? 0;
          return (
            <li key={key} className="gu-person">
              <strong style={{ color: character.color ?? undefined }}>{character.name}</strong>
              <span>
                {relationLevel(character.levels, value)} · ♥ {value}
              </span>
            </li>
          );
        })}
      </ul>
      {Object.keys(game.stats).length > 0 && (
        <>
          <h3>Характеристики</h3>
          <ul className="gu-rows">
            {Object.entries(game.stats).map(([key, stat]) => {
              const value = view.state.stats[key] ?? 0;
              return (
                <li key={key} className="gu-stat">
                  <span>{stat.name}</span>
                  <meter min={stat.min} max={stat.max} value={value} />
                  <strong>{value}</strong>
                </li>
              );
            })}
          </ul>
        </>
      )}
      <h3>Аккаунт</h3>
      <p className="gu-muted">
        Уровень {view.account.level} · опыт {view.account.xp} из {view.account.next_level_xp}
      </p>
    </div>
  );
}

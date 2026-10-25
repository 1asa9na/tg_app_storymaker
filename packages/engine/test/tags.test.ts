import { describe, expect, it } from "vitest";

import { parseTag, TagError } from "../src/tags.ts";

describe("parseTag", () => {
  it("parses scene commands", () => {
    expect(parseTag("bg: gym")).toEqual({ kind: "command", command: { type: "bg", key: "gym" } });
    expect(parseTag("show: anna smirk left")).toEqual({
      kind: "command",
      command: { type: "show", character: "anna", emotion: "smirk", position: "left" },
    });
    expect(parseTag("show: anna happy")).toMatchObject({ command: { position: null } });
    expect(parseTag("music: stop")).toEqual({
      kind: "command",
      command: { type: "music", key: null },
    });
    expect(parseTag("wait: 1.5")).toEqual({
      kind: "command",
      command: { type: "wait", seconds: 1.5 },
    });
    expect(parseTag("fx: shake")).toEqual({
      kind: "command",
      command: { type: "fx", name: "shake" },
    });
  });

  it("parses effects", () => {
    expect(parseTag("effect: affection anna +3")).toEqual({
      kind: "effect",
      effect: { op: "affection", character: "anna", delta: 3 },
    });
    expect(parseTag("effect: take water_bottle")).toMatchObject({
      effect: { op: "take", count: 1 },
    });
    expect(parseTag("effect: give rose 2")).toMatchObject({ effect: { op: "give", count: 2 } });
    expect(parseTag("effect: unflag met_anna")).toMatchObject({
      effect: { op: "flag", flag: "met_anna", value: false },
    });
    expect(parseTag("effect: xp 10")).toMatchObject({ effect: { op: "xp", amount: 10 } });
  });

  it("parses premium price", () => {
    expect(parseTag("premium: 15")).toEqual({ kind: "premium", price: 15 });
  });

  it.each([
    "bg",
    "bg: Gym",
    "show: anna",
    "show: anna happy top",
    "wait: 0",
    "fx: blink",
    "effect: affection anna 3",
    "effect: give rose 0",
    "effect: teleport anna",
    "premium: -5",
    "unknown: x",
  ])("rejects «%s»", (raw) => {
    expect(() => parseTag(raw)).toThrow(TagError);
  });
});

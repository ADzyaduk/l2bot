# L2Net ↔ Python L2Bot cross-reference

Local L2Net tree (reference only): `C:\pj\L2Bot\L2Net`. This project targets **Teon / Elmorelab Interlude**; **do not copy numeric opcodes** from L2Net `PServer` / `PClient` — they differ from this shard (e.g. Teon **CS_Action = 0x04** vs L2Net `PClient.Action` values).

**Source of truth for opcodes:** XOR-resolved session opcodes from the game proxy log + [`core/protocol/opcode_detector.py`](../core/protocol/opcode_detector.py) `TEON_BASE_OPCODES`, plus builders/parsers under [`core/packets/client/`](../core/packets/client/__init__.py) and [`core/packets/server/`](../core/packets/server/__init__.py).

## Module mapping

| Python | L2Net (look at field order / ideas) | Compare | Do not copy |
|--------|-------------------------------------|---------|-------------|
| `core/packets/client/__init__.py` | `Code/Network/Packets/ServerPackets.cs` (C2S builders) | Layout of `Use_Skill`, movement, action | Opcode integers |
| `core/packets/server/__init__.py` | `ClientPackets.cs` (S2C parsers) | `AbnormalStatusUpdate` / buff effect rows | Opcode integers |
| `engine/bot.py` | `GameServer_HandlePackets.cs`, scripting | Handler coverage, timing ideas | Full dispatcher |
| `engine/world.py` | In-memory `CharInfo` / `NPCInfo` usage in scripts | NPC filtering, distance | C# types |
| `engine/combat_profile.py` | `BotOptions`, `Script_Ops` lists | Whitelist/blacklist, Z range, aggro priority | — |
| `core/crypto/blowfish_cipher.py` | L2Net Blowfish | Test vectors only | Replace wholesale |

## Auto-combat (script layer in L2Net)

L2Net drives combat via **scripts**, mainly:

- [`Script_Handlers_L2.cs`](file:///C:/pj/L2Bot/L2Net/Code/Scripting/Handlers/Script_Handlers_L2.cs): `Script_TARGET_NEAREST_Internal` (~2244+) — nearby NPC scan, **priority for mobs already hitting you** (`attackingself`), **keep current target** if same NPC type and still within a short 3D distance, filters (`MeetsConditions`).
- Same file: `Script_ATTACK_TARGET` (~2722+) — skip **party** and **summon** edge cases before `ClickOBJ`.
- [`Script_Ops.cs`](file:///C:/pj/L2Bot/L2Net/Code/Scripting/Logic/Script_Ops.cs): `NEAREST_*`, **DoNotNPC**-style lists.

Python implementation: [`engine/bot.py`](../engine/bot.py) `_auto_combat_loop`, target selection via [`World.pick_auto_combat_target`](../engine/world.py), rules in [`CombatProfile`](../engine/combat_profile.py). Attack chain stays **Teon**: **0x04** target + **0x2F** force attack — not L2Net’s opcode numbers for `ClickOBJ` / `AttackRequest`.

## UI ↔ L2Net windows (ideas only)

| L2Net concept | Our UI |
|---------------|--------|
| Packet filter / packet window | **Log** tab → Packets pane: direction filters, text filter, recent hex buffer |
| Status / connection | [`ui/app.py`](../ui/app.py) status bar + combat phase from `BotEngine` |
| Script editor | **Script** tab |
| Shortcuts / bar | Not cloned; JSON **presets** on Auto combat / Buffs where useful |

## S2C buff-related packets

- **AbnormalStatusUpdate** (base `0x7F` in `TEON_BASE_OPCODES`) — primary self buff list; layout variants handled in `AbnormalStatusUpdate.parse`.
- **PartySpelled** (base `0xEE` L2J Interlude) — buff list per party member object id; merged into `World.abnormal_buffs_by_object` when detected.
- **ShortBuffStatusUpdate** (base `0x91` L2J-style) — short icon row; optional merge for self when `object_id` matches.

If XOR’d opcodes on a fork do not match, capture one session hex and adjust `TEON_BASE_OPCODES` / parser — never paste L2Net enum values blindly.

## Optional / not ported

- **MoveBeforeTargeting / MOVE_SMART** — requires pathing or waypoints; `CombatProfile.move_before_targeting` reserved, not executed until pathing exists.
- Full L2Net **script VM** — out of scope.

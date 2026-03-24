# Post-kill sit / stand recovery

## What was going wrong

The client uses **one** packet for both sit and stand: `CS_RequestActionUse` with `actionId=0` — it is a **toggle**, not “sit” and “stand” separately.

If the character was **already sitting** (you sat manually, or state was wrong), the first toggle **stood** them. The bot then waited for HP, called toggle again “to stand”, which **sat** again — so you could end up at **full HP but still sitting**.

Another issue: if recovery **timed out** or you **stopped auto-combat** while `_wait_recovery` was running, the second toggle might never run, leaving you sitting.

## What we do now

1. **`SC_ChangeWaitType`** (Teon base opcode `0x25`, XOR-scrambled per session) is parsed and updates `World.me.me_sitting` for your object id when the second dword is a known pattern.
2. **Before sitting for recovery** we skip the toggle if `me_sitting` is already `True`.
3. **After recovery** (success, timeout, or combat stopped mid-wait) a `finally` block calls **`_ensure_standing_after_recovery`**, which toggles only if the server said we are sitting or we had sent a sit toggle with state still unknown.
4. **`MoveToPoint` for self** sets `me_sitting = False` (you cannot walk while sitting).
5. **New character / object id** from `UserInfo` resets `me_sitting` to standing (`False`).

## Fork-specific: second dword meaning

Many Interlude private cores use **Acis-style** encoding: `0` = sitting, `1` = standing. Some stacks use the opposite.

In `config/autocombat.json` set:

```json
"recovery_change_wait_type_sit_raw": 0
```

Use **`1`** if your server sends `1` when sitting (Mobius-like). The bot compares the packet’s second `int` to this value when it is only `0` or `1`. Larger enum values (`5`, `7`, etc.) are treated as sitting; `2`–`6` as not sitting.

## Timing

After each toggle we wait **`_RECOVERY_TOGGLE_ACK_SEC` (0.4s)** in code so `ChangeWaitType` can arrive before the next toggle.

## This is not “broken decryption”

Login lines like `Unknown client opcode` are the proxy not naming a C2S packet. Sit/stand bugs here were **toggle + missing server state**, not Blowfish/XOR game crypto.

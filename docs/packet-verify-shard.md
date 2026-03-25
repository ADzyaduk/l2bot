# Verifying Abnormal / PartySpelled on your shard

If buff rules or target abnormal gating behave wrong, confirm what the server actually sends.

1. Connect the game client through the proxy and log in.
2. Open the **Log** tab → enable **Packets** (direction server → client).
3. Filter or search for opcodes that decode as `AbnormalStatusUpdate` / `PartySpelled` after XOR (see `core/protocol/opcode_detector.py` base names).
4. Capture one full payload hex for a suspicious packet.
5. Compare field layout with your fork’s L2J `gameserver/network/serverpackets` sources (e.g. `AbnormalStatus`, `PartySpelled`).
6. If lengths or field order differ, add or adjust a branch in `AbnormalStatusUpdate.parse` in `core/packets/server/__init__.py` and extend `tests/test_server_packets_phase2.py` with that hex body.

Teon and private forks often vary slightly from stock Interlude; **do not** copy opcode numbers from L2Net — only compare structure.

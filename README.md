# L2Bot

Lineage 2 **MITM proxy bot** (Interlude-oriented, tested against Teon-style XOR game protocol). The game client connects to localhost; traffic is forwarded to the real login/game servers while a shadow decrypt path feeds `BotEngine` for world state, auto-combat, and buff maintenance.

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Configure `config/settings.ini` (active server profile, `l2_path` for optional `l2.ini` patch). Client should use the same login/game ports as `[proxy]` (default `2106` / `7777`).

- `python main.py --no-ui` — headless
- `python main.py --config path/to/settings.ini`

## Documentation

Full project documentation (architecture, folders, config, modules): **[docs/PROJECT.md](docs/PROJECT.md)** (Russian).

- Sit/stand recovery details: [docs/recovery-sit-stand.md](docs/recovery-sit-stand.md)

## Layout

| Area | Role |
|------|------|
| `core/proxy` | Login & game TCP proxies, session state |
| `core/crypto` | Blowfish, XOR, checksum, RSA |
| `core/protocol` | Opcode detection (Teon), packet helpers |
| `core/packets` | Client builders, server parsers |
| `engine` | `BotEngine`, `World`, combat/buff profiles |
| `ui` | CustomTkinter tabs, logging |
| `tests` | `pytest` |

## Tests

```bash
pytest tests/ -q
```

## Requirements

See `requirements.txt` (`pycryptodome`, `customtkinter`, `pyparsing`).

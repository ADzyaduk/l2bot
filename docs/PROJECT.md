# L2Bot — документация проекта

Прокси-бот для **Lineage 2** (ориентир: хроника **Interlude**, тесты на **Teon / Elmorelab**): клиент подключается к локальному MITM, трафик пересылается на реальный login/game сервер, параллельно расшифровывается копия игровых пакетов для логики бота (мир, авто-бой, баффы).

---

## Содержание

1. [Архитектура](#архитектура)
2. [Запуск и зависимости](#запуск-и-зависимости)
3. [Конфигурация](#конфигурация)
4. [Структура репозитория](#структура-репозитория)
5. [Слой `core`](#слой-core)
6. [Слой `engine`](#слой-engine)
7. [Интерфейс `ui`](#интерфейс-ui)
8. [Точка входа `main.py`](#точка-входа-mainpy)
9. [Тесты и вспомогательные скрипты](#тесты-и-вспомогательные-скрипты)
10. [Дополнительные материалы](#дополнительные-материалы)

---

## Архитектура

```
L2.exe  ──TCP──►  localhost:2106  [LoginProxy]  ──TCP──►  Реальный Login Server
                    │
                    │  ServerList: подмена IP:port игрового сервера на 127.0.0.1:7777

L2.exe  ──TCP──►  localhost:7777  [GameProxy]   ──TCP──►  Реальный Game Server
                    │
                    └── Теневая расшифровка Blowfish (+ при необходимости XOR) → BotEngine
```

- **Login proxy** — другой формат пакетов, чем у игры: длина + тело, из Init извлекается Blowfish-ключ логина; при необходимости патчится **ServerList**, чтобы клиент шёл в локальный game proxy.
- **Game proxy** — фрейм `[uint16 LE длина][зашифрованное Blowfish тело]`; после расшифровки: `opcode` + payload + checksum. Клиентский трафик в основном прозрачно ретранслируется; бот **инжектит** отдельные C2S пакеты (атака, скиллы, сиденье и т.д.).

Поток управления:

- **asyncio** крутится в **фоновом потоке** (`BotCore._run_loop`).
- **GUI** (главный поток) вызывает `asyncio.run_coroutine_threadsafe` / `call_soon_threadsafe` для команд бота.

---

## Запуск и зависимости

**Python 3.10+** (в проекте встречается 3.14 в кэше).

```bash
pip install -r requirements.txt
python main.py
```

| Зависимость      | Назначение                          |
|-----------------|--------------------------------------|
| `pycryptodome`  | RSA / Blowfish и крипто протокола   |
| `customtkinter` | GUI (без него — режим `--no-ui`)    |
| `pyparsing`     | вспомогательные задачи парсинга    |

Аргументы:

- `python main.py` — GUI.
- `python main.py --no-ui` — только прокси и бот, без окна.
- `python main.py --config путь/к/settings.ini` — другой ini.

Клиент должен подключаться к **тому же порту**, на котором слушает прокси (по умолчанию login **2106**, game **7777**). Обычно `l2.ini` патчится под `127.0.0.1` (см. `main.patch_l2_ini` и `l2_path` в настройках).

---

## Конфигурация

### `config/settings.ini`

- **`[active]`** — `server = имя_профиля` → используется секция `[server.имя_профиля]`.
- **`[server.<имя>]`**:
  - `login_host`, `login_port` — реальный логин-сервер.
  - `game_host`, `game_port` — начальная подсказка для game proxy; реальный адрес часто **обновляется из ServerList** при входе.
  - `l2_path` — путь к `L2.exe` (для автопатча `l2.ini` рядом с клиентом).
  - `chronicle` — влияет на реестр пакетов (`registry.set_chronicle`).
- **`[proxy]`** — `listen_login_port`, `listen_game_port` — порты прослушивания на localhost.
- **`[bot]`** — например `log_level`, `auto_start`.

### `config/autocombat.json`

Профиль **авто-боя** (`CombatProfile`): дистанция, лут, тайминги kill-loop, пороги HP/MP для сидения после убийства, опции пакетов (`target_cancel_payload`, `magic_skill_payload`), правила скиллов/предметов. Загрузка: `engine.combat_profile.load_profile`.

### `config/buffs.json`

Профиль **баффов** (`BuffProfile`): очередь правил, стиль пакетов баффа (`buff_skill_packet` 0x39 vs 0x2F и т.д.). Загрузка: `engine.buff_profile.load_buff_profile`.

### `config/ui_state.json`

Сохраняется автоматически: геометрия окна, индекс вкладки.

### `data/*.json`

Справочники (например `items_en.json`, `skills_en.json`) для отображения имён в UI.

---

## Структура репозитория

| Путь | Назначение |
|------|------------|
| `main.py` | Точка входа, `BotCore`, старт прокси и UI |
| `core/proxy/` | `login_proxy`, `game_proxy`, `session` (сессионное состояние) |
| `core/crypto/` | Blowfish, XOR (game/login), checksum, RSA |
| `core/protocol/` | `registry`, `opcode_detector`, `packet_reader` / `writer`, `base_packet`, категории |
| `core/packets/client/` | Сборка C2S пакетов (атака, движение, скиллы, …) |
| `core/packets/server/` | Разбор S2C (UserInfo, NpcInfo, StatusUpdate, ChangeWaitType, …) |
| `core/game_reference.py` | Внешние справочники/данные сессии (по мере развития) |
| `engine/bot.py` | `BotEngine`: диспетчер S2C, авто-бой, инжекты |
| `engine/world.py` | Модель мира: персонаж, NPC, дроп, инвентарь по пакетам |
| `engine/combat_profile.py` | Модель и JSON авто-боя |
| `engine/buff_profile.py` | Модель и JSON баффов |
| `ui/` | Окно, тема, вкладки, лог в UI |
| `tests/` | Pytest |
| `scripts/` | Утилиты (например выгрузка справки L2J) |
| `docs/` | Документация (этот файл, узкие темы) |

---

## Слой `core`

### Прокси

- **`LoginProxyServer`** — ретрансляция, перехват Init / ключей, патч ServerList, логирование неизвестных C2S opcodes (имена не обязаны быть заведены).
- **`GameProxyServer`** — ретрансляция игрового потока, извлечение ключа из `BlowfishInit`, опционально XOR после `CryptInit`, вызов `on_server_packet(opcode, payload)` для бота, метод **`inject_to_server`** для инжекта от бота.

### Криптография

Соответствует классической схеме L2 game/login: Blowfish сессии, checksum в конце тела пакета, отдельные правила для login-обфускации.

### Протокол

- **`registry`** — имена пакетов и привязка к хронике.
- **`OpcodeDetector`** — для **Teon**: по XOR-ключу сессии и пакетам (в т.ч. размер NpcInfo ~187 байт) восстанавливаются «базовые» opcodes; дальше все хендлеры в боте вешаются на **уже XOR’нутые** opcodes сессии.
- **`packet_reader` / `packet_writer` / `BasePacket`** — удобное чтение полей из payload.

### Пакеты

- **Client** — функции вида `build_attack`, `build_move`, `build_use_skill`, …
- **Server** — `*.parse(payload)` → dataclass; часть полей может быть упрощена под конкретный шард.

---

## Слой `engine`

### `BotEngine` (`engine/bot.py`)

- Подписывается на **`GameProxy.on_server_packet`** (async dispatch).
- До готовности детектора буферизует пакеты и **переигрывает** их после назначения opcodes.
- Таблица **`_handlers`**: opcode → метод `_on_*`, обновляется в **`_on_opcodes_detected`**.
- **Авто-бой**: asyncio-цикл таргет/атака/лут/опционально сидение после убийства (см. `docs/recovery-sit-stand.md`).
- **Бафф-луп**: по профилю баффов и `AbnormalStatusUpdate`.
- Публичные действия: `attack`, `move_to`, `use_skill`, `sit_stand`, `pickup`, старт/стоп авто-боя и смена профилей.

### `World` (`engine/world.py`)

Агрегирует состояние: **`MyChar`** (позиция, HP/MP, target, `me_sitting`, baseline max HP/MP для защиты от мусорных StatusUpdate), **`Npc`**, **`GroundItem`**, скиллы, инвентарь по objectId, баффы по abnormal, кулдауны скиллов.

### Профили

- **`CombatProfile`** — сериализация в/из JSON, миграции старых ключей (где предусмотрено).
- **`BuffProfile`** — то же для баффов.

---

## Интерфейс `ui`

- **`L2BotApp`** — главное окно, вкладки, статус подключения, сохранение `ui_state.json`.
- Вкладки: **Character**, **Monsters**, **Auto combat**, **Buffs**, **Script**, **Log**, **Settings**.
- **`log_handler`** — дублирование логов в вкладку Log.

Действия UI вызывают методы **`BotCore`** (потокобезопасно в сторону asyncio).

---

## Точка входа `main.py`

Класс **`BotCore`**:

- поднимает **GameProxy** и **LoginProxy**;
- связывает **LoginSession.on_game_server_discovered** с обновлением `game_proxy.real_host/real_port`;
- создаёт **`BotEngine`**, вызывает `start()`;
- держит event loop живым до остановки.

Публичный API для UI: инжект, авто-бой, sit/stand, применение/перезагрузка профилей с диска.

---

## Тесты и вспомогательные скрипты

- Запуск: `pytest tests/ -q`
- Темы: крипто, парсеры пакетов, логика мира (HP sanity), гварды бота, login/serverlist, change wait type, баффы.

**`scripts/fetch_l2j_reference.py`** — вспомогательный скрипт для сверки с исходниками L2J (разработка), не нужен для обычного запуска.

---

## Дополнительные материалы

- [recovery-sit-stand.md](recovery-sit-stand.md) — пост-убойное сидение: toggle `RequestActionUse`, `ChangeWaitType`, опция `recovery_change_wait_type_sit_raw` в `autocombat.json`.

---

## Замечания по эксплуатации

1. **Совместимость** завязана на конкретный клиент/сервер (длины NpcInfo, XOR Teon, поля UserInfo). При смене шарда возможны сдвиги — смотрите логи `[UNKNOWN]` и тесты парсеров.
2. **Неизвестные opcodes** в логине/игре не всегда означают ошибку: часть пакетов просто не разобрана в прокси.
3. Использование ботов может **нарушать правила** выбранного сервера; ответственность за применение — на пользователе.

---

*Документ отражает состояние кодовой базы на момент последнего обновления; при крупных рефакторингах имеет смысл поправить разделы `core/` и `engine/`.*

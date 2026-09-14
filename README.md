# ElytrixFuckCheats (EFC)

Киборг-античит для Paper-форков (ShieldSpigot). Сервер: **1.16.5** (Java 8+).
Клиенты: 1.16.5 → 26.2 через ViaVersion на сервере. Зависимость: PacketEvents 1.x.

## Принципы
1. **Честный игрок не страдает** — exemptions (пинг, TPS, телепорт, вход), консервативные пороги, VL с затуханием.
2. **Алерты → кик** только при жёстком палеве. Автобана нет.
3. **Мало проверок, но точных.** Детект растёт апдейтами, безопасность — с билда №1.
4. **Закрытые эвристики** — читы не знают наших проверок.

## Стек идей
- Движение: Grim / Intave (симуляция + лаг-компенсация), кандидат в ядро — `neo` (MIT).
- Мультиверсия: Windfall (MIT, 1.7–26.2).
- PvP/Aim: Hawk/NESS-математика + rotation-эвристики + React (MIT).
- Релиз-философия: BS-AntiCheat (опасное ВЫКЛ по дефолту).
- Тесты: как Intave — записи движений легитов как регресс.

## Сборка
- CI (GitHub Actions): `gradle build` против настоящего `spigot-api 1.16.5`.
- Локально в песочнице: `./build-local.sh` → `ElytrixFuckCheats.jar`
  (JDK качается сам, Bukkit API подменяется compile-only стабами из `stubs/`).

## Команды (билд №1)
- `/efc alerts` — вкл/выкл алерты себе (`efc.alerts`)
- `/efc verbose` — дебаг-флаги (`efc.admin`)
- `/efc info <ник>` — VL игрока (`efc.alerts`)
- `/efc exempt <ник> <сек>` — временный байпас (`efc.admin`)
- `/efc reload` — перезагрузка конфига (`efc.admin`)

## Роадмап
- [x] Ядро: PlayerData, VL, exemptions, алерты, наказания, команды
- [x] Комбат-пакет (порты топов): Reach A (Hawk, глаз→бокс, отмена с 3.0
      как у Grim), Reach.B, Aim.C (Hawk, луч→бокс), Aim.D (Medusa, замок оси),
      Aim.E (Medusa, круглые доводки), Aim.F (Medusa, прилипание к цели),
      Criticals.A (NESS),
      KillAura.B (умный no-swing v2), KillAura.D KeepSprint (Medusa),
      KillAura.F синхронность ударов (Hawk), KillAura.G ритм ударов,
      AutoClicker.C (NESS MaxCPS 18), AutoClicker.D темп атак (Hawk),
      KillAura A/C, AutoClicker A/B,
      Accuracy.A/B, Velocity.A, FastBow.A, FastEat.A.
      Инфра: лаг-компенсация позиций (перемотка жертвы), /efc debug.
      ВЫКЛЮЧЕНЫ: KillAura.E (паттерн угла флагает скилловых легитов),
      Aim.A/B (GCD-ротация врёт на современных мышах).
      Вернутся с пакетным слоем (как у Grim).
      Обследованы: Hawk, NESS, Medusa, VulcanOLD, NCP, Grim, Artemis, MX, Negativity.
- [x] Движение (2): Fly.A, Speed.A (консервативные)
- [ ] Пакетный слой (PacketEvents): пинг, версии клиентов, точная ротация
- [ ] Записи легитов как регресс-тесты
- [ ] Следующий пакет: Jesus, NoFall, Step, Scaffold, NoSlow, Criticals

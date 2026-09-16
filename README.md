# ElytrixBots

Первый прототип лёгких packet-only ботов для Paper 1.16.5.

- 2 виртуальных игрока только в TAB;
- 3 видимых VirtualPlayer появляются и бегут к своим точкам;
- все имена, ping, координаты и скорость находятся в `config.yml`;
- нет клиентских подключений, AI и pathfinding.

## Требования

- Paper 1.16.5 на Java 16
- [VirtualEntityApi 1.4.2](https://github.com/By1337/VirtualEntityApi)
- BLib (зависимость VirtualEntityApi)

Сначала установите VirtualEntityApi и BLib в `plugins/`, затем `ElytrixBots-0.1.0-SNAPSHOT.jar`.

## Сборка

```bash
mvn clean package
```

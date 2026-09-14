#!/bin/bash
# Локальная сборка ElytrixFuckCheats.jar без Gradle и без maven-репозиториев.
# JDK 17 качается сам (нужен только hosts registry.npmjs.org).
# Bukkit API заменён compile-only стабами из ./stubs (в jar НЕ попадают).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
JDK_DIR="/tmp/efc/jre/package/jre"
CLASSES="/tmp/efc/classes"

if [ ! -x "$JDK_DIR/bin/javac" ]; then
  echo "[local-build] downloading JDK 17..."
  mkdir -p /tmp/efc/jre && cd /tmp/efc/jre
  curl -sL --max-time 600 -o jre.tgz "https://registry.npmjs.org/javajre-linux-64/-/javajre-linux-64-17.0.8.tgz"
  tar xzf jre.tgz
  cd "$ROOT"
fi

echo "[local-build] compiling (release 8)..."
rm -rf "$CLASSES" && mkdir -p "$CLASSES"
# shellcheck disable=SC2046
"$JDK_DIR/bin/javac" --release 8 -encoding UTF-8 -nowarn -d "$CLASSES" \
  $(find "$ROOT/stubs" "$ROOT/src/main/java" -name '*.java')

# Стабы в jar не кладём — на сервере их даёт сам ShieldSpigot.
rm -rf "$CLASSES/org"
cp "$ROOT/src/main/resources/plugin.yml" "$ROOT/src/main/resources/config.yml" "$CLASSES/"

echo "[local-build] packing jar..."
rm -f "$ROOT/ElytrixFuckCheats.jar"
"$JDK_DIR/bin/jar" --create --file "$ROOT/ElytrixFuckCheats.jar" -C "$CLASSES" .
"$JDK_DIR/bin/jar" --list --file "$ROOT/ElytrixFuckCheats.jar"
echo "[local-build] done: $ROOT/ElytrixFuckCheats.jar"

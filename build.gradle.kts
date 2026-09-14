plugins {
    java
}

group = "ru.elytrix"
version = "0.1.0-SNAPSHOT"

// TODO: финальный Java-уровень после ответа о версии ShieldSpigot.
// 1.16.5-сервер = Java 8..16 рантайм (таргет 8/11), 1.20.5+ = Java 21.
java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
    maven("https://repo.codemc.io/repository/maven-public/")
}

dependencies {
    // API сервера 1.16.5. На рантайме предоставляет сам ShieldSpigot.
    compileOnly("io.papermc.paper:paper-api:1.16.5-R0.1-SNAPSHOT")
    // TODO билд №2: PacketEvents 1.x (Java 8, протокол 1.16.5).
    // Версию возьмём из метаданных репозитория перед написанием пакетного слоя.
}

tasks.withType<JavaCompile> {
    options.encoding = "UTF-8"
}

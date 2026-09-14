package ru.elytrix.efc.config;

import java.util.Collections;
import java.util.List;
import org.bukkit.configuration.file.FileConfiguration;
import ru.elytrix.efc.ElytrixFuckCheats;

/** Обёртка над config.yml — все значения с безопасными дефолтами. */
public final class ConfigManager {

    private final ElytrixFuckCheats plugin;

    public ConfigManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    private FileConfiguration config() {
        return plugin.getConfig();
    }

    public String prefix() {
        return config().getString("prefix", "&8[&cEFC&8]");
    }

    public String alertFormat() {
        return config().getString("alerts.format",
                "%prefix% &c%player% &7флагнут &e%check% &7(VL: &c%vl%&7) &8%details%");
    }

    public boolean consoleAlerts() {
        return config().getBoolean("alerts.console", true);
    }

    public double vlDecayPerSecond() {
        return config().getDouble("vl-decay-per-second", 1.0);
    }

    public long joinGraceMs() {
        return config().getLong("grace.join-seconds", 5) * 1000;
    }

    public long teleportGraceMs() {
        return config().getLong("grace.teleport-seconds", 3) * 1000;
    }

    public double minTps() {
        return config().getDouble("min-tps", 18.5);
    }

    public boolean creativeBypass() {
        return config().getBoolean("creative-bypass", true);
    }

    public long punishCooldownMs() {
        return config().getLong("punish-cooldown-seconds", 60) * 1000;
    }

    public boolean checkEnabled(String key) {
        return config().getBoolean("checks." + key + ".enabled", false);
    }

    public double checkMaxVl(String key) {
        return config().getDouble("checks." + key + ".max-vl", 20.0);
    }

    public double checkAddVl(String key) {
        return config().getDouble("checks." + key + ".add-vl", 1.0);
    }

    /** Произвольный числовой параметр проверки. */
    public double checkDouble(String checkKey, String key, double def) {
        return config().getDouble("checks." + checkKey + "." + key, def);
    }

    public List<String> punishCommands(String key) {
        List<String> specific = config().getStringList("punishments." + key);
        if (!specific.isEmpty()) {
            return specific;
        }
        List<String> def = config().getStringList("punishments.default");
        if (!def.isEmpty()) {
            return def;
        }
        return Collections.singletonList("kick %player% Elytrix: читы запрещены (%check%)");
    }

    public void reload() {
        plugin.reloadConfig();
    }
}

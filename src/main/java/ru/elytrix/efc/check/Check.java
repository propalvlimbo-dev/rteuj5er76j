package ru.elytrix.efc.check;

import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.config.ConfigManager;
import ru.elytrix.efc.data.PlayerData;

/**
 * База всех проверок. Один флаг = +VL, алерт, возможное наказание.
 * Перед флагом всегда спрашиваем ExemptionManager — легит важнее детекта.
 */
public abstract class Check {

    protected final ElytrixFuckCheats plugin;
    private final String name;
    private final String type;
    private final Category category;

    protected Check(ElytrixFuckCheats plugin, String name, String type, Category category) {
        this.plugin = plugin;
        this.name = name;
        this.type = type;
        this.category = category;
    }

    /** Полный ID: "KillAura.A". */
    public final String id() {
        return name + "." + type;
    }

    /** Ключ в конфиге: "killaura-a". */
    public final String configKey() {
        return (name + "-" + type).toLowerCase();
    }

    public final String getName() {
        return name;
    }

    public final String getType() {
        return type;
    }

    public final Category getCategory() {
        return category;
    }

    public final boolean isEnabled() {
        return plugin.getConfigManager().checkEnabled(configKey());
    }

    public final double getMaxVl() {
        return plugin.getConfigManager().checkMaxVl(configKey());
    }

    /**
     * Флагнуть игрока. Возвращает новый VL (0 — если флага не было).
     */
    protected final double flag(PlayerData data, String details) {
        return flag(data, details, 1.0);
    }

    protected final double flag(PlayerData data, String details, double multiplier) {
        if (!isEnabled()) {
            return 0;
        }
        Player player = data.getPlayer();
        if (player == null) {
            return 0;
        }
        // Правило №1: exemptions раньше детекта.
        if (plugin.getExemptionManager().isExempt(player, category)) {
            return 0;
        }
        ConfigManager config = plugin.getConfigManager();
        double vl = data.addVl(id(), config.checkAddVl(configKey()) * multiplier);
        plugin.getAlertManager().alert(data, this, details, vl);
        plugin.getPunishmentManager().onFlag(data, this, vl);
        return vl;
    }

    /** Снять VL (награда за легитное поведение). */
    protected final void reward(PlayerData data, double amount) {
        data.addVl(id(), -Math.abs(amount));
    }

    /** Вызывается при выходе игрока — почистить своё состояние. */
    public void onQuit(UUID uuid) {
    }

    /** Свой числовой параметр из checks.<ключ>.<параметр>. */
    protected final double cfg(String key, double def) {
        return plugin.getConfigManager().checkDouble(configKey(), key, def);
    }
}

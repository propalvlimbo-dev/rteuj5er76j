package ru.elytrix.efc;

import org.bukkit.plugin.java.JavaPlugin;
import ru.elytrix.efc.alert.AlertManager;
import ru.elytrix.efc.check.CheckManager;
import ru.elytrix.efc.command.EfcCommand;
import ru.elytrix.efc.config.ConfigManager;
import ru.elytrix.efc.data.DataManager;
import ru.elytrix.efc.exempt.ExemptionManager;
import ru.elytrix.efc.punish.PunishmentManager;

/**
 * ElytrixFuckCheats — киборг-античит.
 * Приоритет №1: честный игрок никогда не страдает.
 */
public final class ElytrixFuckCheats extends JavaPlugin {

    private ConfigManager configManager;
    private DataManager dataManager;
    private ExemptionManager exemptionManager;
    private AlertManager alertManager;
    private PunishmentManager punishmentManager;
    private CheckManager checkManager;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        this.configManager = new ConfigManager(this);
        this.dataManager = new DataManager(this);
        this.exemptionManager = new ExemptionManager(this);
        this.alertManager = new AlertManager(this);
        this.punishmentManager = new PunishmentManager(this);
        this.checkManager = new CheckManager(this);

        getServer().getPluginManager().registerEvents(dataManager, this);
        getServer().getPluginManager().registerEvents(exemptionManager, this);
        getServer().getPluginManager().registerEvents(alertManager, this);

        EfcCommand command = new EfcCommand(this);
        getCommand("efc").setExecutor(command);
        getCommand("efc").setTabCompleter(command);

        getLogger().info("ElytrixFuckCheats enabled. Checks: " + checkManager.getChecks().size());
    }

    @Override
    public void onDisable() {
        if (dataManager != null) {
            dataManager.clear();
        }
    }

    public ConfigManager getConfigManager() {
        return configManager;
    }

    public DataManager getDataManager() {
        return dataManager;
    }

    public ExemptionManager getExemptionManager() {
        return exemptionManager;
    }

    public AlertManager getAlertManager() {
        return alertManager;
    }

    public PunishmentManager getPunishmentManager() {
        return punishmentManager;
    }

    public CheckManager getCheckManager() {
        return checkManager;
    }
}

package ru.elytrix.efc.check;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.checks.combat.AutoClickerA;
import ru.elytrix.efc.checks.combat.KillAuraA;
import ru.elytrix.efc.checks.combat.ReachA;
import ru.elytrix.efc.checks.movement.FlyA;
import ru.elytrix.efc.checks.movement.SpeedA;

/**
 * Реестр проверок. Каждая проверка сама слушает Bukkit-события.
 */
public final class CheckManager {

    private final ElytrixFuckCheats plugin;
    private final List<Check> checks = new ArrayList<>();

    public CheckManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
        registerAll();
    }

    private void registerAll() {
        register(new KillAuraA(plugin));
        register(new ReachA(plugin));
        register(new AutoClickerA(plugin));
        register(new FlyA(plugin));
        register(new SpeedA(plugin));
    }

    public void register(Check check) {
        checks.add(check);
        plugin.getServer().getPluginManager().registerEvents(check, plugin);
    }

    public List<Check> getChecks() {
        return Collections.unmodifiableList(checks);
    }

    public Check get(String id) {
        for (Check check : checks) {
            if (check.id().equalsIgnoreCase(id)) {
                return check;
            }
        }
        return null;
    }

    /** Почистить состояние всех проверок при выходе игрока. */
    public void onQuit(UUID uuid) {
        for (Check check : checks) {
            check.onQuit(uuid);
        }
    }
}

package ru.elytrix.efc.check;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.checks.combat.AccuracyA;
import ru.elytrix.efc.checks.combat.AimA;
import ru.elytrix.efc.checks.combat.AimB;
import ru.elytrix.efc.checks.combat.AimC;
import ru.elytrix.efc.checks.combat.AutoClickerA;
import ru.elytrix.efc.checks.combat.AutoClickerB;
import ru.elytrix.efc.checks.combat.FastBowA;
import ru.elytrix.efc.checks.combat.FastEatA;
import ru.elytrix.efc.checks.combat.KillAuraA;
import ru.elytrix.efc.checks.combat.KillAuraB;
import ru.elytrix.efc.checks.combat.KillAuraC;
import ru.elytrix.efc.checks.combat.ReachA;
import ru.elytrix.efc.checks.combat.ReachB;
import ru.elytrix.efc.checks.combat.VelocityA;
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
        register(new KillAuraB(plugin));
        register(new KillAuraC(plugin));
        register(new ReachA(plugin));
        register(new ReachB(plugin));
        register(new AutoClickerA(plugin));
        register(new AutoClickerB(plugin));
        register(new AimA(plugin));
        register(new AimB(plugin));
        register(new AimC(plugin));
        register(new AccuracyA(plugin));
        register(new VelocityA(plugin));
        register(new FastBowA(plugin));
        register(new FastEatA(plugin));
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

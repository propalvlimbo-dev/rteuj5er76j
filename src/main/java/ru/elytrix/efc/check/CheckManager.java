package ru.elytrix.efc.check;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.checks.combat.AccuracyA;
import ru.elytrix.efc.checks.combat.AccuracyB;
import ru.elytrix.efc.checks.combat.AccuracyC;
import ru.elytrix.efc.checks.combat.AimA;
import ru.elytrix.efc.checks.combat.AimB;
import ru.elytrix.efc.checks.combat.AimC;
import ru.elytrix.efc.checks.combat.AimD;
import ru.elytrix.efc.checks.combat.AimE;
import ru.elytrix.efc.checks.combat.AimF;
import ru.elytrix.efc.checks.combat.AutoClickerA;
import ru.elytrix.efc.checks.combat.AutoClickerB;
import ru.elytrix.efc.checks.combat.AutoClickerC;
import ru.elytrix.efc.checks.combat.AutoClickerD;
import ru.elytrix.efc.checks.combat.CriticalsA;
import ru.elytrix.efc.checks.combat.FastBowA;
import ru.elytrix.efc.checks.combat.FastEatA;
import ru.elytrix.efc.checks.combat.HitBoxA;
import ru.elytrix.efc.checks.combat.KillAuraA;
import ru.elytrix.efc.checks.combat.KillAuraB;
import ru.elytrix.efc.checks.combat.KillAuraC;
import ru.elytrix.efc.checks.combat.KillAuraD;
import ru.elytrix.efc.checks.combat.KillAuraE;
import ru.elytrix.efc.checks.combat.KillAuraF;
import ru.elytrix.efc.checks.combat.KillAuraG;
import ru.elytrix.efc.checks.combat.ReachA;
import ru.elytrix.efc.checks.combat.ReachB;
import ru.elytrix.efc.checks.combat.VelocityA;
import ru.elytrix.efc.checks.movement.FlyA;
import ru.elytrix.efc.checks.movement.FlyB;
import ru.elytrix.efc.checks.movement.NoFallB;
import ru.elytrix.efc.checks.movement.SpeedA;
import ru.elytrix.efc.checks.movement.SpeedB;
import ru.elytrix.efc.checks.movement.TimerA;

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
        register(new KillAuraD(plugin));
        register(new KillAuraE(plugin));
        register(new KillAuraF(plugin));
        register(new KillAuraG(plugin));
        register(new ReachA(plugin));
        register(new ReachB(plugin));
        register(new AutoClickerA(plugin));
        register(new AutoClickerB(plugin));
        register(new AutoClickerC(plugin));
        register(new AutoClickerD(plugin));
        register(new AimA(plugin));
        register(new AimB(plugin));
        register(new AimC(plugin));
        register(new AimD(plugin));
        register(new AimE(plugin));
        register(new AimF(plugin));
        register(new AccuracyA(plugin));
        register(new AccuracyB(plugin));
        register(new AccuracyC(plugin));
        register(new CriticalsA(plugin));
        register(new VelocityA(plugin));
        register(new FastBowA(plugin));
        register(new FastEatA(plugin));
        register(new HitBoxA(plugin));
        register(new FlyA(plugin));
        register(new SpeedA(plugin));
        register(new TimerA(plugin));
        register(new SpeedB(plugin));
        register(new FlyB(plugin));
        register(new NoFallB(plugin));
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

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
import ru.elytrix.efc.checks.exploit.CrashA;
import ru.elytrix.efc.checks.exploit.CrashB;
import ru.elytrix.efc.checks.exploit.CrashC;
import ru.elytrix.efc.checks.exploit.CrashD;
import ru.elytrix.efc.checks.exploit.CrashE;
import ru.elytrix.efc.checks.exploit.CrashF;
import ru.elytrix.efc.checks.exploit.CrashH;
import ru.elytrix.efc.checks.exploit.ExploitA;
import ru.elytrix.efc.checks.movement.FlyA;
import ru.elytrix.efc.checks.movement.FlyB;
import ru.elytrix.efc.checks.movement.GroundSpoofA;
import ru.elytrix.efc.checks.movement.JesusA;
import ru.elytrix.efc.checks.movement.NoFallB;
import ru.elytrix.efc.checks.movement.NoSlowA;
import ru.elytrix.efc.checks.movement.PhaseA;
import ru.elytrix.efc.checks.movement.SpeedA;
import ru.elytrix.efc.checks.movement.SpeedB;
import ru.elytrix.efc.checks.movement.SprintA;
import ru.elytrix.efc.checks.movement.SprintC;
import ru.elytrix.efc.checks.movement.SprintD;
import ru.elytrix.efc.checks.movement.StepA;
import ru.elytrix.efc.checks.movement.TimerA;
import ru.elytrix.efc.checks.movement.TimerB;
import ru.elytrix.efc.checks.movement.TimerC;
import ru.elytrix.efc.checks.world.FarBreakA;
import ru.elytrix.efc.checks.world.FarPlaceA;
import ru.elytrix.efc.checks.world.FastBreakA;
import ru.elytrix.efc.checks.world.FastBreakB;
import ru.elytrix.efc.checks.world.InvalidPlaceA;
import ru.elytrix.efc.checks.world.NoSwingBreak;
import ru.elytrix.efc.checks.world.NukerA;
import ru.elytrix.efc.checks.world.PositionPlaceA;
import ru.elytrix.efc.checks.world.RotationBreakA;
import ru.elytrix.efc.checks.world.RotationPlaceA;
import ru.elytrix.efc.checks.world.ScaffoldA;
import ru.elytrix.efc.checks.world.ScaffoldB;

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
        register(new NukerA(plugin));
        register(new ScaffoldA(plugin));
        register(new FarBreakA(plugin));
        register(new FarPlaceA(plugin));
        register(new RotationBreakA(plugin));
        register(new RotationPlaceA(plugin));
        register(new InvalidPlaceA(plugin));
        register(new PositionPlaceA(plugin));
        register(new NoSlowA(plugin));
        register(new JesusA(plugin));
        register(new StepA(plugin));
        register(new PhaseA(plugin));
        register(new GroundSpoofA(plugin));
        register(new FastBreakA(plugin));
        register(new TimerB(plugin));
        register(new TimerC(plugin));
        register(new SprintA(plugin));
        register(new SprintC(plugin));
        register(new SprintD(plugin));
        register(new CrashA(plugin));
        register(new CrashB(plugin));
        register(new CrashC(plugin));
        register(new CrashD(plugin));
        register(new CrashE(plugin));
        register(new CrashF(plugin));
        register(new CrashH(plugin));
        register(new ExploitA(plugin));
        register(new FastBreakB(plugin));
        register(new NoSwingBreak(plugin));
        register(new ScaffoldB(plugin));
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

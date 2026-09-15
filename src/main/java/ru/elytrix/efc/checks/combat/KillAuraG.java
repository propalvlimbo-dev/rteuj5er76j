package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.G: машинный ритм ударов (семейство Hawk FightSpeedConsistency).
 * Аура бьёт строго по кулдауну: разброс 20 интервалов меньше 12 мс.
 * Живая рука так не может — джиттер 25+ мс даже у топов, серверный
 * лаг только добавляет разброса (ложным взяться неоткуда).
 * Мульти-урон в один тик пропускаем, пауза &gt;3 с сбрасывает серию.
 * Удар в прыжке сбрасывает серию: джамп-криты легита — метроном физики.
 */
public final class KillAuraG extends Check {

    private static final class State {
        final Deque<Long> intervals = new ArrayDeque<>();
        long lastHit;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraG(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "G", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        long now = System.currentTimeMillis();
        boolean airborne;
        try {
            airborne = !attacker.isOnGround();
        } catch (Throwable ignored) {
            airborne = false;
        }
        if (airborne) {
            // Крит/удар в прыжке: ритм задаёт физика прыжка, а не аура.
            state.intervals.clear();
            state.lastHit = now;
            return;
        }
        if (state.lastHit > 0) {
            long dt = now - state.lastHit;
            if (dt > 3000) {
                state.intervals.clear();
            } else if (dt >= 50) {
                state.intervals.addLast(dt);
                while (state.intervals.size() > 20) {
                    state.intervals.removeFirst();
                }
                if (state.intervals.size() >= 20) {
                    double mean = 0;
                    for (long interval : state.intervals) {
                        mean += interval;
                    }
                    mean /= state.intervals.size();
                    double variance = 0;
                    for (long interval : state.intervals) {
                        double diff = interval - mean;
                        variance += diff * diff;
                    }
                    variance /= state.intervals.size();
                    if (Math.sqrt(variance) < cfg("max-stddev-ms", 12)) {
                        flag(plugin.getDataManager().get(attacker), "rhythm");
                    }
                }
            }
        }
        state.lastHit = now;
    }
}

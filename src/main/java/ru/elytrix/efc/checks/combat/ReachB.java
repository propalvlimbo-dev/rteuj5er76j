package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Reach.B: средняя дистанция ударов за 25 попаданий.
 * Ловит аккуратный рич 3.1–3.5, который пропускает Reach.A.
 * Лаговые выбросы тонут в среднем — честный средний ~2.6–2.9.
 */
public final class ReachB extends Check {

    private static final class State {
        int count;
        double sum;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public ReachB(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "B", Category.COMBAT);
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
        Entity victim = DamageUtil.entityOf(event);
        if (victim == null) {
            return;
        }
        double distance = attacker.getLocation().distance(victim.getLocation());
        if (distance > 5.5) {
            // Единичный глюк/телепорт — не портим статистику.
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        state.count++;
        state.sum += distance;
        if (state.count < 25) {
            return;
        }
        double average = state.sum / state.count;
        state.count = 0;
        state.sum = 0;
        double max = DamageUtil.reachLimit(attacker, victim,
                cfg("base", 3.0), cfg("per-ms", 0.0025), cfg("cap", 4.0));
        if (average > max) {
            flag(plugin.getDataManager().get(attacker), "avg " + String.format("%.2f", average));
        }
    }
}

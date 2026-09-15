package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerAnimationEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Accuracy.B: длинная точность (расширение идеи NESS KillauraHitMissRatio).
 * 90 взмахов, хит только по той же цели подряд, планка 88%.
 * Рабочая зона джиттер-аур (SpookyTime и ко): мажут чаще грубых,
 * но точнее любой живой руки на дистанции. Оба двигаются, только игроки.
 * Уверенность — только серией: 3 окна подряд = x5, 5 = x20 (кик).
 * Чистое окно, сомнения и пауза 5 мин обнуляют серию.
 */
public final class AccuracyB extends Check {

    private static final class State {
        int swings;
        int hits;
        double moved;
        int streak;
        long lastEval;
        UUID lastVictim;
        double victimStartOdo;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();
    private final Map<UUID, Double> odometer = new ConcurrentHashMap<>();

    public AccuracyB(ElytrixFuckCheats plugin) {
        super(plugin, "Accuracy", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
        odometer.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        double dist = Math.sqrt(dx * dx + dz * dz);
        UUID uuid = event.getPlayer().getUniqueId();
        states.computeIfAbsent(uuid, key -> new State()).moved += dist;
        odometer.merge(uuid, dist, Double::sum);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        state.swings++;
        if (state.swings < 90) {
            return;
        }
        long now = System.currentTimeMillis();
        int swings = state.swings;
        int hits = state.hits;
        double moved = state.moved;
        UUID victim = state.lastVictim;
        double victimMoved = victim == null
                ? 0 : odometer.getOrDefault(victim, 0.0) - state.victimStartOdo;
        state.swings = 0;
        state.hits = 0;
        state.moved = 0;
        state.lastVictim = null;
        state.victimStartOdo = 0;
        if (now - state.lastEval > 300000) {
            state.streak = 0;
        }
        state.lastEval = now;
        if (moved <= 4.0 || victimMoved <= 2.5) {
            state.streak = 0;
            return;
        }
        double ratio = (double) hits / swings;
        if (ratio >= 0.88 && ratio <= 1.0) {
            streakFlag(player, state, Math.round(ratio * 100) + "% " + swings);
        } else {
            state.streak = 0;
        }
    }

    private void streakFlag(Player player, State state, String details) {
        state.streak++;
        double mult = state.streak >= 5 ? 20.0 : state.streak >= 3 ? 5.0 : 1.0;
        flag(plugin.getDataManager().get(player),
                details + (state.streak >= 2 ? " x" + state.streak : ""), mult);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        UUID victim = DamageUtil.victimId(event);
        if (victim == null || !(DamageUtil.entityOf(event) instanceof Player)) {
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        if (victim.equals(state.lastVictim)) {
            state.hits++;
        } else {
            state.lastVictim = victim;
            state.victimStartOdo = odometer.getOrDefault(victim, 0.0);
        }
    }
}

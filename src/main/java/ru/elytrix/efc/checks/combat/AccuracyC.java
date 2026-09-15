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
 * Accuracy.C: быстрая точность (та же идея NESS KillauraHitMissRatio).
 * 20 взмахов, все в цель — первый ответ уже через ~15 сек боя.
 * Окно живёт 60 сек: рваное пвп (2 удара тут, 2 там) считается
 * взмахами, а не позицией, старые взмахи протухают.
 * Уверенность — только серией: 3 окна подряд = x5, 5 = x20 (кик).
 * Чистое окно, сомнения и пауза 5 мин обнуляют серию.
 */
public final class AccuracyC extends Check {

    private static final class State {
        int swings;
        int hits;
        double moved;
        int streak;
        long lastEval;
        long windowStart;
        UUID lastVictim;
        double victimStartOdo;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();
    private final Map<UUID, Double> odometer = new ConcurrentHashMap<>();

    public AccuracyC(ElytrixFuckCheats plugin) {
        super(plugin, "Accuracy", "C", Category.COMBAT);
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
        long now = System.currentTimeMillis();
        if (state.swings == 0) {
            state.windowStart = now;
        } else if (now - state.windowStart > 60000) {
            state.swings = 0;
            state.hits = 0;
            state.moved = 0;
            state.lastVictim = null;
            state.victimStartOdo = 0;
            state.windowStart = now;
        }
        state.swings++;
        if (state.swings < 20) {
            return;
        }
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
        if (moved <= 3.0 || victimMoved <= 2.0) {
            state.streak = 0;
            return;
        }
        if (hits >= swings - 1) {
            streakFlag(player, state, hits + "/" + swings);
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

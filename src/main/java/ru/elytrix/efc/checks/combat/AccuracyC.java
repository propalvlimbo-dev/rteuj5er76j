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
 * Слабый сигнал: один флаг ничего не решает, подтверждение — A/B.
 * Позиции не важны, работает и в подвижном бою. Оба двигаются.
 */
public final class AccuracyC extends Check {

    private static final class State {
        int swings;
        int hits;
        double moved;
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
        if (moved <= 3.0 || victimMoved <= 2.0) {
            return;
        }
        if (hits >= swings - 1) {
            flag(plugin.getDataManager().get(player), hits + "/" + swings);
        }
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

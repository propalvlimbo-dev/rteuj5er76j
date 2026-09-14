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
 * Accuracy.A: процент попаданий (логика NESS KillauraHitMissRatio).
 * 60 взмахов, хит засчитывается только по той же цели подряд,
 * атакующий должен двигаться. Порог 95–100%. Плюс наше: только по игрокам.
 */
public final class AccuracyA extends Check {

    private static final class State {
        int swings;
        int hits;
        double moved;
        UUID lastVictim;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AccuracyA(ElytrixFuckCheats plugin) {
        super(plugin, "Accuracy", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        State state = states.computeIfAbsent(event.getPlayer().getUniqueId(), key -> new State());
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        state.moved += Math.sqrt(dx * dx + dz * dz);
    }

    @EventHandler
    public void onAnimation(PlayerAnimationEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        state.swings++;
        if (state.swings < 60) {
            return;
        }
        int swings = state.swings;
        int hits = state.hits;
        double moved = state.moved;
        state.swings = 0;
        state.hits = 0;
        state.moved = 0;
        state.lastVictim = null;
        if (moved <= 3.0) {
            return;
        }
        double ratio = (double) hits / swings;
        if (ratio >= 0.95 && ratio <= 1.0) {
            flag(plugin.getDataManager().get(player), Math.round(ratio * 100) + "% " + swings);
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
        }
        state.lastVictim = victim;
    }
}

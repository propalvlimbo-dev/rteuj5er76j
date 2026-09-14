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
 * Accuracy.A: 100% попаданий по игрокам за 40+ взмахов в активном бою.
 * Триггерботы и хитбоксы почти не мажут. Фарм стоя на месте (АФК-мобы)
 * не считается — требуем движение атакующего.
 */
public final class AccuracyA extends Check {

    private static final class State {
        int swings;
        int hits;
        long windowStart;
        double moved;
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
        long now = System.currentTimeMillis();
        if (state.windowStart == 0) {
            state.windowStart = now;
        }
        if (now - state.windowStart >= 10000) {
            int swings = state.swings;
            int hits = state.hits;
            double moved = state.moved;
            state.swings = 0;
            state.hits = 0;
            state.moved = 0;
            state.windowStart = now;
            if (swings >= 40 && moved > 3.0) {
                double ratio = (double) hits / swings;
                if (ratio >= 0.98 && ratio <= 1.0) {
                    flag(plugin.getDataManager().get(player), "100% " + swings);
                    return;
                }
            }
        }
        state.swings++;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null || !(event.getEntity() instanceof Player)) {
            return;
        }
        State state = states.computeIfAbsent(attacker.getUniqueId(), key -> new State());
        state.hits++;
    }
}

package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Velocity.A: анти-нокбэк — игрока бьют, а он стоит как вкопанный.
 * После удара меряем смещение за 250+ мс. Нужно 5 таких случаев подряд.
 * Стены дают редкие ложные «ноль-смещения» — серия из 5 почти невозможна.
 */
public final class VelocityA extends Check {

    private static final class State {
        boolean pending;
        double hurtX;
        double hurtZ;
        long hurtTime;
        int takes;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public VelocityA(ElytrixFuckCheats plugin) {
        super(plugin, "Velocity", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getEntity() instanceof Player)) {
            return;
        }
        if (DamageUtil.meleeAttacker(event) == null || event.getDamage() < 1.0) {
            return;
        }
        Player victim = (Player) event.getEntity();
        State state = states.computeIfAbsent(victim.getUniqueId(), key -> new State());
        Location location = victim.getLocation();
        state.pending = true;
        state.hurtX = location.getX();
        state.hurtZ = location.getZ();
        state.hurtTime = System.currentTimeMillis();
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.get(player.getUniqueId());
        if (state == null || !state.pending) {
            return;
        }
        long elapsed = System.currentTimeMillis() - state.hurtTime;
        if (elapsed < 250) {
            return;
        }
        state.pending = false;
        if (elapsed > 800) {
            return;
        }
        double dx = event.getTo().getX() - state.hurtX;
        double dz = event.getTo().getZ() - state.hurtZ;
        if (Math.sqrt(dx * dx + dz * dz) < 0.15) {
            state.takes++;
            if (state.takes >= 5) {
                state.takes = 0;
                flag(plugin.getDataManager().get(player), "no-kb");
            }
        } else {
            state.takes = Math.max(0, state.takes - 2);
        }
    }
}

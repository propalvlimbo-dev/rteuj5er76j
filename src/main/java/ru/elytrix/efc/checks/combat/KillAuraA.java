package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * KillAura.A: доворот-снап прямо перед ударом.
 * Аура дёргает голову на цель и тут же бьёт. Живой игрок так не умеет:
 * резкий доворот >150° за один пакет + удар в пределах 150 мс = чит.
 */
public final class KillAuraA extends Check {

    private static final class State {
        double lastYaw;
        double lastPitch;
        boolean hasLast;
        double lastSnap;
        long lastSnapTime;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraA(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        double yaw = event.getTo().getYaw();
        double pitch = event.getTo().getPitch();
        if (state.hasLast) {
            double snap = Math.max(yawDelta(state.lastYaw, yaw), Math.abs(state.lastPitch - pitch));
            state.lastSnap = snap;
            state.lastSnapTime = System.currentTimeMillis();
        }
        state.lastYaw = yaw;
        state.lastPitch = pitch;
        state.hasLast = true;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getDamager();
        State state = states.get(player.getUniqueId());
        if (state == null || !state.hasLast) {
            return;
        }
        // Снап должен быть прямо перед ударом, иначе это просто резкий поворот.
        if (System.currentTimeMillis() - state.lastSnapTime > 150) {
            return;
        }
        if (state.lastSnap >= cfg("snap-degrees", 150.0)) {
            flag(plugin.getDataManager().get(player), "snap " + Math.round(state.lastSnap) + "deg");
        }
    }

    private static double yawDelta(double from, double to) {
        double delta = Math.abs(from - to) % 360.0;
        return delta > 180.0 ? 360.0 - delta : delta;
    }
}

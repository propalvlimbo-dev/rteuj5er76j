package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Speed.B: горизонталь за один тик движения.
 * Легитные потолки: земля 0.24/спринт 0.31, воздух 0.30/спринт-прыжки 0.43,
 * лёд 0.80, зелье скорости масштабирует как в ванилле.
 * Вода, паутина, лестницы, откидывание — пропуск.
 */
public final class SpeedB extends Check {

    private final Map<UUID, Long> lastAlert = new ConcurrentHashMap<>();

    public SpeedB(ElytrixFuckCheats plugin) {
        super(plugin, "Speed", "B", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastAlert.remove(uuid);
    }

    @EventHandler
    public void onVelocity(PlayerVelocityEvent event) {
        try {
            MovementUtil.noteVelocity(event.getPlayer().getUniqueId());
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || MovementUtil.cantCheck(player)) {
            return;
        }
        UUID id = player.getUniqueId();
        if (MovementUtil.velocityRecent(id)) {
            return;
        }
        Material feet = MovementUtil.feetType(player);
        if (MovementUtil.isLiquid(feet) || MovementUtil.isWeb(feet)) {
            return;
        }
        if (MovementUtil.isClimbable(feet)) {
            return;
        }
        if (event.getFrom() == null || event.getTo() == null) {
            return;
        }
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        double step = Math.sqrt(dx * dx + dz * dz);
        if (step < 0.01 || step > 8) {
            return;
        }
        Material below = MovementUtil.belowType(player);
        if (MovementUtil.isClimbable(below) || MovementUtil.isSlowGround(below)) {
            return;
        }
        double limit;
        if (player.isOnGround()) {
            limit = player.isSprinting() ? 0.31 : 0.24;
        } else {
            limit = player.isSprinting() ? 0.43 : 0.30;
        }
        int speedAmp = MovementUtil.effectAmplifier(player, PotionEffectType.SPEED);
        if (speedAmp >= 0) {
            limit *= 1.0 + 0.2 * (speedAmp + 1);
        }
        if (MovementUtil.isIce(below)) {
            limit = Math.max(limit, 0.80);
        }
        if (step <= limit) {
            return;
        }
        long now = System.currentTimeMillis();
        Long last = lastAlert.get(id);
        if (last != null && now - last < 250) {
            return;
        }
        lastAlert.put(id, now);
        flag(plugin.getDataManager().get(player),
                String.format("dxz=%.3f limit=%.3f", step, limit));
    }
}

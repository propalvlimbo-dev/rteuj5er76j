package ru.elytrix.efc.checks.movement;

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
 * NoSlow.A: крадучись или со щитом быстрее 0.22/тик по земле.
 * Легит: sneak/shield ~0.13, зелье скорости масштабирует.
 * Воздух, лёд, вода, лестницы — пропуск.
 */
public final class NoSlowA extends Check {

    public NoSlowA(ElytrixFuckCheats plugin) {
        super(plugin, "NoSlow", "A", Category.MOVEMENT);
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
        if (MovementUtil.velocityRecent(player.getUniqueId())) {
            return;
        }
        boolean slowed;
        try {
            slowed = player.isSneaking() || player.isBlocking();
        } catch (Throwable ignored) {
            return;
        }
        if (!slowed) {
            return;
        }
        if (!player.isOnGround()) {
            return;
        }
        Material feet = MovementUtil.feetType(player);
        if (MovementUtil.isLiquid(feet) || MovementUtil.isWeb(feet)) {
            return;
        }
        if (MovementUtil.isClimbable(feet)) {
            return;
        }
        if (MovementUtil.isIce(MovementUtil.belowType(player))) {
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
        double limit = 0.22;
        int speedAmp = MovementUtil.effectAmplifier(player, PotionEffectType.SPEED);
        if (speedAmp >= 0) {
            limit *= 1.0 + 0.2 * (speedAmp + 1);
        }
        if (step > limit) {
            flag(plugin.getDataManager().get(player), String.format("dxz=%.3f", step));
        }
    }
}

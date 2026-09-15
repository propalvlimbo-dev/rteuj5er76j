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
 * Step.A: подъём выше 0.6 за одно движение.
 * Прыжок 0.42, ступени/плиты 0.5 — мимо. Джамп-буст расширяет лимит,
 * слизь/кровати/левитация/вода — пропуск.
 */
public final class StepA extends Check {

    public StepA(ElytrixFuckCheats plugin) {
        super(plugin, "Step", "A", Category.MOVEMENT);
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
        Material feet = MovementUtil.feetType(player);
        Material below = MovementUtil.belowType(player);
        if (MovementUtil.isBounceSafe(feet) || MovementUtil.isBounceSafe(below)) {
            return;
        }
        if (MovementUtil.isLiquid(feet) || MovementUtil.isLiquid(below)) {
            return;
        }
        if (MovementUtil.isClimbable(feet) || MovementUtil.isClimbable(below)) {
            return;
        }
        if (MovementUtil.effectAmplifier(player, PotionEffectType.LEVITATION) >= 0
                || MovementUtil.effectAmplifier(player, PotionEffectType.SLOW_FALLING) >= 0) {
            return;
        }
        if (event.getFrom() == null || event.getTo() == null) {
            return;
        }
        double dy = event.getTo().getY() - event.getFrom().getY();
        if (dy <= 0.6) {
            return;
        }
        double limit = 0.6;
        int jumpAmp = MovementUtil.effectAmplifier(player, PotionEffectType.JUMP);
        if (jumpAmp >= 0) {
            limit = 0.6 + (jumpAmp + 1) * 0.15;
        }
        if (dy > limit) {
            flag(plugin.getDataManager().get(player), String.format("step=%.2f", dy));
        }
    }
}

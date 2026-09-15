package ru.elytrix.efc.checks.movement;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerToggleSprintEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Sprint.D: старт спринта со слепотой (Grim SprintD).
 * Слепой стартовать не может; судим только момент старта.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit.
 */
public final class SprintD extends Check {

    public SprintD(ElytrixFuckCheats plugin) {
        super(plugin, "Sprint", "D", Category.MOVEMENT);
    }

    @EventHandler
    public void onToggle(PlayerToggleSprintEvent event) {
        if (!event.isSprinting()) {
            return;
        }
        Player player = event.getPlayer();
        if (player == null || MovementUtil.cantCheck(player)) {
            return;
        }
        if (MovementUtil.effectAmplifier(player, PotionEffectType.BLINDNESS) >= 0) {
            flag(plugin.getDataManager().get(player), "blind-sprint");
        }
    }
}

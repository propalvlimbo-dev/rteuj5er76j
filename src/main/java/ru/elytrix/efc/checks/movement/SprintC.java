package ru.elytrix.efc.checks.movement;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Sprint.C: спринт с поднятым щитом (по мотивам Grim SprintC).
 * Блок гасит спринт на сервере; связка дольше пары движений — чит.
 * Портировано из Grim (GPL-3.0), адаптировано под Bukkit.
 */
public final class SprintC extends Check {

    public SprintC(ElytrixFuckCheats plugin) {
        super(plugin, "Sprint", "C", Category.MOVEMENT);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null || MovementUtil.cantCheck(player)) {
            return;
        }
        boolean sprinting;
        boolean blocking;
        try {
            sprinting = player.isSprinting();
            blocking = player.isBlocking();
        } catch (Throwable ignored) {
            return;
        }
        if (sprinting && blocking) {
            flag(plugin.getDataManager().get(player), "shield-sprint");
        }
    }
}

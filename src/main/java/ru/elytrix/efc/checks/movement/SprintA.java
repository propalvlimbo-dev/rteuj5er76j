package ru.elytrix.efc.checks.movement;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Sprint.A: спринт при голоде 6 и ниже (Grim SprintA).
 * Ванилла такой спринт запрещает. Полёт и транспорт — пропуск.
 * Портировано из Grim (GPL-3.0).
 */
public final class SprintA extends Check {

    public SprintA(ElytrixFuckCheats plugin) {
        super(plugin, "Sprint", "A", Category.MOVEMENT);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        boolean sprinting;
        try {
            sprinting = player.isSprinting();
        } catch (Throwable ignored) {
            return;
        }
        if (!sprinting) {
            return;
        }
        if (player.getAllowFlight() || player.isInsideVehicle()) {
            return;
        }
        int food;
        try {
            food = player.getFoodLevel();
        } catch (Throwable ignored) {
            return;
        }
        if (food <= 6) {
            flag(plugin.getDataManager().get(player), "hunger=" + food);
        }
    }
}

package ru.elytrix.efc.checks.world;

import java.util.UUID;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockPlaceEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.MovementUtil;

/**
 * InvalidPlace.A: опора установки — чистый воздух.
 * Установка в воду/лаву/снег/траву честна (опора не воздух).
 * Связка «сломал+поставил в том же тике» прикрыта грейсом 200 мс.
 */
public final class InvalidPlaceA extends Check {

    public InvalidPlaceA(ElytrixFuckCheats plugin) {
        super(plugin, "InvalidPlace", "A", Category.WORLD);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        Block against = event.getBlockAgainst();
        if (player == null || against == null) {
            return;
        }
        UUID id = player.getUniqueId();
        boolean air;
        try {
            air = BlockUtil.isAir(against.getType());
        } catch (Throwable ignored) {
            return;
        }
        if (!air) {
            return;
        }
        if (BlockUtil.brokeWithin(id, 200)) {
            return;
        }
        if (MovementUtil.cantCheck(player)) {
            return;
        }
        event.setCancelled(true);
        flag(plugin.getDataManager().get(player), "against=air");
    }
}

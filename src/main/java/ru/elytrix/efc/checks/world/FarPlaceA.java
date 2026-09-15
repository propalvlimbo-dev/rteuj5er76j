package ru.elytrix.efc.checks.world;

import org.bukkit.Material;
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
 * FarPlace.A: установка в блок дальше 6 от глаз.
 * Строительные леса пропускаем — у них особая дальность.
 */
public final class FarPlaceA extends Check {

    public FarPlaceA(ElytrixFuckCheats plugin) {
        super(plugin, "FarPlace", "A", Category.WORLD);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        Block against = event.getBlockAgainst();
        if (player == null || against == null) {
            return;
        }
        try {
            Block placed = event.getBlockPlaced();
            if (placed != null && placed.getType() == Material.SCAFFOLDING) {
                return;
            }
        } catch (Throwable ignored) {
            return;
        }
        if (MovementUtil.cantCheck(player)) {
            return;
        }
        double dist;
        try {
            dist = BlockUtil.eyeToBlockDistance(player.getLocation(), against);
        } catch (Throwable ignored) {
            return;
        }
        if (dist > 6.0) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), String.format("dist=%.2f", dist));
        }
    }
}

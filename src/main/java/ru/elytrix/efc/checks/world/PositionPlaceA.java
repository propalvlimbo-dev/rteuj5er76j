package ru.elytrix.efc.checks.world;

import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.block.BlockFace;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockPlaceEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.MovementUtil;

/**
 * PositionPlace.A: клик в грань с невозможной стороны
 * (например, в верхнюю грань, стоя ниже блока). Допуск 0.25.
 */
public final class PositionPlaceA extends Check {

    public PositionPlaceA(ElytrixFuckCheats plugin) {
        super(plugin, "PositionPlace", "A", Category.WORLD);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        Player player = event.getPlayer();
        Block against = event.getBlockAgainst();
        if (player == null || against == null) {
            return;
        }
        BlockFace face;
        try {
            face = event.getBlockFace();
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
        Location feet;
        try {
            feet = player.getLocation();
        } catch (Throwable ignored) {
            return;
        }
        if (BlockUtil.eyeInsideBlock(feet, against, 0.05)) {
            return;
        }
        if (!BlockUtil.faceReachable(feet, against, face, 0.25)) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), "face=" + face);
        }
    }
}

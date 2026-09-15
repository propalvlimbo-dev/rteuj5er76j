package ru.elytrix.efc.checks.world;

import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockBreakEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.MovementUtil;

/**
 * FarBreak.A: слом дальше 6 блоков от глаз (ближайшая точка куба).
 * Выживание дотягивается на 4.5, +1.5 запаса на лаг и десинк.
 */
public final class FarBreakA extends Check {

    public FarBreakA(ElytrixFuckCheats plugin) {
        super(plugin, "FarBreak", "A", Category.WORLD);
    }

    @EventHandler
    public void onBreak(BlockBreakEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) {
            return;
        }
        BlockUtil.noteBreak(player.getUniqueId());
        if (MovementUtil.cantCheck(player)) {
            return;
        }
        double dist;
        try {
            dist = BlockUtil.eyeToBlockDistance(player.getLocation(), block);
        } catch (Throwable ignored) {
            return;
        }
        if (dist > 6.0) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(player), String.format("dist=%.2f", dist));
        }
    }
}

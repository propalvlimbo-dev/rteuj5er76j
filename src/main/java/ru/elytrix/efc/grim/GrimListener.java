package ru.elytrix.efc.grim;

import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockDamageEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.player.PlayerMoveEvent;

/**
 * Единственный Bukkit-слушатель Grim-моста (регистрируется один раз).
 */
public final class GrimListener implements Listener {

    public static final GrimListener INSTANCE = new GrimListener();

    private GrimListener() {
    }

    @EventHandler
    public void onDamage(BlockDamageEvent event) {
        GrimBridge.onBlockDamage(event);
    }

    @EventHandler
    public void onBreak(BlockBreakEvent event) {
        GrimBridge.onBlockBreak(event);
    }

    @EventHandler
    public void onPlace(BlockPlaceEvent event) {
        GrimBridge.onBlockPlace(event);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player != null) {
            GrimBridge.onBukkitMove(player);
        }
    }
}

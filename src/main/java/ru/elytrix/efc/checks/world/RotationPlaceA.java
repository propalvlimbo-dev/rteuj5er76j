package ru.elytrix.efc.checks.world;

import java.util.UUID;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.util.Vector;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.packet.PacketData;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.MovementUtil;

/**
 * RotationPlace.A: установка в блок, в который пакетный взгляд не попадает.
 * Главный детект сакффолда без взгляда. Без PacketEvents тихо спит.
 */
public final class RotationPlaceA extends Check {

    private static final double[] EYE_HEIGHTS = {1.62, 1.27};

    public RotationPlaceA(ElytrixFuckCheats plugin) {
        super(plugin, "RotationPlace", "A", Category.WORLD);
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
        UUID id = player.getUniqueId();
        long now = System.currentTimeMillis();
        PacketData packets = plugin.getPacketManager().get(id);
        if (!packets.hasRecentFlying(now, 2000)) {
            return;
        }
        Location feet;
        try {
            feet = player.getLocation();
        } catch (Throwable ignored) {
            return;
        }
        if (BlockUtil.eyeInsideBlock(feet, against, 0.1)) {
            return;
        }
        Vector dir = CombatGeometry.dirFromYawPitch(packets.getLastYaw(), packets.getLastPitch());
        for (double h : EYE_HEIGHTS) {
            Vector origin = new Vector(feet.getX(), feet.getY() + h, feet.getZ());
            if (BlockUtil.rayHitsBlock(origin, dir, against, 0.2, 6.5)) {
                return;
            }
        }
        flag(plugin.getDataManager().get(player), "no-look place");
    }
}

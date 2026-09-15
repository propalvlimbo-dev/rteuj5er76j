package ru.elytrix.efc.checks.world;

import java.util.UUID;
import org.bukkit.Location;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.util.Vector;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.packet.PacketData;
import ru.elytrix.efc.util.BlockUtil;
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.MovementUtil;

/**
 * RotationBreak.A: слом блока, в который пакетный взгляд не попадает.
 * Луч из глаз (обе высоты) по последнему yaw/pitch из Flying-пакета
 * в куб блока +0.2. Без PacketEvents тихо спит.
 */
public final class RotationBreakA extends Check {

    private static final double[] EYE_HEIGHTS = {1.62, 1.27};

    public RotationBreakA(ElytrixFuckCheats plugin) {
        super(plugin, "RotationBreak", "A", Category.WORLD);
    }

    @EventHandler
    public void onBreak(BlockBreakEvent event) {
        Player player = event.getPlayer();
        Block block = event.getBlock();
        if (player == null || block == null) {
            return;
        }
        UUID id = player.getUniqueId();
        BlockUtil.noteBreak(id);
        if (MovementUtil.cantCheck(player)) {
            return;
        }
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
        if (BlockUtil.eyeInsideBlock(feet, block, 0.1)) {
            return;
        }
        Vector dir = CombatGeometry.dirFromYawPitch(packets.getLastYaw(), packets.getLastPitch());
        for (double h : EYE_HEIGHTS) {
            Vector origin = new Vector(feet.getX(), feet.getY() + h, feet.getZ());
            if (BlockUtil.rayHitsBlock(origin, dir, block, 0.2, 6.5)) {
                return;
            }
        }
        event.setCancelled(true);
        flag(plugin.getDataManager().get(player), "no-look break");
    }
}

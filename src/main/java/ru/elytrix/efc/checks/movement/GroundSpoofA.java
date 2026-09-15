package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.packet.PacketData;
import ru.elytrix.efc.util.MovementUtil;

/**
 * GroundSpoof.A: клиент 30+ движений подряд врёт «стою на земле»,
 * а сервер видит воздух. Данные о земле — из свежих Flying-пакетов.
 * Без PacketEvents тихо спит.
 */
public final class GroundSpoofA extends Check {

    private final Map<UUID, Integer> bad = new ConcurrentHashMap<>();

    public GroundSpoofA(ElytrixFuckCheats plugin) {
        super(plugin, "GroundSpoof", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        bad.remove(uuid);
    }

    @EventHandler
    public void onVelocity(PlayerVelocityEvent event) {
        try {
            MovementUtil.noteVelocity(event.getPlayer().getUniqueId());
        } catch (Throwable ignored) {
        }
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        if (MovementUtil.cantCheck(player) || MovementUtil.velocityRecent(id)) {
            bad.remove(id);
            return;
        }
        Material feet = MovementUtil.feetType(player);
        Material below = MovementUtil.belowType(player);
        if (MovementUtil.isLiquid(feet) || MovementUtil.isLiquid(below)) {
            bad.remove(id);
            return;
        }
        if (MovementUtil.isWeb(feet) || MovementUtil.isWeb(below)) {
            bad.remove(id);
            return;
        }
        if (MovementUtil.isClimbable(feet) || MovementUtil.isClimbable(below)) {
            bad.remove(id);
            return;
        }
        if (MovementUtil.isBounceSafe(feet) || MovementUtil.isBounceSafe(below)) {
            bad.remove(id);
            return;
        }
        if (MovementUtil.effectAmplifier(player, PotionEffectType.LEVITATION) >= 0
                || MovementUtil.effectAmplifier(player, PotionEffectType.SLOW_FALLING) >= 0) {
            bad.remove(id);
            return;
        }
        long now = System.currentTimeMillis();
        PacketData packets = plugin.getPacketManager().get(id);
        if (!packets.hasRecentFlying(now, 500)) {
            bad.remove(id);
            return;
        }
        boolean clientGround = packets.getLastGround();
        boolean serverGround;
        try {
            serverGround = player.isOnGround();
        } catch (Throwable ignored) {
            bad.remove(id);
            return;
        }
        if (clientGround && !serverGround) {
            int count = bad.getOrDefault(id, 0) + 1;
            bad.put(id, count);
            if (count >= 30) {
                bad.remove(id);
                flag(plugin.getDataManager().get(player), "spoof=" + count + "t");
            }
            return;
        }
        bad.remove(id);
    }
}

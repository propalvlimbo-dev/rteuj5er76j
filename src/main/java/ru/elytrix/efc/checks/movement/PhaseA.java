package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.MovementUtil;

/**
 * Phase.A: движение, где начало И конец внутри твёрдых блоков.
 * Углы дверей и выход из блока (одна точка в воздухе) — мимо.
 * Троттлинг 1 флаг/250 мс: случайный клип сгорит, фазер долетит до кика.
 */
public final class PhaseA extends Check {

    private final Map<UUID, Long> lastAlert = new ConcurrentHashMap<>();

    public PhaseA(ElytrixFuckCheats plugin) {
        super(plugin, "Phase", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        lastAlert.remove(uuid);
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
        if (player == null || MovementUtil.cantCheck(player)) {
            return;
        }
        UUID id = player.getUniqueId();
        if (MovementUtil.velocityRecent(id)) {
            return;
        }
        Material feet = MovementUtil.feetType(player);
        if (MovementUtil.isLiquid(feet) || MovementUtil.isWeb(feet)) {
            return;
        }
        if (MovementUtil.isClimbable(feet)) {
            return;
        }
        Location from = event.getFrom();
        Location to = event.getTo();
        if (from == null || to == null) {
            return;
        }
        double dx = to.getX() - from.getX();
        double dz = to.getZ() - from.getZ();
        double dxz = Math.sqrt(dx * dx + dz * dz);
        double dy = Math.abs(to.getY() - from.getY());
        if (dxz < 0.1 && dy < 0.5) {
            return;
        }
        Material fromMat;
        Material toMat;
        try {
            Block fromBlock = from.getBlock();
            Block toBlock = to.getBlock();
            if (fromBlock == null || toBlock == null) {
                return;
            }
            fromMat = fromBlock.getType();
            toMat = toBlock.getType();
            if (fromMat == null || toMat == null) {
                return;
            }
            if (!fromMat.isSolid() || !toMat.isSolid()) {
                return;
            }
        } catch (Throwable ignored) {
            return;
        }
        long now = System.currentTimeMillis();
        Long last = lastAlert.get(id);
        if (last != null && now - last < 250) {
            return;
        }
        lastAlert.put(id, now);
        flag(plugin.getDataManager().get(player), "through=" + toMat);
    }
}

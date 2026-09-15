package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.entity.EnderDragon;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.util.Vector;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * HitBox.A: портировано из NoCheatPlus Fight.Direction (GPL-3.0).
 * Математика CollisionUtil.directionCheck дословно: предсказание точки
 * взгляда на дистанции цели, поэтапный допуск (полуразмер + 2.6),
 * порог off > 0.1, VL += перпендикулярный промах, награда x0.8.
 * Нарушение гасит урон — по расширенным хитбоксам бить нельзя.
 */
public final class HitBoxA extends Check {

    private static final double PRECISION = 2.6D;

    private final Map<UUID, Double> directionVL = new ConcurrentHashMap<>();

    public HitBoxA(ElytrixFuckCheats plugin) {
        super(plugin, "HitBox", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        directionVL.remove(uuid);
    }

    /** NCP CollisionUtil.directionCheck, без отладочного вызова. */
    private static double directionCheck(double sourceX, double sourceY, double sourceZ,
            double dirX, double dirY, double dirZ,
            double targetX, double targetY, double targetZ,
            double targetWidth, double targetHeight, double precision) {
        double dirLength = Math.sqrt(dirX * dirX + dirY * dirY + dirZ * dirZ);
        if (dirLength == 0.0) {
            dirLength = 1.0;
        }

        double dX = targetX - sourceX;
        double dY = targetY - sourceY;
        double dZ = targetZ - sourceZ;

        double targetDist = Math.sqrt(dX * dX + dY * dY + dZ * dZ);

        double xPrediction = targetDist * dirX / dirLength;
        double yPrediction = targetDist * dirY / dirLength;
        double zPrediction = targetDist * dirZ / dirLength;

        double off = 0.0D;

        off += Math.max(Math.abs(dX - xPrediction) - (targetWidth / 2 + precision), 0.0D);
        off += Math.max(Math.abs(dZ - zPrediction) - (targetWidth / 2 + precision), 0.0D);
        off += Math.max(Math.abs(dY - yPrediction) - (targetHeight / 2 + precision), 0.0D);

        if (off > 1) {
            off = Math.sqrt(off);
        }

        return off;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getDamager();
        Entity damaged = event.getEntity();
        if (damaged instanceof EnderDragon) {
            return;
        }
        UUID uuid = player.getUniqueId();

        double width = damaged instanceof Player ? 0.6D : 1.0D;
        double height = damaged instanceof Player ? 1.8D : 2.0D;

        Location loc = player.getLocation();
        Location dLoc = damaged.getLocation();
        Vector direction = loc.getDirection();

        double off = directionCheck(loc.getX(), loc.getY() + 1.62D, loc.getZ(),
                direction.getX(), direction.getY(), direction.getZ(),
                dLoc.getX(), dLoc.getY() + height / 2.0D, dLoc.getZ(),
                width, height, PRECISION);

        if (off > 0.1) {
            double bx = dLoc.getX() - loc.getX();
            double by = dLoc.getY() + height / 2.0D - loc.getY() - 1.62D;
            double bz = dLoc.getZ() - loc.getZ();
            double dx = direction.getX();
            double dy = direction.getY();
            double dz = direction.getZ();
            double cx = by * dz - bz * dy;
            double cy = bz * dx - bx * dz;
            double cz = bx * dy - by * dx;
            double dirLen = Math.sqrt(dx * dx + dy * dy + dz * dz);
            if (dirLen == 0.0) {
                dirLen = 1.0;
            }
            double distance = Math.sqrt(cx * cx + cy * cy + cz * cz) / dirLen;

            directionVL.put(uuid, directionVL.getOrDefault(uuid, 0.0D) + distance);
            flag(plugin.getDataManager().get(player), String.format("off=%.2f", off));
            event.setCancelled(true);
        } else {
            directionVL.put(uuid, directionVL.getOrDefault(uuid, 0.0D) * 0.8D);
        }
    }
}

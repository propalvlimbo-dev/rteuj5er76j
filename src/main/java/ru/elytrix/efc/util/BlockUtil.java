package ru.elytrix.efc.util;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.block.Block;
import org.bukkit.block.BlockFace;
import org.bukkit.util.Vector;

/**
 * Геометрия блоков для мировых проверок: глаз к блоку, луч в блок,
 * сторона грани. Техники стандартные (как у Grim: closest-point,
 * slab-raytrace, face-side), код свой.
 */
public final class BlockUtil {

    private BlockUtil() {
    }

    /** Высота глаз: стоя и крадучись. */
    private static final double[] EYE_HEIGHTS = {1.62, 1.27};

    private static final Map<UUID, Long> LAST_BREAK = new ConcurrentHashMap<>();

    public static void noteBreak(UUID id) {
        if (id != null) {
            LAST_BREAK.put(id, System.currentTimeMillis());
        }
    }

    /** Ломал ли блок меньше ms назад (грейс связки сломал+поставил). */
    public static boolean brokeWithin(UUID id, long ms) {
        Long t = LAST_BREAK.get(id);
        return t != null && System.currentTimeMillis() - t <= ms;
    }

    public static void clear(UUID id) {
        LAST_BREAK.remove(id);
    }

    public static boolean isAir(Material material) {
        return material == Material.AIR
                || material == Material.CAVE_AIR
                || material == Material.VOID_AIR;
    }

    /** Минимальная дистанция от глаз до куба блока (обе высоты глаз). */
    public static double eyeToBlockDistance(Location feet, Block block) {
        double minX = block.getX();
        double maxX = minX + 1;
        double minY = block.getY();
        double maxY = minY + 1;
        double minZ = block.getZ();
        double maxZ = minZ + 1;
        double best = Double.MAX_VALUE;
        for (double h : EYE_HEIGHTS) {
            double ex = feet.getX();
            double ey = feet.getY() + h;
            double ez = feet.getZ();
            double dx = Math.max(minX - ex, Math.max(0, ex - maxX));
            double dy = Math.max(minY - ey, Math.max(0, ey - maxY));
            double dz = Math.max(minZ - ez, Math.max(0, ez - maxZ));
            double dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
            if (dist < best) {
                best = dist;
            }
        }
        return best;
    }

    /** Глаза внутри (расширенного) куба блока? */
    public static boolean eyeInsideBlock(Location feet, Block block, double expand) {
        double minX = block.getX() - expand;
        double maxX = minX + 1 + expand * 2;
        double minY = block.getY() - expand;
        double maxY = minY + 1 + expand * 2;
        double minZ = block.getZ() - expand;
        double maxZ = minZ + 1 + expand * 2;
        for (double h : EYE_HEIGHTS) {
            double ex = feet.getX();
            double ey = feet.getY() + h;
            double ez = feet.getZ();
            if (ex >= minX && ex <= maxX && ey >= minY && ey <= maxY && ez >= minZ && ez <= maxZ) {
                return true;
            }
        }
        return false;
    }

    /** Луч бьёт в куб блока? Slab-метод, dir единичный. */
    public static boolean rayHitsBlock(Vector origin, Vector dir, Block block,
                                       double expand, double maxDist) {
        double ox = origin.getX();
        double oy = origin.getY();
        double oz = origin.getZ();
        double minX = block.getX() - expand;
        double maxX = minX + 1 + expand * 2;
        double minY = block.getY() - expand;
        double maxY = minY + 1 + expand * 2;
        double minZ = block.getZ() - expand;
        double maxZ = minZ + 1 + expand * 2;
        double tmin = 0.0;
        double tmax = maxDist;
        double[] o = {ox, oy, oz};
        double[] d = {dir.getX(), dir.getY(), dir.getZ()};
        double[] lo = {minX, minY, minZ};
        double[] hi = {maxX, maxY, maxZ};
        for (int i = 0; i < 3; i++) {
            if (Math.abs(d[i]) < 1e-9) {
                if (o[i] < lo[i] || o[i] > hi[i]) {
                    return false;
                }
            } else {
                double t1 = (lo[i] - o[i]) / d[i];
                double t2 = (hi[i] - o[i]) / d[i];
                tmin = Math.max(tmin, Math.min(t1, t2));
                tmax = Math.min(tmax, Math.max(t1, t2));
            }
        }
        return tmax >= tmin;
    }

    /**
     * Глаза с кликабельной стороны грани? Только сторона, без латерали —
     * дальность судит FarPlace. Неизвестная грань — пропуск (легит важнее).
     */
    public static boolean faceReachable(Location feet, Block against, BlockFace face, double tol) {
        if (face == null) {
            return true;
        }
        double ex = feet.getX();
        double ez = feet.getZ();
        double eyMin = feet.getY() + EYE_HEIGHTS[1];
        double eyMax = feet.getY() + EYE_HEIGHTS[0];
        double minX = against.getX();
        double maxX = minX + 1;
        double minY = against.getY();
        double maxY = minY + 1;
        double minZ = against.getZ();
        double maxZ = minZ + 1;
        switch (face) {
            case NORTH:
                return ez <= minZ + tol;
            case SOUTH:
                return ez >= maxZ - tol;
            case EAST:
                return ex >= maxX - tol;
            case WEST:
                return ex <= minX + tol;
            case UP:
                return eyMax >= maxY - tol;
            case DOWN:
                return eyMin <= minY + tol;
            default:
                return true;
        }
    }
}

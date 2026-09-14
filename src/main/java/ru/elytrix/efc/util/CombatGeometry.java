package ru.elytrix.efc.util;

import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.util.Vector;

/**
 * Геометрия боя по образцу Hawk (AABB.distanceToPosition, EntityInteractDirection).
 * Хитбокс игрока 0.6 x 1.8. Своя арифметика — стандартная математика луча и бокса.
 */
public final class CombatGeometry {

    private CombatGeometry() {
    }

    /** Расстояние от глаза атакующего до хитбокса жертвы (Hawk: distanceToPosition). */
    public static double eyeToBoxDistance(Player attacker, Player victim, double border) {
        Location eye = attacker.getEyeLocation();
        Location feet = victim.getLocation();
        double minX = feet.getX() - 0.3 - border;
        double maxX = feet.getX() + 0.3 + border;
        double minY = feet.getY() - border;
        double maxY = feet.getY() + 1.8 + border;
        double minZ = feet.getZ() - 0.3 - border;
        double maxZ = feet.getZ() + 0.3 + border;
        double dx = Math.max(minX - eye.getX(), Math.max(0, eye.getX() - maxX));
        double dy = Math.max(minY - eye.getY(), Math.max(0, eye.getY() - maxY));
        double dz = Math.max(minZ - eye.getZ(), Math.max(0, eye.getZ() - maxZ));
        return Math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    /** Луч взгляда пересекает хитбокс жертвы? (Hawk: betweenRays, slab-метод). */
    public static boolean rayHitsBox(Player attacker, Player victim, double expand, double maxDist) {
        Location eye = attacker.getEyeLocation();
        Vector dir = eye.getDirection();
        double ox = eye.getX();
        double oy = eye.getY();
        double oz = eye.getZ();
        Location feet = victim.getLocation();
        double minX = feet.getX() - 0.3 - expand;
        double maxX = feet.getX() + 0.3 + expand;
        double minY = feet.getY() - expand;
        double maxY = feet.getY() + 1.8 + expand;
        double minZ = feet.getZ() - 0.3 - expand;
        double maxZ = feet.getZ() + 0.3 + expand;
        double tmin = 0.0;
        double tmax = maxDist;
        double[][] axes = {
                {ox, dir.getX(), minX, maxX},
                {oy, dir.getY(), minY, maxY},
                {oz, dir.getZ(), minZ, maxZ},
        };
        for (double[] ax : axes) {
            double origin = ax[0];
            double d = ax[1];
            if (Math.abs(d) < 1e-9) {
                if (origin < ax[2] || origin > ax[3]) {
                    return false;
                }
            } else {
                double t1 = (ax[2] - origin) / d;
                double t2 = (ax[3] - origin) / d;
                tmin = Math.max(tmin, Math.min(t1, t2));
                tmax = Math.min(tmax, Math.max(t1, t2));
            }
        }
        return tmax >= tmin;
    }
}

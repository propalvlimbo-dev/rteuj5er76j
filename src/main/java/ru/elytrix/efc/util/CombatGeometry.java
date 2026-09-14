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

    /** Луч из глаза по взгляду пересекает хитбокс жертвы? (Hawk: betweenRays, slab-метод). */
    public static boolean rayHitsBox(Player attacker, Player victim, double expand, double maxDist) {
        Location eye = attacker.getEyeLocation();
        return rayHitsBoxDir(eye.toVector(), eye.getDirection(), victim, expand, maxDist);
    }

    /** Тот же тест, но луч задан явно (нужен для экстраполированного луча Hawk). */
    public static boolean rayHitsBoxDir(Vector origin, Vector dir, Player victim,
                                        double expand, double maxDist) {
        double ox = origin.getX();
        double oy = origin.getY();
        double oz = origin.getZ();
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
            double o = ax[0];
            double d = ax[1];
            if (Math.abs(d) < 1e-9) {
                if (o < ax[2] || o > ax[3]) {
                    return false;
                }
            } else {
                double t1 = (ax[2] - o) / d;
                double t2 = (ax[3] - o) / d;
                tmin = Math.max(tmin, Math.min(t1, t2));
                tmax = Math.min(tmax, Math.max(t1, t2));
            }
        }
        return tmax >= tmin;
    }

    /** Вектор взгляда из yaw/pitch (стандартная формула Minecraft). */
    public static Vector dirFromYawPitch(float yaw, float pitch) {
        double pitchRad = Math.toRadians(pitch);
        double yawRad = Math.toRadians(yaw);
        double y = -Math.sin(pitchRad);
        double xz = Math.cos(pitchRad);
        return new Vector(-Math.sin(yawRad) * xz, y, Math.cos(yawRad) * xz);
    }
}

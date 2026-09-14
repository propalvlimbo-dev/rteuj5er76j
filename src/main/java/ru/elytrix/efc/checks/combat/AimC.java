package ru.elytrix.efc.checks.combat;

import org.bukkit.Location;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Aim.C: удар мимо взгляда — бьёт туда, куда не смотрит.
 * Угол между взглядом и жертвой >100° невозможен честно
 * (хитбоксы и сайлент-ауры палятся именно здесь).
 */
public final class AimC extends Check {

    public AimC(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "C", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity victim = DamageUtil.entityOf(event);
        if (victim == null) {
            return;
        }
        Location eye = attacker.getLocation();
        Location target = victim.getLocation();

        double yaw = Math.toRadians(eye.getYaw());
        double pitch = Math.toRadians(eye.getPitch());
        double lookX = -Math.sin(yaw) * Math.cos(pitch);
        double lookY = -Math.sin(pitch);
        double lookZ = Math.cos(yaw) * Math.cos(pitch);

        double dx = target.getX() - eye.getX();
        double dy = (target.getY() + 0.9) - (eye.getY() + 1.62);
        double dz = target.getZ() - eye.getZ();
        double length = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (length < 0.000001) {
            return;
        }
        double dot = (lookX * dx + lookY * dy + lookZ * dz) / length;
        dot = Math.max(-1.0, Math.min(1.0, dot));
        double angle = Math.toDegrees(Math.acos(dot));
        if (angle > cfg("max-angle", 100.0)) {
            flag(plugin.getDataManager().get(attacker), "angle " + Math.round(angle));
        }
    }
}

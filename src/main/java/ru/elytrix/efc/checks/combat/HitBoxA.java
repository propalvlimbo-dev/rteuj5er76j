package ru.elytrix.efc.checks.combat;

import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * HitBox.A: угол между взглядом атакующего и направлением на цель.
 * Расширенный хитбокс бьёт мимо прицела (30-90°+). Легит ~0-10°.
 * Порог 30°, дистанция от 1.2 (в упор углы шумят). Удар гасится.
 */
public final class HitBoxA extends Check {

    public HitBoxA(ElytrixFuckCheats plugin) {
        super(plugin, "HitBox", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player) || !(event.getEntity() instanceof Player)) {
            return;
        }
        Player attacker = (Player) event.getDamager();
        if (attacker.getGameMode() == GameMode.CREATIVE) {
            return;
        }
        Location eye = attacker.getEyeLocation();
        Location victim = event.getEntity().getLocation();
        double tx = victim.getX() - eye.getX();
        double ty = victim.getY() + 0.9D - eye.getY();
        double tz = victim.getZ() - eye.getZ();
        double dist = Math.sqrt(tx * tx + ty * ty + tz * tz);
        if (dist < 1.2D || dist > 7.0D) {
            return;
        }
        double yaw = Math.toRadians(eye.getYaw());
        double pitch = Math.toRadians(eye.getPitch());
        double lx = -Math.sin(yaw) * Math.cos(pitch);
        double ly = -Math.sin(pitch);
        double lz = Math.cos(yaw) * Math.cos(pitch);
        double dot = (lx * tx + ly * ty + lz * tz) / dist;
        dot = Math.min(1.0D, Math.max(-1.0D, dot));
        double angle = Math.toDegrees(Math.acos(dot));
        if (angle > 30.0D) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(attacker), String.format("%.1fdeg", angle));
        }
    }
}

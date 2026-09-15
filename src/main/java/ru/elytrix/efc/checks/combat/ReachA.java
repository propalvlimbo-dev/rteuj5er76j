package ru.elytrix.efc.checks.combat;

import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Reach.A: дистанция удара от глаз атакующего до ближайшей точки цели.
 * Ванилла 1.16: 3.0 блока. Порог 3.6 (пинг + движение). Удар гасится.
 */
public final class ReachA extends Check {

    public ReachA(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player) || !(event.getEntity() instanceof LivingEntity)) {
            return;
        }
        Player attacker = (Player) event.getDamager();
        if (attacker.getGameMode() == GameMode.CREATIVE) {
            return;
        }
        Location eye = attacker.getEyeLocation();
        Location victim = event.getEntity().getLocation();
        double closestY = Math.min(Math.max(eye.getY(), victim.getY()), victim.getY() + 1.8D);
        double dx = eye.getX() - victim.getX();
        double dy = eye.getY() - closestY;
        double dz = eye.getZ() - victim.getZ();
        double distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (distance > 3.6D) {
            event.setCancelled(true);
            flag(plugin.getDataManager().get(attacker), String.format("%.2f", distance));
        }
    }
}

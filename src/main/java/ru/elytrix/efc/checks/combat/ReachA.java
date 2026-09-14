package ru.elytrix.efc.checks.combat;

import org.bukkit.Location;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.CombatGeometry;
import ru.elytrix.efc.util.DamageUtil;

/**
 * Reach.A: дистанция глаз-&gt;хитбокс (порт Hawk EntityInteractReach).
 * Позиция жертвы — из перемотки (лаг-компенсация), поэтому база 3.0
 * как у Grim. Удар за лимитом СРАЗУ отменяется. Только игроки.
 */
public final class ReachA extends Check {

    public ReachA(ElytrixFuckCheats plugin) {
        super(plugin, "Reach", "A", Category.COMBAT);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        Entity rawVictim = DamageUtil.entityOf(event);
        if (!(rawVictim instanceof Player)) {
            return;
        }
        if (plugin.getExemptionManager().isExempt(attacker, getCategory())) {
            return;
        }
        try {
            if (event.isCancelled()) {
                return;
            }
        } catch (Throwable ignored) {
            return;
        }
        Player victim = (Player) rawVictim;
        long now = System.currentTimeMillis();
        long delay = Math.max(0, Math.min(1000,
                (DamageUtil.pingOf(attacker) + DamageUtil.pingOf(victim)) / 2 + 50));
        Location eye = attacker.getEyeLocation();
        Location feet = plugin.getPositionHistory().locationAt(victim, now - delay);
        double distance = CombatGeometry.eyeToBoxDistance(eye, feet, 0.1);
        double limit = DamageUtil.reachLimit(attacker, victim,
                cfg("base", 3.0), cfg("per-ms", 0.002), cfg("cap", 3.6));
        if (distance > limit) {
            flag(plugin.getDataManager().get(attacker),
                    "dist " + String.format("%.2f", distance)
                            + ">" + String.format("%.2f", limit) + " blocked");
            try {
                event.setCancelled(true);
            } catch (Throwable ignored) {
                // Форк без отмены урона — хотя бы флаг останется.
            }
        }
    }
}
